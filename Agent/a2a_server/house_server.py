#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: house_server.py
作者: 智租顾问 (Zhizu Advisor)
描述: 房源查询agent服务器，基于 rental 库的 house_listing 表
"""
import os
import sys
import json
import asyncio

# 路径配置：把项目根目录加入 sys.path，支持 from Agent.xxx import 绝对路径导入
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from Agent.a2a_server.base_text2sql_server import Text2SqlAgentServer
from python_a2a import run_server, AgentCard, AgentSkill
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

from Agent.config import Config
from Agent.create_logger import logger
from Agent.utils.format import format_exception

conf = Config()

# 初始化LLM
# 说明: 缺少 API Key 时不在 import 阶段直接抛 OpenAIError, 而是降级为 None 并告警——
# 否则全新 clone(未配置 config_local/keys.py)连单元测试都跑不起来; 调用侧已有 try/except 兜底。
try:
    llm = ChatOpenAI(
        model=conf.model_name,
        base_url=conf.base_url,
        api_key=conf.api_key,
        temperature=0.1,
        request_timeout=10,
        max_retries=1
    )
except Exception as e:
    logger.warning(f"LLM 初始化失败({type(e).__name__}: {e}); 相关链路降级, 请检查 DASHSCOPE_API_KEY / config_local/keys.py")
    llm = None

# 数据表 schema
table_schema_string = """  # 定义房源表的SQL schema字符串，用于Prompt上下文
CREATE TABLE house_listing (
    id INT AUTO_INCREMENT PRIMARY KEY,
    house_id VARCHAR(50) NOT NULL COMMENT '房源ID',
    city VARCHAR(20) DEFAULT '郑州',
    district VARCHAR(50) COMMENT '区域（如 金水区/中原区/二七区/管城区/郑东新区）',
    community TEXT COMMENT '小区名称',
    layout TEXT COMMENT '户型（如 3室2厅2卫）',
    area DECIMAL(10,2) COMMENT '面积m²',
    rent INT COMMENT '月租金（元）',
    orientation VARCHAR(20) COMMENT '朝向',
    floor VARCHAR(50) COMMENT '楼层',
    metro_line VARCHAR(50) COMMENT '地铁线路（如 1号线）',
    walk_minutes INT COMMENT '距地铁步行分钟',
    status VARCHAR(20) DEFAULT '在租' COMMENT '在租/已租/下架',
    detail_url VARCHAR(255) COMMENT '详情页链接',
    update_time DATETIME,
    UNIQUE KEY unique_house (house_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='房源表';
"""

# 生成SQL的提示词
sql_prompt = ChatPromptTemplate.from_template(
    """
系统提示：你是一个专业的郑州房源查询SQL生成器，需要从对话历史（含用户的问题）中提取关键信息，然后基于house_listing表生成SELECT语句。
- **约束完整性（最高优先级）**：用户明确提到的每个筛选条件（区域、价格、地铁、户型、类型、线路等）必须逐一转成 WHERE 条件，ORDER BY 只能排序、绝不能替代 WHERE 过滤；宁可放宽，不可遗漏。
- **偏好优先级**：对话历史中“用户偏好：...”前缀的内容是历史画像，仅当本次问题未明确提及对应维度时才作为默认值；用户本次问题明确表达的条件优先级最高，必须强制执行（如用户说“要两室”，就不能按历史偏好“合租”来筛）。
- 如果用户需要查询房源，则至少需要区域（district）或价格（rent）或地铁（metro_line/walk_minutes）等信息。如果对话历史中缺乏必要的信息，可以向其追问，输出格式为json格式，如示例所示；如果对话历史中信息齐全，则输出纯SQL即可。
- 如果用户问与房源无关的问题，则模仿最后1个示例回复即可。
- 字段说明（**重要：必须严格按真实数据取值生成查询条件，否则查不到数据**）：
  * district：区域。**表中取值没有"区"字**，例如 '金水'、'二七'、'中原'、'管城'、'惠济'、'高新'、'经开'、'郑东新区'、'航空港区' 等。用户说"金水区"时用 district LIKE '%金水%' 匹配（同理"中原区"→LIKE '%中原%'、"二七区"→LIKE '%二七%'、"管城区"→LIKE '%管城%'）。
  * rent：月租金（元），community：小区名称，area：面积（㎡）
  * layout：户型（如 3室2厅2卫）
  * status：租住方式，**只有 '整租' 和 '合租' 两种取值，不存在'在租'**。用户提到"合租"→status='合租'；**其余情况（含未提及时）默认 status='整租'**。
  * metro_line：地铁线路（含站点名，如 '1号线五一公园站'），查询线路用 metro_line LIKE '%1号线%'。
  * walk_minutes：**距最近地铁站的步行距离（单位：米），范围约150~1200米**。"离地铁站近"用 walk_minutes IS NOT NULL AND walk_minutes <= 800。
  * orientation：朝向，floor：楼层
  * detail_url：详情页链接，SELECT 时**必须带上**，推荐给用户时用于点击查看详情
- **数量约束**：如果用户明确要求数量（如“推荐两套/3个/几间”），LIMIT 必须等于该数字；未明确提及时默认 LIMIT 5。
- 查询结果请按 rent 升序或 walk_minutes 升序等合理排序。

示例：
- 对话: user: 金水区有没有2000元以下的整租房？
输出: SELECT community, district, layout, area, rent, orientation, floor, metro_line, walk_minutes, detail_url FROM house_listing WHERE district LIKE '%金水%' AND rent < 2000 AND status = '整租' ORDER BY rent LIMIT 5
- 对话: user: 离地铁站近的房源有哪些
输出: SELECT community, district, layout, area, rent, metro_line, walk_minutes, detail_url FROM house_listing WHERE metro_line IS NOT NULL AND walk_minutes IS NOT NULL AND walk_minutes <= 800 AND status = '整租' ORDER BY walk_minutes LIMIT 5
- 对话: user: 1号线附近的房源
输出: SELECT community, district, layout, area, rent, metro_line, walk_minutes, detail_url FROM house_listing WHERE metro_line LIKE '%1号线%' AND status = '整租' ORDER BY rent LIMIT 5
- 对话: user: 推荐一些三室的房子
输出: SELECT community, district, layout, area, rent, metro_line, walk_minutes, detail_url FROM house_listing WHERE layout LIKE '%3室%' AND status = '整租' ORDER BY rent LIMIT 5
- 对话: user: 二七区的合租房源
输出: SELECT community, district, layout, area, rent, metro_line, walk_minutes, detail_url FROM house_listing WHERE district LIKE '%二七%' AND status = '合租' ORDER BY rent LIMIT 5
- 对话: user: 你好
输出: {{"status": "input_required", "message": "请提供房源查询条件，例如区域、租金范围或地铁线路，如'金水区2000元以下的房子'。"}}

house_listing表结构：{table_schema_string}
对话历史: {conversation}
当前日期: {current_date} (Asia/Shanghai)
    """
)


# 修正/放宽 SQL 的提示词（P1-3 执行报错自动纠错 + P1-4 空结果自动放宽条件）
fix_sql_prompt = ChatPromptTemplate.from_template(
    """
系统提示：你是郑州房源查询SQL修正器。上一轮生成的SQL执行遇到问题，请根据执行反馈修正SQL，只输出修正后的纯SQL，不要输出任何解释。
- 如果是"执行报错"：修正 SQL 的语法、字段名或值错误，保持用户查询意图不变。
- 如果是"查询结果为空"：放宽筛选条件——去掉过严的限制（如价格上限、区域限定、户型、步行距离阈值），或用更宽松的 LIKE 匹配（如去掉"区"字、缩短关键词），扩大查询范围；若用户只问一个条件（如只要金水区），可去掉该条件查询全部或降低排序条件。
- 保留 SELECT 字段列表（必须含 detail_url），保留 LIMIT，按 rent 升序等合理字段排序。
- 如果实在无法修正或放宽，返回上一轮SQL。

house_listing表结构：{table_schema_string}
对话历史（用户原始问题）: {conversation}
上一轮SQL: {last_sql}
执行反馈: {feedback}
当前日期: {current_date} (Asia/Shanghai)
    """
)


# 定义查询函数
async def get_house(sql):
    """调用 MCP 查询，带 15s 超时；区分连接错误(connection_error)与SQL错误(error)。

    - connection_error：MCP 服务未启动/超时，属基础设施故障，上层不应让 LLM 误以为是 SQL 写错
    - error：SQL 执行层面的错误，上层可交给 LLM 修正重试
    """
    async def _call():
        # 启动 MCP server，通过streamable建立连接
        async with streamablehttp_client("http://127.0.0.1:8004/mcp") as (read, write, _):
            # 使用读写通道创建 MCP 会话
            async with ClientSession(read, write) as session:
                await session.initialize()
                # 工具调用
                result = await session.call_tool("query_houses", {"sql": sql})
                result_data = json.loads(result) if isinstance(result, str) else result
                return result_data.content[0].text

    try:
        return await asyncio.wait_for(_call(), timeout=25)
    except asyncio.TimeoutError:
        logger.error("房源 MCP 调用超时（15s）")
        return {"status": "connection_error", "message": "房源 服务响应超时，请稍后重试。"}
    except Exception as e:
        err_msg = format_exception(e)
        logger.error(f"连接或会话初始化时发生错误: {err_msg}")
        return {"status": "connection_error", "message": "房源 服务连接失败，请确认对应服务已启动。"}

# 将房源结果格式化为美观的编号列表文本（markdown 风格，前端可渲染；所有字段 None 安全）
def format_house_rows(data):
    lines = []
    for i, d in enumerate(data, 1):
        community = d.get('community') or '未知小区'
        district = d.get('district') or ''
        layout = d.get('layout') or ''
        area = d.get('area')
        area_txt = f"{area}㎡" if area is not None else ''
        rent = d.get('rent')
        rent_txt = f"{rent}元/月" if rent is not None else ''
        detail = " · ".join(x for x in (layout, area_txt) if x) or '信息待补充'
        orientation = d.get('orientation') or '未知'
        floor_txt = d.get('floor') or '未知'
        metro = d.get('metro_line') or '暂无地铁信息'
        walk = d.get('walk_minutes')
        metro_txt = f"{metro}（距地铁约{walk}米）" if walk else metro
        url = d.get('detail_url') or ''
        link = f"[点击查看详情]({url})" if url else "无详情链接"
        lines.append(
            f"{i}. **{community}**（{district}）｜ {detail} ｜ 租金 **{rent_txt}**\n"
            f"   - 朝向：{orientation} ｜ 楼层：{floor_txt}\n"
            f"   - 地铁：{metro_txt}\n"
            f"   - 详情：{link}"
        )
    return "\n\n".join(lines)


# Agent卡片定义
agent_card = AgentCard(
    name="HouseQueryAssistant",
    description="基于LangChain提供郑州房源查询服务的助手",
    url="http://localhost:5006",
    version="1.0.0",
    capabilities={"streaming": False, "memory": True},  # 服务端为同步处理，前端分块推送，不声明未实现的流式能力
    skills=[  # 定义技能列表
        AgentSkill(
            name="execute house query",
            description="执行房源查询，返回房源数据库结果，支持自然语言输入",
            examples=["金水区有没有2000元以下的整租房？", "离地铁站近的房源有哪些", "1号线附近的房源"]
        )
    ]
)

# 房源查询服务器类
class HouseQueryServer(Text2SqlAgentServer):
    def __init__(self):
        super().__init__(agent_card=agent_card)
        self.llm = llm
        self.sql_prompt = sql_prompt
        self.fix_sql_prompt = fix_sql_prompt
        self.schema = table_schema_string
        self.getter = get_house
        self.formatter = format_house_rows
        self.input_required_msg = "查询无效，请提供区域、租金或地铁等房源条件。"

if __name__ == "__main__":
    # 创建并运行服务器
    # 实例化房源查询服务器
    house_server = HouseQueryServer()
    # 打印服务器信息
    logger.info("=== 房源服务器信息 ===")
    logger.info(f"名称: {house_server.agent_card.name}")
    logger.info(f"描述: {house_server.agent_card.description}")
    logger.info("技能:")
    for skill in house_server.agent_card.skills:
        logger.info(f"- {skill.name}: {skill.description}")
    # 运行服务器
    run_server(house_server, host="127.0.0.1", port=5006)
