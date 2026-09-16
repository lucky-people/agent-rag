#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: recommend_server.py
作者: 智租顾问 (Zhizu Advisor)
描述: 综合推荐agent服务器，基于 rental 库的 house_listing、poi_data、metro_station 三张表
"""
import os
import sys
import json
import asyncio
import uuid

# 路径配置：把项目根目录加入 sys.path，支持 from Agent.xxx import 绝对路径导入
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from Agent.a2a_server.base_text2sql_server import Text2SqlAgentServer
from python_a2a import (run_server, AgentCard, AgentSkill,
                        TaskStatus, TaskState, AgentNetwork,
                        Message, TextContent, MessageRole, Task)
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

from Agent.config import Config
from Agent.create_logger import logger
from Agent.utils.format import format_exception, robust_json_loads

conf = Config()

# 初始化LLM
llm = ChatOpenAI(
    model=conf.model_name,
    base_url=conf.base_url,
    api_key=conf.api_key,
    temperature=0.1,
    request_timeout=10,
    max_retries=1
)

# 数据表 schema
table_schema_string = """  # 定义房源/POI/地铁表的SQL schema字符串，用于Prompt上下文
CREATE TABLE house_listing (
    id INT AUTO_INCREMENT PRIMARY KEY,
    house_id VARCHAR(50) NOT NULL COMMENT '房源ID',
    district VARCHAR(50) COMMENT '区域（如 金水区/中原区/二七区）',
    community TEXT COMMENT '小区名称',
    layout TEXT COMMENT '户型（如 3室2厅2卫）',
    area DECIMAL(10,2) COMMENT '面积m²',
    rent INT COMMENT '月租金（元）',
    metro_line VARCHAR(50) COMMENT '地铁线路（如 1号线）',
    walk_minutes INT COMMENT '距地铁步行分钟',
    status VARCHAR(20) DEFAULT '在租' COMMENT '在租/已租/下架',
    detail_url VARCHAR(255) COMMENT '详情页链接'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='房源表';

CREATE TABLE poi_data (
    id INT AUTO_INCREMENT PRIMARY KEY,
    poi_id VARCHAR(50) NOT NULL COMMENT '高德POI ID',
    name VARCHAR(255) NOT NULL COMMENT '名称',
    type VARCHAR(100) COMMENT '大类（旅游景点/公园广场/医疗保健/住宿服务/餐饮服务）',
    address VARCHAR(255) COMMENT '地址',
    adname VARCHAR(50) COMMENT '区县（如 金水区）',
    nearest_metro VARCHAR(100) COMMENT '最近地铁站',
    nearest_metro_line VARCHAR(50) COMMENT '最近地铁线路',
    distance_to_metro INT COMMENT '到最近地铁站距离(米)'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='POI数据表';

CREATE TABLE metro_station (
    id INT AUTO_INCREMENT PRIMARY KEY,
    poi_id VARCHAR(50) NOT NULL COMMENT '高德POI ID',
    name VARCHAR(100) NOT NULL COMMENT '地铁站名',
    line_name VARCHAR(50) COMMENT '所属线路（如 1号线）',
    address VARCHAR(255) COMMENT '地址'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='地铁站表';
"""

# 生成SQL的提示词
sql_prompt = ChatPromptTemplate.from_template(
    """
系统提示：你是一个专业的郑州综合推荐SQL生成器，需要从对话历史（含用户的问题）中提取关键信息，然后基于house_listing、poi_data、metro_station表生成SELECT语句，输出综合推荐。
- **约束完整性（最高优先级）**：用户明确提到的每个筛选条件（区域、价格、地铁、户型、类型、线路等）必须逐一转成 WHERE 条件，ORDER BY 只能排序、绝不能替代 WHERE 过滤；宁可放宽，不可遗漏。
- **偏好优先级**：对话历史中“用户偏好：...”前缀的内容是历史画像，仅当本次问题未明确提及对应维度时才作为默认值；用户本次问题明确表达的条件优先级最高，必须强制执行（如用户说“要两室”，就不能按历史偏好“合租”来筛）。
- 根据查询主体选择合适的表：
  * 查房源（价格/区域/地铁/户型）→ house_listing 表
  * 查景点/美食/住宿等POI → poi_data 表
  * 查地铁站/线路 → metro_station 表
- 综合查询可对同一结果附加多个条件（如地铁线路 + 价格）。
- 字段说明（**重要：必须严格按真实数据取值生成查询条件，否则查不到数据**）：
  * house_listing: district(区域，**取值没有"区"字**，如'金水'/'中原'/'二七'/'管城'，查询用 district LIKE '%金水%')；rent(月租金)；layout(户型)；metro_line(地铁线路含站点，用 LIKE '%1号线%')；walk_minutes(**距地铁距离，单位米**，范围约150~1200，"离地铁近"用 <= 800)；area(面积)；status(**只有'整租'/'合租'，用户提合租→status='合租'，其余默认 status='整租'**)；detail_url(详情页链接，SELECT时必须带上)
  * poi_data: type(旅游景点/公园广场/餐饮服务/住宿服务/医疗保健), adname(区县，**带区/市/县后缀**，如'金水区'/'管城回族区'/'新郑市'，查询用 adname LIKE '%金水%')，nearest_metro(最近地铁站), nearest_metro_line(最近地铁线路), distance_to_metro(距地铁米)
  * metro_station: name(地铁站名，**实际带'(地铁站)'后缀**，查询用 name LIKE '%郑州东站%')，line_name(线路)，address(换乘线路信息)
- **数量约束**：如果用户明确要求数量（如“推荐两套/3个/几间”），LIMIT 必须等于该数字；未明确提及时默认 LIMIT 5。
- 如果信息不齐，输出json追问；无关问题则模仿最后1个示例。

示例：
- 对话: user: 1号线附近2000以下的房源有哪些？
输出: SELECT community, district, layout, area, rent, metro_line, walk_minutes, detail_url FROM house_listing WHERE rent < 2000 AND metro_line LIKE '%1号线%' AND status = '整租' ORDER BY rent LIMIT 5
- 对话: user: 金水区离地铁近的景点有哪些？
输出: SELECT name, type, adname, nearest_metro, nearest_metro_line, distance_to_metro FROM poi_data WHERE adname LIKE '%金水%' AND type = '旅游景点' AND distance_to_metro IS NOT NULL AND distance_to_metro <= 1000 ORDER BY distance_to_metro LIMIT 5
- 对话: user: 推荐几个中原区交通方便、租金适中的房子
输出: SELECT community, district, layout, area, rent, metro_line, walk_minutes, detail_url FROM house_listing WHERE district LIKE '%中原%' AND metro_line IS NOT NULL AND walk_minutes IS NOT NULL AND walk_minutes <= 800 AND status = '整租' ORDER BY rent LIMIT 5
- 对话: user: 你好
输出: {{"status": "input_required", "message": "请提供综合推荐需求，例如'1号线附近2000以下的房源有哪些'、'金水区离地铁近的景点有哪些'。"}}

表结构：{table_schema_string}
对话历史: {conversation}
当前日期: {current_date} (Asia/Shanghai)
    """
)


# 修正/放宽 SQL 的提示词（P1-3 执行报错自动纠错 + P1-4 空结果自动放宽条件）
fix_sql_prompt = ChatPromptTemplate.from_template(
    """
系统提示：你是郑州综合推荐SQL修正器。上一轮生成的SQL执行遇到问题，请根据执行反馈修正SQL，只输出修正后的纯SQL，不要输出任何解释。
- 如果是"执行报错"：修正 SQL 的语法、字段名或值错误，保持用户查询意图不变。
- 如果是"查询结果为空"：放宽筛选条件——去掉过严的限制（如价格上限、区域限定、户型、步行距离阈值），或用更宽松的 LIKE 匹配（如去掉"区"字、缩短关键词），扩大范围。
- 保留 SELECT 字段列表，保留 LIMIT，按合理字段排序。
- 如果实在无法修正或放宽，返回上一轮SQL。

{table_schema_string}
对话历史（用户原始问题）: {conversation}
上一轮SQL: {last_sql}
执行反馈: {feedback}
当前日期: {current_date} (Asia/Shanghai)
    """
)


# 定义查询函数
async def get_recommend(sql):
    """调用 MCP 查询，带 15s 超时；区分连接错误(connection_error)与SQL错误(error)。

    - connection_error：MCP 服务未启动/超时，属基础设施故障，上层不应让 LLM 误以为是 SQL 写错
    - error：SQL 执行层面的错误，上层可交给 LLM 修正重试
    """
    async def _call():
        # 启动 MCP server，通过streamable建立连接
        async with streamablehttp_client("http://127.0.0.1:8007/mcp") as (read, write, _):
            # 使用读写通道创建 MCP 会话
            async with ClientSession(read, write) as session:
                await session.initialize()
                # 工具调用
                result = await session.call_tool("query_recommend", {"sql": sql})
                result_data = json.loads(result) if isinstance(result, str) else result
                return result_data.content[0].text

    try:
        return await asyncio.wait_for(_call(), timeout=25)
    except asyncio.TimeoutError:
        logger.error("综合推荐 MCP 调用超时（15s）")
        return {"status": "connection_error", "message": "综合推荐 服务响应超时，请稍后重试。"}
    except Exception as e:
        err_msg = format_exception(e)
        logger.error(f"连接或会话初始化时发生错误: {err_msg}")
        return {"status": "connection_error", "message": "综合推荐 服务连接失败，请确认对应服务已启动。"}

# 将综合推荐结果格式化为美观的编号列表文本（markdown 风格，前端可渲染；所有字段 None 安全）
def format_recommend_rows(data):
    lines = []
    for i, d in enumerate(data, 1):
        if 'rent' in d:  # 房源结果
            layout = d.get('layout') or ''
            area = d.get('area')
            area_txt = f"{area}㎡" if area is not None else ''
            rent = d.get('rent')
            rent_txt = f"{rent}元/月" if rent is not None else ''
            detail = " · ".join(x for x in (layout, area_txt) if x) or '信息待补充'
            metro = d.get('metro_line') or '暂无地铁信息'
            walk = d.get('walk_minutes')
            metro_txt = f"{metro}（距地铁约{walk}米）" if walk else metro
            url = d.get('detail_url') or ''
            link = f"[点击查看详情]({url})" if url else "无详情链接"
            lines.append(
                f"{i}. **{d.get('community') or '未知小区'}**（{d.get('district') or ''}）｜ {detail} ｜ 租金 **{rent_txt}**\n"
                f"   - 地铁：{metro_txt}\n"
                f"   - 详情：{link}"
            )
        elif 'type' in d:  # POI结果
            metro = d.get('nearest_metro') or '暂无'
            line = d.get('nearest_metro_line') or ''
            dist = d.get('distance_to_metro')
            metro_txt = f"{metro}（{line}，约{dist}米）" if dist else metro
            lines.append(
                f"{i}. **{d.get('name') or '未知地点'}**（{d.get('type') or '未知类型'}）｜ {d.get('adname') or ''}\n"
                f"   - 最近地铁：{metro_txt}"
            )
        elif 'line_name' in d:  # 地铁站结果
            trans = d.get('address') or ''
            trans_txt = f" ｜ 可换乘：{trans}" if trans else ""
            lines.append(f"{i}. **{d.get('name') or ''}**：{d.get('line_name') or '未知线路'}{trans_txt}")
        else:
            lines.append(f"{i}. {d}")
    return "\n\n".join(lines)


# Agent卡片定义
agent_card = AgentCard(
    name="RecommendQueryAssistant",
    description="基于LangChain提供郑州综合推荐服务的助手（跨房源/周边/地铁组合推荐）",
    url="http://localhost:5009",
    version="1.0.0",
    capabilities={"streaming": False, "memory": True},  # 服务端为同步处理，前端分块推送，不声明未实现的流式能力
    skills=[  # 定义技能列表
        AgentSkill(
            name="execute recommend query",
            description="执行综合推荐查询，返回房源/景点/地铁组合推荐结果，支持自然语言输入",
            examples=["1号线附近2000以下的房源有哪些？", "金水区离地铁近的景点有哪些？"]
        )
    ]
)

# 综合推荐查询服务器类
class RecommendQueryServer(Text2SqlAgentServer):
    def __init__(self):
        super().__init__(agent_card=agent_card)
        self.llm = llm
        self.sql_prompt = sql_prompt
        self.fix_sql_prompt = fix_sql_prompt
        self.schema = table_schema_string
        self.getter = get_recommend
        self.formatter = format_recommend_rows
        self.input_required_msg = "查询无效，请提供综合推荐条件。"

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

    async def _call_sub_agent(self, intent_name: str, url: str, sub_query: str, timeout: float = 30.0):
        """调用单个子Agent，返回 (域, 文本结果, 状态, 耗时ms)；失败返回 None"""
        import time as _t
        _start = _t.time()
        try:
            agent = self.network.get_agent(intent_name)
            msg = Message(content=TextContent(text=sub_query), role=MessageRole.USER)
            task = Task(id="task-" + str(uuid.uuid4()), message=msg.to_dict())
            raw = await asyncio.wait_for(agent.send_task_async(task), timeout=timeout)
            # 提取文本结果
            text_result = raw if isinstance(raw, str) else str(raw)
            # A2A 返回可能是 dict/object，尝试取 artifacts 文本
            if isinstance(raw, dict):
                artifacts = raw.get("artifacts") or []
                parts = []
                for art in artifacts:
                    for part in art.get("parts", []) if isinstance(art, dict) else []:
                        if part.get("type") == "text":
                            parts.append(part.get("text", ""))
                text_result = "\n".join(parts) if parts else text_result
            _elapsed = round((_t.time() - _start) * 1000, 1)
            return {"domain": intent_name, "text": text_result.strip(), "status": "success", "elapsed_ms": _elapsed}
        except asyncio.TimeoutError:
            logger.warning(f"子Agent {intent_name} 调用超时")
            return {"domain": intent_name, "text": "", "status": "timeout", "elapsed_ms": round((_t.time() - _start) * 1000, 1)}
        except Exception as e:
            logger.warning(f"子Agent {intent_name} 调用失败: {str(e)}")
            return {"domain": intent_name, "text": "", "status": "error", "elapsed_ms": round((_t.time() - _start) * 1000, 1)}

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
            # ---- 编排可观测性：把每个子调用的域/状态/耗时写入 trace ----
            import time as _t2
            orchestration_trace = {
                "type": "orchestration_trace",
                "timestamp": _t2.strftime("%Y-%m-%d %H:%M:%S"),
                "sub_agents": [
                    {
                        "domain": r.get("domain"),
                        "title": SUB_AGENTS.get(r.get("domain"), (None, None, r.get("domain")))[2],
                        "status": r.get("status", "success"),
                        "elapsed_ms": r.get("elapsed_ms"),
                        "query": sub_queries.get(r.get("domain"), conversation),
                    } for r in results if r
                ],
            }
            if not valid:
                logger.warning("[编排] 子Agent全部不可用，降级回退 text2sql")
                return super().handle_task(task)

            # 汇总
            sections = []
            for r in valid:
                title = SUB_AGENTS.get(r["domain"], (None, None, r["domain"]))[2]
                sections.append(f"{title}：\n{r['text']}")
            combined = "\n\n".join(sections)
            task.artifacts = [{"parts": [{"type": "text", "text": combined}]}]
            # 编排明细随 artifacts 返回，web_server 可解析为子节点展示
            task.artifacts.append({"parts": [{"type": "json", "data": orchestration_trace}]})
            task.status = TaskStatus(state=TaskState.COMPLETED)
            return task
        except Exception as e:
            logger.error(f"[编排] 汇总失败，降级回退 text2sql: {str(e)}")
            return super().handle_task(task)



if __name__ == "__main__":
    # 创建并运行服务器
    # 实例化综合推荐查询服务器
    recommend_server = OrchestratedRecommendQueryServer()
    # 打印服务器信息
    logger.info("=== 推荐服务器信息 ===")
    logger.info(f"名称: {recommend_server.agent_card.name}")
    logger.info(f"描述: {recommend_server.agent_card.description}")
    logger.info("技能:")
    for skill in recommend_server.agent_card.skills:
        logger.info(f"- {skill.name}: {skill.description}")
    # 运行服务器
    run_server(recommend_server, host="127.0.0.1", port=5009)
