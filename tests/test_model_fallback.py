# -*- coding: utf-8 -*-
"""模型缺失兜底测试: 全新 clone(未下载 models/) 时不应因缺本地模型而崩溃.

覆盖 Agent/legal_qa/rag_qa/core/query_classifier.py::_resolve_bert_base
(本地 models/bert-base-chinese 缺失 -> 回退 HuggingFace 仓库名, 由 HF 自动下载).
测试用假的模型根目录 + mock, 不依赖本机是否下载过模型.
"""
import os
import sys
import unittest
from unittest import mock

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from Agent.legal_qa.rag_qa.core import query_classifier  # noqa: E402

# 一定不存在的模型根目录: 用于模拟"全新 clone 未下载模型"的环境.
FAKE_MODEL_ROOT = os.path.join(PROJECT_ROOT, 'no_such_models_root_for_test')


class TestBertBaseFallback(unittest.TestCase):
    def setUp(self):
        self._old_root = os.environ.get('RAG_MODEL_ROOT')
        self.addCleanup(self._restore_env)
        os.environ['RAG_MODEL_ROOT'] = FAKE_MODEL_ROOT

    def _restore_env(self):
        if self._old_root is None:
            os.environ.pop('RAG_MODEL_ROOT', None)
        else:
            os.environ['RAG_MODEL_ROOT'] = self._old_root

    def test_local_model_preferred(self):
        """本地 models/bert-base-chinese 存在时优先返回本地路径, 不走 HF 下载."""
        local = os.path.join(FAKE_MODEL_ROOT, 'models', 'bert-base-chinese')
        with mock.patch.object(query_classifier, 'rag_qa_path', FAKE_MODEL_ROOT), \
                mock.patch.object(query_classifier.os.path, 'exists', side_effect=lambda p: p == local):
            self.assertEqual(query_classifier._resolve_bert_base(), local)

    def test_repo_name_when_local_missing(self):
        """本地模型全缺失时回退 HF 仓库名, 而不是抛 OSError 让法律问答链路起不来."""
        self.assertFalse(os.path.exists(FAKE_MODEL_ROOT))
        with mock.patch.object(query_classifier, 'rag_qa_path', FAKE_MODEL_ROOT):
            self.assertEqual(query_classifier._resolve_bert_base(), query_classifier.BERT_BASE_REPO)


if __name__ == "__main__":
    unittest.main()
