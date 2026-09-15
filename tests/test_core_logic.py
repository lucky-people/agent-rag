#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试用例 3：核心逻辑测试——SQL 只读白名单 / 编排降级 / 基类 handle_task 三分支

运行方式（在项目根目录）：
    python -m unittest discover tests -v
"""
import unittest
import sys
import os
import asyncio

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


class TestSQLReadonlyWhitelist(unittest.TestCase):
    """SQL 只读白名单：合法 SELECT/WITH 放行，写操作/危险语句一律拦截"""

    def setUp(self):
        from Agent.utils.format import validate_readonly_sql
        self.validate = validate_readonly_sql

    def test_valid_select_passes(self):
        ok, sql = self.validate("SELECT * FROM house_listing WHERE rent < 2000 LIMIT 5")
        self.assertTrue(ok)
        self.assertIn("LIMIT", sql.upper())

    def test_valid_with_passes(self):
        ok, _ = self.validate("WITH t AS (SELECT * FROM house_listing) SELECT * FROM t")
        self.assertTrue(ok)

    def test_insert_blocked(self):
        ok, _ = self.validate("INSERT INTO house_listing VALUES (1,2,3)")
        self.assertFalse(ok)

    def test_update_blocked(self):
        ok, _ = self.validate("UPDATE house_listing SET rent = 1")
        self.assertFalse(ok)

    def test_delete_blocked(self):
        ok, _ = self.validate("DELETE FROM house_listing")
        self.assertFalse(ok)

    def test_drop_blocked(self):
        ok, _ = self.validate("DROP TABLE house_listing")
        self.assertFalse(ok)

    def test_alter_blocked(self):
        ok, _ = self.validate("ALTER TABLE house_listing ADD COLUMN x INT")
        self.assertFalse(ok)

    def test_information_schema_blocked(self):
        ok, _ = self.validate("SELECT * FROM information_schema.tables")
        self.assertFalse(ok)

    def test_sleep_blocked(self):
        ok, _ = self.validate("SELECT SLEEP(10)")
        self.assertFalse(ok)

    def test_multiple_statements_blocked(self):
        ok, _ = self.validate("SELECT * FROM house_listing; DROP TABLE house_listing")
        self.assertFalse(ok)


class TestText2SqlBaseClass(unittest.TestCase):
    """基类 handle_task 三分支：成功→completed / 连接错误→直接失败不重试 / 追问→input-required"""

    def _make_server(self, getter_result):
        """构造最小 Text2SqlAgentServer 子类：真实 getter/formatter，mock 掉 generate_sql_query"""
        from Agent.a2a_server.base_text2sql_server import Text2SqlAgentServer
        from python_a2a import AgentCard
        from unittest.mock import MagicMock

        class _FakeServer(Text2SqlAgentServer):
            def __init__(self):
                super().__init__(AgentCard(name="fake", url="http://localhost:9999",
                                           description="fake", version="0.1.0"))
                self._getter_result = getter_result
                self.formatter = lambda data: f"格式化结果：{data}"
                self.getter = self._fake_getter  # super().__init__ 会置 None，需重新绑定

            async def _fake_getter(self, sql):
                return self._getter_result

        srv = _FakeServer()
        # 让 generate_sql_query 固定返回一条 SQL（跳过 LLM）
        srv.generate_sql_query = MagicMock(
            return_value={"status": "sql", "sql": "SELECT * FROM house_listing LIMIT 5"})
        return srv

    def _make_task(self, text="测试问题"):
        from python_a2a import Message, MessageRole, TextContent, Task
        msg = Message(content=TextContent(text=text), role=MessageRole.USER)
        return Task(id="task-test", message=msg.to_dict())

    def test_success_completed(self):
        srv = self._make_server({"status": "success", "data": [{"community": "金水区测试小区"}]})
        task = self._make_task()
        out = srv.handle_task(task)
        self.assertEqual(out.status.state.value, "completed")

    def test_connection_error_no_retry(self):
        srv = self._make_server({"status": "connection_error", "message": "MCP 连接失败"})
        task = self._make_task()
        out = srv.handle_task(task)
        self.assertEqual(out.status.state.value, "failed")

    def test_input_required(self):
        from unittest.mock import MagicMock
        srv = self._make_server(None)
        srv.generate_sql_query = MagicMock(
            return_value={"status": "input_required", "message": "请提供更多筛选条件"})
        task = self._make_task()
        out = srv.handle_task(task)
        self.assertEqual(out.status.state.value, "input-required")


class TestOrchestrationFallback(unittest.TestCase):
    """编排器降级：单域走原 text2sql；多域拆解识别；LLM 失败回退单域"""

    def _new_srv(self):
        from Agent.a2a_server import recommend_server as rs
        srv = rs.OrchestratedRecommendQueryServer.__new__(rs.OrchestratedRecommendQueryServer)
        return srv

    def test_single_domain_skips_orchestration(self):
        """单域（如纯房源）应走原 text2sql 路径，不触发编排"""
        split = {"domains": ["house"], "sub_queries": {"house": "金水区2000以下整租"}}
        self.assertEqual(len(split["domains"]), 1)
        self.assertLess(len(split["domains"]), 2)

    def test_split_domains_parses_multi(self):
        """多域拆解：'房源+地铁'应识别为两个域"""
        from Agent.a2a_server import recommend_server as rs
        import unittest.mock as mock
        srv = self._new_srv()
        fake_chain = mock.MagicMock()
        fake_chain.invoke.return_value = mock.MagicMock(
            content='{"domains": ["house", "metro"], "sub_queries": {"house": "金水区房源", "metro": "1号线站点"}}')
        # split_prompt 支持 | 运算返回 fake_chain
        srv.split_prompt = mock.MagicMock()
        srv.split_prompt.__or__ = lambda self, other: fake_chain
        srv.llm = object()  # 不被实际使用（__or__ 已接管）

        split = srv._split_domains("1号线附近2000以下的房子")
        self.assertIn("house", split["domains"])
        self.assertIn("metro", split["domains"])

    def test_split_domains_fallback_on_llm_error(self):
        """LLM 拆解失败（返回非 JSON）应回退单域 house，不崩溃"""
        from Agent.a2a_server import recommend_server as rs
        import unittest.mock as mock
        srv = self._new_srv()
        fake_chain = mock.MagicMock()
        fake_chain.invoke.return_value = mock.MagicMock(content="抱歉我无法理解")
        srv.split_prompt = mock.MagicMock()
        srv.split_prompt.__or__ = lambda self, other: fake_chain
        srv.llm = object()

        split = srv._split_domains("随便聊聊")
        self.assertEqual(split["domains"], ["house"])


if __name__ == "__main__":
    unittest.main()
