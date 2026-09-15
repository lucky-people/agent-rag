# -*- coding: utf-8 -*-
"""一次性脚本：recommend_server 真编排改造
- 新增 OrchestratedRecommendQueryServer 子类：多维度组合查询时并行调用 house/poi/metro 三个子 agent 并汇总
- 单维度查询/子agent不可用时降级回退原 text2sql 路径（保证可用性不倒退）
"""
import io
import os
import subprocess
import sys

p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Agent', 'a2a_server', 'recommend_server.py')
with io.open(p, 'r', encoding='utf-8') as f:
    text = f.read()

# 1) import 增加 AgentNetwork/Message/TextContent/MessageRole/Task
old_imp = '''from python_a2a import A2AServer, run_server, AgentCard, AgentSkill, TaskStatus, TaskState'''
new_imp = '''from python_a2a import (A2AServer, run_server, AgentCard, AgentSkill,
                        TaskStatus, TaskState, AgentNetwork,
                        Message, TextContent, MessageRole, Task)'''
if old_imp in text:
    text = text.replace(old_imp, new_imp, 1)
    print('[import] OK')
else:
    print('[import] WARN')

# 2) 在 handle_task 之前插入编排逻辑类（挂在 RecommendQueryServer 之后、__main__ 之前）
orchestrator_code = '''

# ============================================================
# 编排增强（Orchestrator）：
# 当用户查询涉及 2 个及以上子域（房源/POI/地铁）时，RecommendAgent
# 作为编排器并行调用 House/Poi/Metro 三个子 Agent，再汇总结果。
# 单维度查询或子 Agent 不可用时，自动降级回退到原 text2sql 路径。
# ============================================================

# 子 Agent 注册表：领域 -> (意图名, A2A地址, 汇总标题)
SUB_AGENTS = {
    "house":   ("HouseQueryAssistant",   "http://localhost:5006", "🏠 房源推荐"),
    "poi":     ("PoiQueryAssistant",     "http://localhost:5007", "📍 周边景点/POI"),
    "metro":   ("MetroQueryAssistant",   "http://localhost:5008", "🚇 地铁出行"),
}

# 多维度拆解提示词：判断用户问题涉及哪些子域，并生成对应的子查询
split_prompt = ChatPromptTemplate.from_template(
    """
你是郑州租房综合推荐任务的编排拆解器。请判断用户问题涉及哪些数据域，并为每个涉及的域生成一个独立的子查询问题。

可用的数据域：
- house：房源（租金/区域/户型/面积/朝向/楼层/地铁线路）
- poi：周边景点/公园/餐饮/医疗/住宿等POI
- metro：地铁线路/站点/换乘

输出要求：只输出 JSON，格式为：
{{"domains": ["house"], "sub_queries": {{"house": "金水区2000元以下的整租房源"}}}}
- domains 列出所有涉及的域（1-3个）
- sub_queries 为每个域生成一个独立、自包含的子查询问题（不要引用其他域的结果）
- 如果问题只涉及单一域，domains 只有一个元素
- 如果问题与租房无关（问候、闲聊、法律），domains 为空数组

用户问题: {question}
    """
)


class OrchestratedRecommendQueryServer(RecommendQueryServer):
    """综合推荐编排器：多维度查询并行调度子Agent，单维度/降级走原text2sql"""

    def __init__(self):
        super().__init__()
        self.network = AgentNetwork(name="RecommendOrchestrator")
        for intent_name, url, _ in SUB_AGENTS.values():
            self.network.add(intent_name, url)

    def _split_domains(self, conversation: str) -> dict:
        """用LLM拆解用户问题为多域子查询；失败时保守回退（视为单域house）"""
        try:
            chain = self.split_prompt | self.llm
            out = chain.invoke({"question": conversation}).content.strip()
            parsed = robust_json_loads(out)
            if isinstance(parsed, dict) and isinstance(parsed.get("domains"), list):
                domains = [d for d in parsed["domains"] if d in SUB_AGENTS]
                sub_queries = parsed.get("sub_queries", {})
                if domains:
                    return {"domains": domains, "sub_queries": sub_queries}
        except Exception as e:
            logger.error(f"编排拆解失败，回退单域: {str(e)}")
        return {"domains": ["house"], "sub_queries": {"house": conversation}}

    async def _call_sub_agent(self, intent_name: str, url: str, sub_query: str, timeout: float = 20.0):
        """调用单个子Agent，返回 (域, 文本结果)；失败返回 None"""
        try:
            agent = self.network.get_agent(intent_name)
            msg = Message(content=TextContent(text=sub_query), role=MessageRole.USER)
            task = Task(id="task-" + str(uuid.uuid4()), message=msg.to_dict())
            raw = await asyncio.wait_for(agent.send_task_async(task), timeout=timeout)
            # 提取文本结果
            import re as _re
            text_result = raw if isinstance(raw, str) else str(raw)
            # A2A 返回可能是 dict/object，尝试取 artifacts 文本
            if isinstance(raw, dict):
                artifacts = raw.get("artifacts") or []
                parts = []
                for art in artifacts:
                    for part in art.get("parts", []) if isinstance(art, dict) else []:
                        if part.get("type") == "text":
                            parts.append(part.get("text", ""))
                text_result = "\\n".join(parts) if parts else text_result
            return {"domain": intent_name, "text": text_result.strip()}
        except asyncio.TimeoutError:
            logger.warning(f"子Agent {intent_name} 调用超时")
            return None
        except Exception as e:
            logger.warning(f"子Agent {intent_name} 调用失败: {str(e)}")
            return None

    def handle_task(self, task):
        """多维度组合查询 → 并行编排；否则降级回退原逻辑"""
        content = (task.message or {}).get("content", {})
        conversation = content.get("text", "") if isinstance(content, dict) else ""
        if not conversation.strip():
            return super().handle_task(task)

        split = self._split_domains(conversation)
        domains = split.get("domains", [])
        # 仅当明确涉及 2 个及以上子域才走编排；否则走原 text2sql 单域路径
        if len(domains) < 2:
            return super().handle_task(task)

        logger.info(f"[编排] 检测到多维度查询: {domains}")
        sub_queries = split.get("sub_queries", {})
        try:
            # 并行调用子Agent
            async def _run_all():
                coros = []
                for d in domains:
                    intent_name, url, _ = SUB_AGENTS[d]
                    q = sub_queries.get(d, conversation)
                    coros.append(self._call_sub_agent(intent_name, url, q))
                results = await asyncio.gather(*coros)
                return results

            results = asyncio.run(_run_all())
            valid = [r for r in results if r and r.get("text")]
            if not valid:
                logger.warning("[编排] 子Agent全部不可用，降级回退 text2sql")
                return super().handle_task(task)

            # 汇总
            sections = []
            for r in valid:
                title = SUB_AGENTS.get(r["domain"], (None, None, r["domain"]))[2]
                sections.append(f"{title}：\\n{r['text']}")
            combined = "\\n\\n".join(sections)
            task.artifacts = [{"parts": [{"type": "text", "text": combined}]}]
            task.status = TaskStatus(state=TaskState.COMPLETED)
            return task
        except Exception as e:
            logger.error(f"[编排] 汇总失败，降级回退 text2sql: {str(e)}")
            return super().handle_task(task)


'''
anchor = "if __name__ == \"__main__\":"
if orchestrator_code in text:
    print('[orchestrator] already present')
else:
    idx = text.find(anchor)
    if idx == -1:
        print('[orchestrator] WARN: __main__ anchor not found')
    else:
        text = text[:idx] + orchestrator_code + "\n" + text[idx:]
        print('[orchestrator] OK')

# 3) __main__ 使用编排版服务器
old_main = '''    recommend_server = RecommendQueryServer()'''
new_main = '''    recommend_server = OrchestratedRecommendQueryServer()'''
if old_main in text:
    text = text.replace(old_main, new_main, 1)
    print('[main use orchestrator] OK')
else:
    print('[main use orchestrator] WARN')

with io.open(p, 'w', encoding='utf-8', newline='') as f:
    f.write(text)
r = subprocess.run([sys.executable, '-m', 'py_compile', p], capture_output=True, text=True)
print('compile:', 'OK' if r.returncode == 0 else 'FAIL\\n' + r.stderr[:600])
