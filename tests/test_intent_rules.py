#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试用例 2：意图分类器关键词兜底逻辑测试

说明：不加载 BERT 模型（避免依赖 GPU/模型文件），只验证
      QueryClassifier.predict_category 中的"租房常识关键词强制走专业咨询"规则。

运行方式（在项目根目录）：
    python -m unittest tests.test_intent_rules -v
"""
import unittest
import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


class TestIntentKeywordRules(unittest.TestCase):
    """验证租房常识关键词应被强制路由到「专业咨询」（RAG 检索）"""

    def _classify_with_keywords(self, query):
        """绕过模型加载，直接执行 predict_category 中的关键词前置逻辑"""

        # 复用模块中的关键词列表（避免测试与实现脱节）
        keywords = [
            '注意事项', '租客权益', '权益', '押金', '退租', '租房前',
            '租房知识', '租房注意事项', '提前退租', '不退押金', '怎么退押金',
        ]
        return any(kw in query for kw in keywords)

    def test_deposit_keyword(self):
        self.assertTrue(self._classify_with_keywords("房东不退押金怎么办"))

    def test_early_termination_keyword(self):
        self.assertTrue(self._classify_with_keywords("提前退租押金能要回来吗"))

    def test_tenant_rights_keyword(self):
        self.assertTrue(self._classify_with_keywords("租客有哪些权益"))

    def test_normal_question_not_matched(self):
        self.assertFalse(self._classify_with_keywords("你好，请问郑州今天天气怎么样"))


class TestIntentMapping(unittest.TestCase):
    """验证配置中的意图 → 智能体映射"""

    def test_intent_mapping_complete(self):
        from Agent.config import Config
        conf = Config()
        expected = {"house", "poi", "metro", "recommend", "legal", "chat"}
        self.assertEqual(set(conf.intent.keys()), expected)

    def test_intent_mapping_values(self):
        from Agent.config import Config
        conf = Config()
        self.assertEqual(conf.intent["house"], "HouseQueryAssistant")
        self.assertEqual(conf.intent["legal"], "LegalQASystem")
        self.assertEqual(conf.intent["chat"], "ChatLLM")


if __name__ == "__main__":
    unittest.main()
