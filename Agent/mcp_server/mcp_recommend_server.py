#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: mcp_recommend_server.py
作者: 智租顾问 (Zhizu Advisor)
描述: 综合推荐MCP服务器，基于 rental 库的 house_listing、poi_data、metro_station 三张表
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


# 综合推荐服务类
class RecommendService:  # 定义综合推荐服务类，封装数据库操作逻辑
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
                                                                                      "message": "未找到符合条件的推荐，请调整条件。"},
                              cls=DateEncoder, ensure_ascii=False)
        except Exception as e:
            logger.error(f"综合推荐查询错误: {str(e)}")
            # 返回错误JSON响应
            return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


# 创建综合推荐MCP服务器
def create_recommend_mcp_server():
    # 创建FastMCP实例
    recommend_mcp = FastMCP(name="RecommendTools",
                           instructions="综合推荐工具，基于 house_listing、poi_data、metro_station 表，跨领域组合推荐房源/景点/地铁。",
                           log_level="ERROR",
                           host="127.0.0.1", port=8007)

    # 实例化综合推荐服务对象（若数据库不可用，给出清晰提示，避免端口未监听导致A2A侧连接失败）
    try:
        service = RecommendService()
    except Exception as e:
        logger.error(f"[启动失败] 数据库连接出错，请检查MySQL服务与 rental 库: {e}")
        return

    @recommend_mcp.tool(
        name="query_recommend",
        description="综合推荐查询，输入 SQL，如 'SELECT * FROM house_listing WHERE rent < 2000 AND metro_line LIKE \"%1号线%\"'"
    )
    def query_recommend(sql: str) -> str:
        logger.info(f"执行综合推荐查询: {sql}")
        return service.execute_query(sql)

    # 打印服务器信息
    logger.info("=== 综合推荐MCP服务器信息 ===")
    logger.info(f"名称: {recommend_mcp.name}")
    logger.info(f"描述: {recommend_mcp.instructions}")

    # 运行服务器
    try:
        logger.info("推荐MCP服务器已启动，请访问 http://127.0.0.1:8007/mcp")
        recommend_mcp.run(transport="streamable-http")
    except Exception as e:
        logger.error(f"推荐MCP服务器启动失败: {e}")


if __name__ == '__main__':
    create_recommend_mcp_server()
