#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: base_text2sql_server.py
作者: 智租顾问 (Zhizu Advisor)
描述: Text2SQL 智能体服务器抽象基类。
      4 个 A2A server（House/Poi/Metro/Recommend）的
      generate_sql_query / regenerate_sql / handle_task 三段逻辑逐字重复，
      统一收敛到本基类；子类只需提供：
        - getter：异步查询函数（调用 MCP，返回 JSON 字符串/对象）
        - formatter：结果格式化函数（data -> 美观文本）
        - input_required_msg：无法生成 SQL 时的追问文案
        - sql_prompt / fix_sql_prompt / schema：LLM 提示词与表结构
"""

import asyncio
import json
import time
from datetime import datetime
import pytz

from python_a2a import A2AServer, TaskStatus, TaskState

from Agent.create_logger import logger
from Agent.utils.format import robust_json_loads, extract_sql


class Text2SqlAgentServer(A2AServer):
    """通用 Text2SQL A2A 服务器：LLM 生成 SQL → 调 MCP → 格式化返回。

    子类在 __init__ 中调用 super().__init__(agent_card=...) 后，再设置：
        self.sql_prompt / self.fix_sql_prompt / self.schema
        self.getter / self.formatter / self.input_required_msg
    """

    def __init__(self, agent_card):
        super().__init__(agent_card=agent_card)
        self.sql_prompt = None
        self.fix_sql_prompt = None
        self.schema = ""
        self.getter = None          # async def getter(sql) -> str/dict
        self.formatter = None       # def formatter(data: list) -> str
        self.input_required_msg = "查询无效，请提供更多筛选条件。"

    # 定义生成SQL查询方法，输入对话历史，返回SQL或追问JSON
    def generate_sql_query(self, conversation: str) -> dict:
        try:
            # 组装链
            chain = self.sql_prompt | self.llm
            # 调用链
            current_date = datetime.now(pytz.timezone('Asia/Shanghai')).strftime('%Y-%m-%d')  # 获取当前日期，格式化为字符串
            output = chain.invoke({"conversation": conversation, "current_date": current_date, "table_schema_string": self.schema}).content.strip()
            logger.info(f"原始 LLM 输出: {output}")

            # 1) 优先尝试解析为 JSON（追问场景）
            try:
                parsed = robust_json_loads(output)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass  # 非 JSON，继续按 SQL 处理

            # 2) 从输出中提取纯 SQL（容忍代码围栏、"输出:"标签等杂文）
            sql = extract_sql(output)
            if sql:
                return {"status": "sql", "sql": sql}

            return {"status": "input_required", "message": self.input_required_msg}  # 返回追问JSON
        except Exception as e:
            logger.error(f"SQL生成失败: {str(e)}")
            return {"status": "input_required", "message": self.input_required_msg}  # 返回追问JSON

    def regenerate_sql(self, conversation: str, last_sql: str, feedback: str) -> str:
        """根据执行反馈（SQL报错/查询结果为空）让 LLM 重新生成（修正或放宽）SQL"""
        try:
            chain = self.fix_sql_prompt | self.llm
            current_date = datetime.now(pytz.timezone('Asia/Shanghai')).strftime('%Y-%m-%d')
            output = chain.invoke({
                "conversation": conversation,
                "last_sql": last_sql,
                "feedback": feedback,
                "table_schema_string": self.schema,
                "current_date": current_date,
            }).content.strip()
            sql = extract_sql(output)
            logger.info(f"修正/放宽后 SQL: {sql}")
            return sql or last_sql
        except Exception as e:
            logger.error(f"SQL 修正失败: {str(e)}")
            return last_sql

    # 处理任务：提取输入，生成SQL，调用MCP，格式化结果
    def handle_task(self, task):
        # 1 提取输入
        content = (task.message or {}).get("content", {})  # 从消息中获取内容
        # 提取conversation，即客户端发起的任务中的query语句
        conversation = content.get("text", "") if isinstance(content, dict) else ""
        logger.info(f"对话历史及用户问题: {conversation}")

        try:
            # 2 基于用户问题生成SQL查询
            gen_result = self.generate_sql_query(conversation)
            # 检查是否需要追问，如果是则添加追问消息后返回任务
            if gen_result["status"] == "input_required":
                # 追问逻辑，这里是指在无法正常生成sql时，设置任务状态为输入所需，添加追问消息
                task.status = TaskStatus(state=TaskState.INPUT_REQUIRED,
                                         message={"role": "agent", "content": {"text": gen_result["message"]}})
                return task

            # 否则则提取SQL查询，并进行MCP调用
            sql_query = gen_result["sql"]  #
            logger.info(f"生成的SQL查询: {sql_query}")

            # 3 带重试的查询循环（P1-3 执行报错自动纠错 / P1-4 空结果自动放宽条件）
            max_attempts = 3
            response_text = None
            for attempt in range(1, max_attempts + 1):
                logger.info(f"查询尝试 {attempt}/{max_attempts}: {sql_query}")
                raw_result = asyncio.run(self.getter(sql_query))

                # 4 格式化结果
                response = json.loads(raw_result) if isinstance(raw_result, str) else raw_result
                logger.info(f"MCP 返回: {response}")
                # 检查响应状态
                if response.get("status") == "success":
                    data = response.get("data", [])  # 提取数据列表
                    response_text = self.formatter(data)  # 格式化为美观的编号列表
                    task.artifacts = [{"parts": [{"type": "text", "text": response_text}]}]
                    task.status = TaskStatus(state=TaskState.COMPLETED)
                    return task
                elif response.get("status") == "connection_error":
                    # 基础设施故障（MCP未启动/超时）→ 瞬时故障自动重试（不浪费 LLM 调用去"修正SQL"）
                    if attempt < max_attempts:
                        logger.warning(f"连接失败（第 {attempt}/{max_attempts} 次）：{response.get('message', '')}，0.5s 后自动重试...")
                        time.sleep(0.5)  # 短暂等待，给服务恢复时间
                        continue
                    task.status = TaskStatus(state=TaskState.FAILED,
                                             message={"role": "agent",
                                                      "content": {"text": response.get("message", "服务暂不可用，请稍后重试。")}})
                    return task
                elif response.get("status") == "error":
                    # P1-3：SQL 执行报错 → 反馈给 LLM 修正后重试
                    if attempt < max_attempts:
                        err_msg = response.get("message", "SQL执行错误")
                        logger.warning(f"SQL 执行错误，尝试修正重试: {err_msg}")
                        new_sql = self.regenerate_sql(conversation, sql_query, f"SQL执行报错：{err_msg}")
                        if new_sql and new_sql != sql_query:
                            sql_query = new_sql
                            continue
                        break
                    task.status = TaskStatus(state=TaskState.FAILED,
                                             message={"role": "agent", "content": {"text": f"查询失败: {response.get('message', '未知错误')}"}})
                    return task
                elif response.get("status") == "no_data":
                    # P1-4：查询结果为空 → 放宽筛选条件重查
                    if attempt < max_attempts:
                        logger.warning("查询结果为空，尝试放宽条件重查")
                        new_sql = self.regenerate_sql(conversation, sql_query, "查询结果为空，请放宽筛选条件（去掉过严限制、扩大范围）后重新生成一条更宽松的SQL")
                        if new_sql and new_sql != sql_query:
                            sql_query = new_sql
                            continue
                        break
                    task.status = TaskStatus(state=TaskState.INPUT_REQUIRED,
                                             message={"role": "agent", "content": {"text": "未找到符合条件的查询结果，已尝试放宽条件仍无结果，请换个说法再试。"}})
                    return task
                else:
                    response_text = response.get("message", "查询失败，请重试或提供更多细节。")
                    task.status = TaskStatus(state=TaskState.FAILED,
                                             message={"role": "agent", "content": {"text": response_text}})
                    return task

            # 重试耗尽仍未成功
            if response_text is None:
                response_text = "未找到符合条件的查询结果，已尝试放宽条件仍无结果，请换个说法再试。"
            task.status = TaskStatus(state=TaskState.INPUT_REQUIRED,
                                     message={"role": "agent", "content": {"text": response_text}})
            return task
        except Exception as e:  # 捕获异常
            logger.error(f"查询失败: {str(e)}")

            # 设置任务状态为失败，添加错误信息
            task.status = TaskStatus(state=TaskState.FAILED,
                                     message={"role": "agent",
                                              "content": {"text": f"查询失败: {str(e)} 请重试或提供更多细节。"}})
            return task
