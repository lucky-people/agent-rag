#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: metro_server.py
作者: 智租顾问 (Zhizu Advisor)
描述: 交通出行agent服务器，基于 rental 库的 metro_station 表与 poi_data 表
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
llm = ChatOpenAI(
    model=conf.model_name,
    base_url=conf.base_url,
    api_key=conf.api_key,
    temperature=0.1
)

# 数据表 schema
table_schema_string = """  # 定义地铁站表与POI表的SQL schema字符串，用于Prompt上下文
CREATE TABLE metro_station (
    id INT AUTO_INCREMENT PRIMARY KEY,
    poi_id VARCHAR(50) NOT NULL COMMENT '高德POI ID',
    name VARCHAR(100) NOT NULL COMMENT '地铁站名（如 郑州东站）',
    line_name VARCHAR(50) COMMENT '所属线路（如 1号线）',
    address VARCHAR(255) COMMENT '地址',
    location VARCHAR(50) COMMENT '经纬度(经度,纬度)',
    lng DECIMAL(10,6) COMMENT '经度',
    lat DECIMAL(10,6) COMMENT '纬度',
    update_time DATETIME,
    UNIQUE KEY unique_poi (poi_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='地铁站表';

CREATE TABLE poi_data (
    id INT AUTO_INCREMENT PRIMARY KEY,
    poi_id VARCHAR(50) NOT NULL COMMENT '高德POI ID',
    name VARCHAR(255) NOT NULL COMMENT '名称',
    type VARCHAR(100) COMMENT '大类',
    address VARCHAR(255) COMMENT '地址',
    adname VARCHAR(50) COMMENT '区县',
    nearest_metro VARCHAR(100) COMMENT '最近地铁站',
    nearest_metro_line VARCHAR(50) COMMENT '最近地铁线路',
    distance_to_metro INT COMMENT '到最近地铁站距离(米)',
    update_time DATETIME,
    UNIQUE KEY unique_poi (poi_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='POI数据表';
"""

# 生成SQL的提示词
sql_prompt = ChatPromptTemplate.from_template(
    """
系统提示：你是一个专业的郑州地铁出行SQL生成器，需要从对话历史（含用户的问题）中提取关键信息，然后基于metro_station表和poi_data表生成SELECT语句。
- 查询"某地铁站坐几号线"：用 metro_station.name 匹配。**注意：name 实际带"(地铁站)"后缀**（如 '郑州东站(地铁站)'、'二七广场(地铁站)'），所以用 name LIKE '%郑州东站%' 匹配，不要用等号。
- metro_station.address 字段存的是换乘线路信息（如 '1号线;5号线;8号线'），SELECT 时带上即可直接展示换乘。
- 如果用户给出地标/POI问最近的地铁站（如"离二七广场最近的地铁站"），在 poi_data 表中查询该地标（name LIKE '%二七广场%'），返回 nearest_metro、nearest_metro_line、distance_to_metro。
- 如果用户只问"离我最近的地铁站在哪"但未提供任何位置或地标，无法定位，输出追问json。
- 如果用户问与地铁出行无关的问题，则模仿最后1个示例回复即可。

示例：
- 对话: user: 郑州东站坐几号线？
输出: SELECT name, line_name, address FROM metro_station WHERE name LIKE '%郑州东站%'
- 对话: user: 离二七广场最近的地铁站是哪个
输出: SELECT name, nearest_metro, nearest_metro_line, distance_to_metro FROM poi_data WHERE name LIKE '%二七广场%' LIMIT 5
- 对话: user: 有哪些地铁站
输出: SELECT name, line_name, address FROM metro_station ORDER BY line_name, name LIMIT 10
- 对话: user: 1号线有哪些站点
输出: SELECT name, line_name, address FROM metro_station WHERE line_name = '1号线' ORDER BY name LIMIT 20
- 对话: user: 离我最近的地铁站在哪
输出: {{"status": "input_required", "message": "请提供您的位置或附近地标，例如'离二七广场最近的地铁站'。"}}
- 对话: user: 你好
输出: {{"status": "input_required", "message": "请提供地铁出行查询，例如'郑州东站坐几号线'或'离XX最近的地铁站'。"}}

表结构：{table_schema_string}
对话历史: {conversation}
当前日期: {current_date} (Asia/Shanghai)
    """
)


