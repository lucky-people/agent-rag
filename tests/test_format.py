#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试用例 1：工具函数测试（Agent/utils/format.py）

运行方式（在项目根目录）：
    python -m unittest discover tests -v
    或
    python -m unittest tests.test_format -v
"""
import json
import unittest
import sys
import os

# 把项目根目录加入 sys.path，保证 import 正常
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from Agent.utils.format import (
    ensure_limit,
    format_exception,
    robust_json_loads,
    extract_sql,
    DateEncoder,
)
from datetime import date, datetime
from decimal import Decimal


class TestEnsureLimit(unittest.TestCase):
    """测试 SQL 自动补 LIMIT 逻辑"""

    def test_plain_select_adds_limit(self):
        self.assertEqual(
            ensure_limit("SELECT * FROM house_listing"),
            "SELECT * FROM house_listing LIMIT 20",
        )

    def test_select_with_semicolon(self):
        self.assertEqual(
            ensure_limit("SELECT id FROM poi_data;"),
            "SELECT id FROM poi_data LIMIT 20;",
        )

    def test_existing_limit_unchanged(self):
        sql = "SELECT * FROM house_listing LIMIT 5"
        self.assertEqual(ensure_limit(sql), sql)

    def test_non_select_unchanged(self):
        sql = "UPDATE house_listing SET price = 100"
        self.assertEqual(ensure_limit(sql), sql)

    def test_empty_unchanged(self):
        self.assertEqual(ensure_limit(""), "")


class TestRobustJsonLoads(unittest.TestCase):
    """测试 LLM 脏输出 JSON 解析"""

    def test_normal_json(self):
        self.assertEqual(robust_json_loads('{"a": 1}'), {"a": 1})

    def test_code_fence(self):
        text = '```json\n{"name": "金水区"}\n```'
        self.assertEqual(robust_json_loads(text), {"name": "金水区"})

    def test_surrounding_text(self):
        text = '好的，结果是：{"price": 1500} 以上就是查询结果。'
        self.assertEqual(robust_json_loads(text), {"price": 1500})

    def test_trailing_comma(self):
        text = '{"a": 1, "b": 2,}'
        self.assertEqual(robust_json_loads(text), {"a": 1, "b": 2})

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            robust_json_loads("")


class TestExtractSql(unittest.TestCase):
    """测试从 LLM 输出中提取 SQL"""

    def test_code_fence(self):
        text = '```sql\nSELECT * FROM metro_station\n```'
        self.assertEqual(extract_sql(text), "SELECT * FROM metro_station")

    def test_label_prefix(self):
        text = 'SQL: SELECT * FROM house_listing WHERE price < 2000'
        self.assertEqual(extract_sql(text), "SELECT * FROM house_listing WHERE price < 2000")

    def test_no_sql_returns_empty(self):
        self.assertEqual(extract_sql("今天天气不错"), "")

    def test_semicolon_stripped(self):
        self.assertEqual(extract_sql("SELECT id FROM poi_data;"), "SELECT id FROM poi_data")


class TestDateEncoder(unittest.TestCase):
    """测试 JSON 编码器对特殊类型的序列化"""

    def test_datetime(self):
        obj = {"time": datetime(2026, 9, 15, 10, 30, 0)}
        result = json.loads(json.dumps(obj, cls=DateEncoder))
        self.assertEqual(result["time"], "2026-09-15 10:30:00")

    def test_date(self):
        obj = {"day": date(2026, 9, 15)}
        result = json.loads(json.dumps(obj, cls=DateEncoder))
        self.assertEqual(result["day"], "2026-09-15")

    def test_decimal(self):
        obj = {"price": Decimal("1500.50")}
        result = json.loads(json.dumps(obj, cls=DateEncoder))
        self.assertEqual(result["price"], 1500.5)


class TestFormatException(unittest.TestCase):
    """测试异常格式化（展开异常组）"""

    def test_normal_exception(self):
        self.assertEqual(format_exception(ValueError("出错")), "出错")

    def test_empty_string(self):
        self.assertEqual(format_exception(Exception("")), "")


if __name__ == "__main__":
    unittest.main()
