# -*- coding: utf-8 -*-
"""MetricsCollector 单元测试: 指标记录/分位数/快照/评估报告读取"""
import os
import sys
import unittest
import tempfile
import json

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from Agent.metrics import MetricsCollector  # noqa: E402


class TestMetricsCollector(unittest.TestCase):
    def setUp(self):
        self.m = MetricsCollector()

    def test_record_request(self):
        self.m.record_request(route="legal", intents="legal,contract", latency_ms=1000.0, ok=True)
        self.m.record_request(route="chat", intents="chat", latency_ms=2000.0, ok=True)
        self.m.record_request(route="error", intents="", latency_ms=500.0, ok=False, err="boom")
        s = self.m.snapshot()
        self.assertEqual(s["requests_total"], 3)
        self.assertEqual(s["requests_ok"], 2)
        self.assertEqual(s["requests_err"], 1)
        self.assertEqual(s["route_dist"]["legal"], 1)
        self.assertEqual(s["route_dist"]["error"], 1)
        self.assertEqual(s["intent_dist"]["legal"], 1)
        self.assertEqual(s["intent_dist"]["contract"], 1)
        self.assertEqual(len(s["errors"]), 1)
        self.assertEqual(s["errors"][0]["err"], "boom")

    def test_percentile(self):
        for i in range(1, 101):
            self.m.record_request(route="chat", intents="chat", latency_ms=float(i), ok=True)
        s = self.m.snapshot()
        self.assertAlmostEqual(s["latency_p50"], 50.0, places=0)
        self.assertAlmostEqual(s["latency_p99"], 99.0, places=0)

    def test_cache_rate(self):
        self.m.record_cache(True)
        self.m.record_cache(True)
        self.m.record_cache(False)
        s = self.m.snapshot()
        self.assertAlmostEqual(s["cache_hit_rate"], round(2 / 3, 4))
        s2 = MetricsCollector().snapshot()
        self.assertIsNone(s2["cache_hit_rate"])

    def test_agentic_rate(self):
        self.m.record_agentic(reflected=True)
        self.m.record_agentic(reflected=False)
        s = self.m.snapshot()
        self.assertEqual(s["agentic_total"], 2)
        self.assertAlmostEqual(s["agentic_reflect_rate"], 0.5)

    def test_quality_from_reports(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "eval_report_20260921_120000.json")
            with open(p, "w", encoding="utf-8") as f:
                json.dump({"timestamp": "20260921_120000", "fails": [],
                           "cur_truth_rate": {"B_纯稠密": 0.9, "D_混合+Rerank": 0.95}}, f)
            q = self.m.quality_from_reports(d)
            self.assertTrue(q["pass"])
            self.assertEqual(q["truth_rate"]["D_混合+Rerank"], 0.95)
        q2 = self.m.quality_from_reports(os.path.join(tempfile.gettempdir(), "no_such_dir_xyz"))
        self.assertIn("note", q2)


if __name__ == "__main__":
    unittest.main()
