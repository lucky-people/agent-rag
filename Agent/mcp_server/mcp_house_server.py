#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: mcp_house_server.py
作者: 智租顾问 (Zhizu Advisor)
描述: 房源查询MCP服务器，基于 rental 库的 house_listing 表
"""
import os
import sys
import mysql.connector
import json
from datetime import date, datetime, timedelta
from decimal import Decimal

# 路径配置：把项目根目录加入 sys.path，支持 from Agent.xxx import 绝对路径导入
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from mcp.server.fastmcp import FastMCP

from Agent.config import Config
from Agent.create_logger import logger
from Agent.utils.format import DateEncoder, default_encoder, ensure_limit, validate_readonly_sql

conf = Config()


# 房源服务类
class HouseService:  # 定义房源服务类，封装数据库操作逻辑
    def __init__(self):
        # 连接数据库
        self.conn = mysql.connector.connect(
            host=conf.host,
            user=conf.user,
            password=conf.password,
            database=conf.database
        )

    # 定义执行SQL查询方法，输入SQL字符串，返回JSON字符串
    def execute_query(self, sql: str) -> str:
        try:
            # 只读白名单校验：仅允许 SELECT/WITH，拒绝写操作与危险语句
            ok, safe_sql = validate_readonly_sql(sql)
            if not ok:
                logger.warning(f"SQL白名单校验拒绝: {safe_sql}")
                return json.dumps({"status": "error", "message": safe_sql}, ensure_ascii=False)
            cursor = self.conn.cursor(dictionary=True)
            cursor.execute(safe_sql)
            results = cursor.fetchall()
            cursor.close()
            # 格式化结果
            for result in results:  # 遍历每个结果字典
                for key, value in result.items():
                    if isinstance(value, (date, datetime, timedelta, Decimal)):  # 检查值是否为特殊类型
                        result[key] = default_encoder(value)  # 使用自定义编码器格式化该值
            # 序列化为JSON，如果有结果返回success，否则no_data；使用DateEncoder，非ASCII不转义
            return json.dumps({"status": "success", "data": results} if results else {"status": "no_data",
                                                                                      "message": "未找到房源数据，请确认查询条件。"},
                              cls=DateEncoder, ensure_ascii=False)
        except Exception as e:
            logger.error(f"房源查询错误: {str(e)}")
            # 返回错误JSON响应
            return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


# 创建房源MCP服务器
def create_house_mcp_server():
    # 创建FastMCP实例
    house_mcp = FastMCP(name="HouseTools",
                        instructions="房源查询工具，基于 house_listing 表。",
                        log_level="ERROR",
                        host="127.0.0.1", port=8004)

    # 实例化房源服务对象（若数据库不可用，给出清晰提示，避免端口未监听导致A2A侧连接失败）
    try:
        service = HouseService()
    except Exception as e:
        logger.error(f"[启动失败] 数据库连接出错，请检查MySQL服务与 rental 库: {e}")
        return

    @house_mcp.tool(
        name="query_houses",
        description="查询房源数据，输入 SQL，如 'SELECT * FROM house_listing WHERE district = \"金水区\" AND rent < 2000'"
    )
    def query_houses(sql: str) -> str:
        logger.info(f"执行房源查询: {sql}")
        return service.execute_query(sql)

    # 打印服务器信息
    logger.info("=== 房源MCP服务器信息 ===")
    logger.info(f"名称: {house_mcp.name}")
    logger.info(f"描述: {house_mcp.instructions}")

    # 运行服务器
    try:
        logger.info("房源MCP服务器已启动，请访问 http://127.0.0.1:8004/mcp")
        house_mcp.run(transport="streamable-http")
    except Exception as e:
        logger.error(f"房源MCP服务器启动失败: {e}")


if __name__ == '__main__':
    create_house_mcp_server()
