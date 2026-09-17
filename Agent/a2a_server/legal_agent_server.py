#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: legal_agent_server.py
作者: 智租顾问 (Zhizu Advisor)
描述: 法律问答 RAG 智能体服务器（Agentic RAG 跨引擎调用载体）。
      - 作为 A2A 子 Agent（端口 5010）暴露法律知识库检索问答能力
      - RecommendAgent 编排器可跨引擎调用本 Agent（如"房源 + 房东不退押金"混合查询）
      - 内部复用 legal_qa/IntegratedQASystem（Redis 缓存 -> BM25 -> Agentic RAG 反思循环）
      - 懒加载初始化（首次请求时加载，避免阻塞启动）
"""
import os
import sys
import time
import threading

# 路径配置：把项目根目录加入 sys.path，支持 from Agent.xxx import 绝对路径导入
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from python_a2a import (run_server, A2AServer, AgentCard, AgentSkill,
                        TaskStatus, TaskState)

from Agent.create_logger import logger


class LegalQueryServer(A2AServer):
    """法律问答 RAG A2A 服务器：输入法律问题 -> 返回 RAG 检索增强答案（含反思轨迹）。"""

    def __init__(self, agent_card):
        super().__init__(agent_card=agent_card)
        self._qa = None
        self._qa_lock = threading.Lock()
        self._qa_error = None

    def _get_qa(self):
        """懒加载 IntegratedQASystem（含 Redis/MySQL/Milvus + BERT 分类器 + RAG 引擎）"""
        if self._qa is not None:
            return self._qa
        with self._qa_lock:
            if self._qa is not None:
                return self._qa
            if self._qa_error:
                return None
            try:
                old_cwd = os.getcwd()
                legal_qa_path = os.path.join(PROJECT_ROOT, "Agent", "legal_qa")
                os.chdir(legal_qa_path)
                try:
                    from Agent.legal_qa.new_main import IntegratedQASystem
                    self._qa = IntegratedQASystem()
                finally:
                    os.chdir(old_cwd)
                logger.info("LegalQueryServer: RAG 问答系统初始化完成")
                return self._qa
            except Exception as e:
                self._qa_error = str(e)
                logger.error(f"LegalQueryServer: RAG 问答系统初始化失败: {e}")
                return None

    def handle_task(self, task):
        """处理法律问答任务：提取问题 -> 走 Agentic RAG -> 返回文本答案"""
        content = (task.message or {}).get("content", {})
        question = content.get("text", "") if isinstance(content, dict) else ""
        question = (question or "").strip()
        logger.info(f"LegalQueryServer 收到法律咨询: {question}")
        if not question:
            task.status = TaskStatus(state=TaskState.INPUT_REQUIRED,
                                     message={"role": "agent", "content": {"text": "请提供您的法律咨询问题，例如'房东不退押金怎么办？'"}})
            return task

        qa = self._get_qa()
        if qa is None:
            task.status = TaskStatus(state=TaskState.FAILED,
                                     message={"role": "agent",
                                              "content": {"text": f"法律知识库服务暂不可用（{self._qa_error}），请检查 MySQL/Redis/Milvus 是否启动。"}})
            return task

        try:
            start_t = time.time()
            collected = ""
            refs = []
            # 注意: 这里不传 session_id, 保持无状态（跨引擎调用不做会话持久化）
            for item in qa.query(question, agentic=True):
                token = item[0]
                if token == "__REFERENCES__":
                    if len(item) > 1:
                        refs = item[1]
                    continue
                if token:
                    collected += token
                if len(item) > 1 and item[1]:
                    break

            elapsed = round(time.time() - start_t, 1)
            logger.info(f"LegalQueryServer 回答完成 (耗时 {elapsed}s, {len(collected)}字)")

            # 附加引用条文
            if refs:
                ref_lines = []
                for r in refs:
                    if isinstance(r, dict):
                        law = r.get('law', '')
                        art = r.get('article', '')
                        snip = (r.get('snippet') or '')[:120]
                        head = f"《{law}》" if law else ""
                        if art:
                            a = str(art).strip()
                            # 规范化条文号：兼容 "第三十五条" / "35" / "第35条" 等写法
                            if a.endswith("条"):
                                a = a[:-1]
                            a = a.lstrip("第")
                            if not a[0].isdigit():
                                a = f"第{a}"
                            head += f"{a}条"
                        ref_lines.append(f"- {head}：{snip}" if head else f"- {snip}")
                collected += "\n\n**引用条文**：\n" + "\n".join(ref_lines)

            if not collected.strip():
                collected = "未找到相关法律答案。"
            task.artifacts = [{"parts": [{"type": "text", "text": collected.strip()}]}]
            task.status = TaskStatus(state=TaskState.COMPLETED)
            return task
        except Exception as e:
            logger.error(f"LegalQueryServer 查询失败: {e}")
            task.status = TaskStatus(state=TaskState.FAILED,
                                     message={"role": "agent",
                                              "content": {"text": f"法律咨询失败: {e}"}})
            return task


if __name__ == "__main__":
    agent_card = AgentCard(
        name="LegalQueryAssistant",
        description="基于RAG法律知识库提供租房法律咨询的助手（押金/合同/租金纠纷等），支持 Agentic RAG 检索增强问答",
        url="http://localhost:5010",
        version="1.0.0",
        capabilities={"streaming": False, "memory": False},
        skills=[
            AgentSkill(
                name="legal query",
                description="法律知识检索问答，支持租房相关的法律问题咨询",
                examples=["房东不退押金怎么办？", "租房合同没到期房东涨房租合法吗？"]
            )
        ]
    )
    server = LegalQueryServer(agent_card=agent_card)
    logger.info("=== LegalQueryServer 信息 ===")
    logger.info(f"名称: {server.agent_card.name}")
    logger.info(f"描述: {server.agent_card.description}")

    # (Agentic RAG) 后台预热：首次请求前完成 RAG 系统初始化（约80s），避免首个请求超时
    def _warmup():
        try:
            server._get_qa()
            logger.info("LegalQueryServer 预热完成，RAG 系统就绪")
        except Exception as e:
            logger.error(f"LegalQueryServer 预热失败: {e}")

    threading.Thread(target=_warmup, daemon=True).start()
    run_server(server, host="127.0.0.1", port=5010)
