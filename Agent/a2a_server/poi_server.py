#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: poi_server.py
作者: 智租顾问 (Zhizu Advisor)
描述: 周边探索agent服务器，基于 rental 库的 poi_data 表
"""
import os
import sys
import json
import asyncio
import re

# 路径配置：把项目根目录加入 sys.path，支持 from Agent.xxx import 绝对路径导入
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from Agent.a2a_server.base_text2sql_server import Text2SqlAgentServer
from python_a2a import A2AServer, run_server, AgentCard, AgentSkill, TaskStatus, TaskState
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from datetime import datetime
import pytz

from Agent.config import Config
from Agent.create_logger import logger
from Agent.utils.format import format_exception, robust_json_loads, extract_sql

conf = Config()

# 初始化LLM
llm = ChatOpenAI(
    model=conf.model_name,
    base_url=conf.base_url,
    api_key=conf.api_key,
    temperature=0.1
)

# 数据表 schema
table_schema_string = """  # 定义POI表的SQL schema字符串，用于Prompt上下文
CREATE TABLE poi_data (
    id INT AUTO_INCREMENT PRIMARY KEY,
    poi_id VARCHAR(50) NOT NULL COMMENT '高德POI ID',
    name VARCHAR(255) NOT NULL COMMENT '名称',
    type VARCHAR(100) COMMENT '大类（旅游景点/公园广场/医疗保健/住宿服务/餐饮服务）',
    typecode VARCHAR(50) COMMENT 'POI类型编码',
    address VARCHAR(255) COMMENT '地址',
    location VARCHAR(50) COMMENT '经纬度(经度,纬度)',
    pname VARCHAR(50) COMMENT '省份',
    cityname VARCHAR(50) COMMENT '城市',
    adname VARCHAR(50) COMMENT '区县（如 金水区/二七区/中原区）',
    nearest_metro VARCHAR(100) COMMENT '最近地铁站',
    nearest_metro_line VARCHAR(50) COMMENT '最近地铁线路（如 1号线）',
    distance_to_metro INT COMMENT '到最近地铁站距离(米)',
    intro TEXT COMMENT '景点简介（旅游景点类才有，查询景点时请一并返回）',
    update_time DATETIME,
    UNIQUE KEY unique_poi (poi_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='POI数据表';
"""

# 生成SQL的提示词
sql_prompt = ChatPromptTemplate.from_template(
    """
系统提示：你是一个专业的郑州周边探索SQL生成器，需要从对话历史（含用户的问题）中提取关键信息，然后基于poi_data表生成SELECT语句。
- poi_data.type 为POI大类，取值包括：旅游景点、公园广场、医疗保健、住宿服务、餐饮服务。"好吃的"对应'餐饮服务'，"景点"对应'旅游景点'，"公园"对应'公园广场'，"住宿"对应'住宿服务'。
- poi_data.adname 为区县，**取值带区/市/县后缀**（如 '金水区'、'管城回族区'、'二七区'、'中原区'、'新郑市'、'中牟县'）。查询时用 adname LIKE '%金水%' 匹配，"管城区"用 adname LIKE '%管城%'（可匹配'管城回族区'），不要直接用等号。
- poi_data.nearest_metro 为最近地铁站，nearest_metro_line 为最近地铁线路，distance_to_metro 为到地铁站距离（**单位：米**）。
- "附近"查询：如果用户提到具体地点/地标（如"二七广场附近"），用 name LIKE '%二七广场%' OR address LIKE '%二七广场%' OR nearest_metro LIKE '%二七广场%' 过滤（nearest_metro 是最近地铁站名，常能兜底命中地标周边）。
- "1号线沿线"用 nearest_metro_line LIKE '%1号线%'。
- "离地铁近"用 distance_to_metro IS NOT NULL AND distance_to_metro <= 1000。
- 如果信息不齐，输出json追问；无关问题则模仿最后1个示例。

示例：
- 对话: user: 二七广场附近有什么好吃的？
输出: SELECT name, type, adname, address, nearest_metro, nearest_metro_line, distance_to_metro, intro FROM poi_data WHERE type = '餐饮服务' AND (name LIKE '%二七广场%' OR address LIKE '%二七广场%' OR nearest_metro LIKE '%二七广场%') LIMIT 5
- 对话: user: 1号线沿线有哪些景点？
输出: SELECT name, type, adname, address, nearest_metro, nearest_metro_line, distance_to_metro, intro FROM poi_data WHERE type = '旅游景点' AND nearest_metro_line LIKE '%1号线%' LIMIT 5
- 对话: user: 金水区有哪些公园
输出: SELECT name, type, adname, address, nearest_metro, nearest_metro_line, distance_to_metro, intro FROM poi_data WHERE adname LIKE '%金水%' AND type = '公园广场' LIMIT 5
- 对话: user: 离地铁近的住宿有哪些
输出: SELECT name, type, adname, address, nearest_metro, nearest_metro_line, distance_to_metro, intro FROM poi_data WHERE type = '住宿服务' AND distance_to_metro IS NOT NULL AND distance_to_metro <= 1000 ORDER BY distance_to_metro LIMIT 5
- 对话: user: 管城区有什么好吃的
输出: SELECT name, type, adname, address, nearest_metro, nearest_metro_line, distance_to_metro, intro FROM poi_data WHERE adname LIKE '%管城%' AND type = '餐饮服务' LIMIT 5
- 对话: user: 你好
输出: {{"status": "input_required", "message": "请提供周边探索需求，例如'二七广场附近有什么好吃的'、'1号线沿线有哪些景点'。"}}

poi_data表结构：{table_schema_string}
对话历史: {conversation}
当前日期: {current_date} (Asia/Shanghai)
    """
)


# 修正/放宽 SQL 的提示词（P1-3 执行报错自动纠错 + P1-4 空结果自动放宽条件）
fix_sql_prompt = ChatPromptTemplate.from_template(
    """
系统提示：你是郑州周边POI查询SQL修正器。上一轮生成的SQL执行遇到问题，请根据执行反馈修正SQL，只输出修正后的纯SQL，不要输出任何解释。
- 如果是"执行报错"：修正 SQL 的语法、字段名或值错误，保持用户查询意图不变。
- 如果是"查询结果为空"：放宽筛选条件——去掉过严的限制（如区域限定、类型限定、关键词过长），或用更宽松的 LIKE 匹配，扩大范围；若用户只问一个条件，可去掉该条件查询全部。
- 保留 SELECT 字段列表，保留 LIMIT。
- 如果实在无法修正或放宽，返回上一轮SQL。

{table_schema_string}
对话历史（用户原始问题）: {conversation}
上一轮SQL: {last_sql}
执行反馈: {feedback}
当前日期: {current_date} (Asia/Shanghai)
    """
)


# 定义查询函数
async def get_poi(sql):
    """调用 MCP 查询，带 15s 超时；区分连接错误(connection_error)与SQL错误(error)。

    - connection_error：MCP 服务未启动/超时，属基础设施故障，上层不应让 LLM 误以为是 SQL 写错
    - error：SQL 执行层面的错误，上层可交给 LLM 修正重试
    """
    async def _call():
        # 启动 MCP server，通过streamable建立连接
        async with streamablehttp_client("http://127.0.0.1:8005/mcp") as (read, write, _):
            # 使用读写通道创建 MCP 会话
            async with ClientSession(read, write) as session:
                await session.initialize()
                # 工具调用
                result = await session.call_tool("query_poi", {"sql": sql})
                result_data = json.loads(result) if isinstance(result, str) else result
                return result_data.content[0].text

    try:
        return await asyncio.wait_for(_call(), timeout=15)
    except asyncio.TimeoutError:
        logger.error(f"POI MCP 调用超时（15s）")
        return {"status": "connection_error", "message": "POI 服务响应超时，请稍后重试。"}
    except Exception as e:
        err_msg = format_exception(e)
        logger.error(f"连接或会话初始化时发生错误: {err_msg}")
        return {"status": "connection_error", "message": "POI 服务连接失败，请确认对应服务已启动。"}

# 将 POI 结果格式化为美观的编号列表文本（markdown 风格，前端可渲染；所有字段 None 安全）
def format_poi_rows(data):
    lines = []
    for i, d in enumerate(data, 1):
        metro = d.get('nearest_metro') or '暂无'
        line = d.get('nearest_metro_line') or ''
        dist = d.get('distance_to_metro')
        metro_txt = f"{metro}（{line}，约{dist}米）" if dist else metro
        intro = d.get('intro')
        intro_txt = f"\n   - 简介：{intro}" if intro else ""
        lines.append(
            f"{i}. **{d.get('name') or '未知地点'}**（{d.get('type') or '未知类型'}）｜ {d.get('adname') or ''}\n"
            f"   - 地址：{d.get('address') or '暂无'}\n"
            f"   - 最近地铁：{metro_txt}{intro_txt}"
        )
    return "\n\n".join(lines)


# Agent卡片定义
agent_card = AgentCard(
    name="PoiQueryAssistant",
    description="基于LangChain提供郑州周边探索（景点/美食/公园等）服务的助手",
    url="http://localhost:5007",
    version="1.0.0",
    capabilities={"streaming": False, "memory": True},  # 服务端为同步处理，前端分块推送，不声明未实现的流式能力
    skills=[  # 定义技能列表
        AgentSkill(
            name="execute poi query",
            description="执行周边POI查询，返回地点数据库结果，支持自然语言输入",
            examples=["二七广场附近有什么好吃的？", "1号线沿线有哪些景点？", "金水区有哪些公园"]
        )
    ]
)

# 周边探索查询服务器类
class PoiQueryServer(Text2SqlAgentServer):
    def __init__(self):
        super().__init__(agent_card=agent_card)
        self.llm = llm
        self.sql_prompt = sql_prompt
        self.fix_sql_prompt = fix_sql_prompt
        self.schema = table_schema_string
        self.getter = get_poi
        self.formatter = format_poi_rows
        self.input_required_msg = "查询无效，请提供周边探索条件（如地点、类型、线路）。"

if __name__ == "__main__":
    # 创建并运行服务器
    # 实例化周边探索查询服务器
    poi_server = PoiQueryServer()
    # 打印服务器信息
    logger.info("=== POI服务器信息 ===")
    logger.info(f"名称: {poi_server.agent_card.name}")
    logger.info(f"描述: {poi_server.agent_card.description}")
    logger.info("技能:")
    for skill in poi_server.agent_card.skills:
        logger.info(f"- {skill.name}: {skill.description}")
    # 运行服务器
    run_server(poi_server, host="127.0.0.1", port=5007)