# 修正/放宽 SQL 的提示词（P1-3 执行报错自动纠错 + P1-4 空结果自动放宽条件）
fix_sql_prompt = ChatPromptTemplate.from_template(
    """
系统提示：你是郑州地铁出行SQL修正器。上一轮生成的SQL执行遇到问题，请根据执行反馈修正SQL，只输出修正后的纯SQL，不要输出任何解释。
- 如果是"执行报错"：修正 SQL 的语法、字段名或值错误，保持用户查询意图不变。
- 如果是"查询结果为空"：放宽筛选条件——去掉过严的限制（如站名关键词过长、线路限定），或用更宽松的 LIKE 匹配（如去掉"(地铁站)"后缀、缩短关键词），扩大范围；若用户给的是房源名/小区名而非站名，可尝试用其区域（如"金水"）匹配附近地铁。
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
async def get_metro(sql):
    """调用 MCP 查询，带 15s 超时；区分连接错误(connection_error)与SQL错误(error)。

    - connection_error：MCP 服务未启动/超时，属基础设施故障，上层不应让 LLM 误以为是 SQL 写错
    - error：SQL 执行层面的错误，上层可交给 LLM 修正重试
    """
    async def _call():
        # 启动 MCP server，通过streamable建立连接
        async with streamablehttp_client("http://127.0.0.1:8006/mcp") as (read, write, _):
            # 使用读写通道创建 MCP 会话
            async with ClientSession(read, write) as session:
                await session.initialize()
                # 工具调用
                result = await session.call_tool("query_metro", {"sql": sql})
                result_data = json.loads(result) if isinstance(result, str) else result
                return result_data.content[0].text

    try:
        return await asyncio.wait_for(_call(), timeout=15)
    except asyncio.TimeoutError:
        logger.error("地铁 MCP 调用超时（15s）")
        return {"status": "connection_error", "message": "地铁 服务响应超时，请稍后重试。"}
    except Exception as e:
        err_msg = format_exception(e)
        logger.error(f"连接或会话初始化时发生错误: {err_msg}")
        return {"status": "connection_error", "message": "地铁 服务连接失败，请确认对应服务已启动。"}

# 将地铁结果格式化为美观的编号列表文本（markdown 风格，前端可渲染；所有字段 None 安全）
def format_metro_rows(data):
    lines = []
    for i, d in enumerate(data, 1):
        if 'line_name' in d:  # metro_station 表结果
            trans = d.get('address') or ''
            trans_txt = f" ｜ 可换乘：{trans}" if trans else ""
            lines.append(f"{i}. **{d.get('name') or ''}**：{d.get('line_name') or '未知线路'}{trans_txt}")
        else:  # poi_data 表结果（地标最近地铁站）
            dist = d.get('distance_to_metro')
            dist_txt = f"约{dist}米" if dist is not None else '距离未知'
            lines.append(
                f"{i}. **{d.get('name') or '未知地点'}** 最近地铁站：{d.get('nearest_metro') or '未知'}"
                f"（{d.get('nearest_metro_line') or ''}，{dist_txt}）"
            )
    return "\n\n".join(lines)


# Agent卡片定义
agent_card = AgentCard(
    name="MetroQueryAssistant",
    description="基于LangChain提供郑州地铁出行查询服务的助手",
    url="http://localhost:5008",
    version="1.0.0",
    capabilities={"streaming": False, "memory": True},  # 服务端为同步处理，前端分块推送，不声明未实现的流式能力
    skills=[  # 定义技能列表
        AgentSkill(
            name="execute metro query",
            description="执行地铁出行查询，返回地铁站/线路数据库结果，支持自然语言输入",
            examples=["郑州东站坐几号线？", "离二七广场最近的地铁站是哪个", "1号线有哪些站点"]
        )
    ]
)

# 地铁出行查询服务器类
class MetroQueryServer(Text2SqlAgentServer):
    def __init__(self):
        super().__init__(agent_card=agent_card)
        self.llm = llm
        self.sql_prompt = sql_prompt
        self.fix_sql_prompt = fix_sql_prompt
        self.schema = table_schema_string
        self.getter = get_metro
        self.formatter = format_metro_rows
        self.input_required_msg = "查询无效，请提供地铁站名或附近地标。"

if __name__ == "__main__":
    # 创建并运行服务器
    # 实例化地铁出行查询服务器
    metro_server = MetroQueryServer()
    # 打印服务器信息
    logger.info("=== 地铁服务器信息 ===")
    logger.info(f"名称: {metro_server.agent_card.name}")
    logger.info(f"描述: {metro_server.agent_card.description}")
    logger.info("技能:")
    for skill in metro_server.agent_card.skills:
        logger.info(f"- {skill.name}: {skill.description}")
    # 运行服务器
    run_server(metro_server, host="127.0.0.1", port=5008)
