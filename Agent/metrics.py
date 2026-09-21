# -*- coding: utf-8 -*-
"""
指标采集模块 (Metrics Collector)
================================
为管理员数据看板提供实时运行指标。全局单例 `metrics`，线程安全。

指标分四层（对应 docs/ADMIN_DASHBOARD.md 看板四区块）:
  技术层: QPS / 请求耗时 P50/P99 / 错误数
  业务层: 路由分布 / 意图分布
  缓存层: RAG 答案缓存命中率
  质量层: 幻觉率 / 引用真实率 / 反思触发率 (来自评估回归门 eval_report)

用法:
  from Agent.metrics import metrics
  metrics.record_request(route="legal", intents="legal", latency_ms=1234, ok=True)
  metrics.record_cache(hit=True)
  metrics.record_llm(model="qwen-plus", prompt_tokens=800, completion_tokens=300)
"""
import os
import json
import glob
import time
import threading
from collections import Counter, deque

MAX_LATENCY = 1000          # 保留最近 1000 条耗时用于分位数
MAX_ERRORS = 20             # 保留最近错误


class MetricsCollector:
    def __init__(self):
        self._lock = threading.Lock()
        self.start_ts = time.time()
        self.requests_total = 0
        self.requests_ok = 0
        self.requests_err = 0
        self.latency_ms = deque(maxlen=MAX_LATENCY)
        self.route_dist = Counter()          # chat / legal / agent / error
        self.intent_dist = Counter()         # 六类意图 + out_of_scope
        self.cache_hit = 0
        self.cache_miss = 0
        self.llm_calls = 0
        self.llm_cost_cny = 0.0              # 估算成本(⑥模型路由启用后由 record_llm 写入)
        self.errors = deque(maxlen=MAX_ERRORS)
        self.agentic_reflects = 0            # 反思循环触发次数
        self.agentic_total = 0               # 法律问答总次数

    # ---------- 记录 ----------
    def record_request(self, route="chat", intents="", latency_ms=0.0, ok=True, err=None):
        with self._lock:
            self.requests_total += 1
            if ok:
                self.requests_ok += 1
            else:
                self.requests_err += 1
                if err:
                    self.errors.append({"ts": time.strftime("%H:%M:%S"), "route": route, "err": str(err)[:200]})
            self.route_dist[route] += 1
            if intents:
                for it in str(intents).split(","):
                    it = it.strip()
                    if it:
                        self.intent_dist[it] += 1
            self.latency_ms.append(float(latency_ms))

    def record_cache(self, hit: bool):
        with self._lock:
            if hit:
                self.cache_hit += 1
            else:
                self.cache_miss += 1

    def record_llm(self, model="", prompt_tokens=0, completion_tokens=0, cost_cny=0.0):
        with self._lock:
            self.llm_calls += 1
            self.llm_cost_cny += cost_cny

    def record_agentic(self, reflected: bool):
        with self._lock:
            self.agentic_total += 1
            if reflected:
                self.agentic_reflects += 1

    # ---------- 聚合 ----------
    def _pct(self, hist, p):
        if not hist:
            return None
        arr = sorted(hist)
        idx = min(len(arr) - 1, int((len(arr) - 1) * p))
        return round(arr[idx], 1)

    def snapshot(self, quality=None):
        """quality: 评估质量指标 dict, 默认从评估报告读取"""
        with self._lock:
            uptime = time.time() - self.start_ts
            qps = round(self.requests_total / uptime, 3) if uptime > 0 else 0.0
            total_cache = self.cache_hit + self.cache_miss
            data = {
                "uptime_s": round(uptime, 1),
                "qps": qps,
                "requests_total": self.requests_total,
                "requests_ok": self.requests_ok,
                "requests_err": self.requests_err,
                "latency_avg": round(sum(self.latency_ms) / len(self.latency_ms), 1) if self.latency_ms else 0.0,
                "latency_p50": self._pct(self.latency_ms, 0.50),
                "latency_p99": self._pct(self.latency_ms, 0.99),
                "latency_samples": len(self.latency_ms),
                "route_dist": dict(self.route_dist),
                "intent_dist": dict(self.intent_dist),
                "cache_hit": self.cache_hit,
                "cache_miss": self.cache_miss,
                "cache_hit_rate": round(self.cache_hit / total_cache, 4) if total_cache else None,
                "llm_calls": self.llm_calls,
                "llm_cost_cny": round(self.llm_cost_cny, 4),
                "agentic_total": self.agentic_total,
                "agentic_reflect_rate": round(self.agentic_reflects / self.agentic_total, 4) if self.agentic_total else None,
                "errors": list(self.errors),
            }
        if quality:
            data["quality"] = quality
        return data

    # ---------- 评估质量(静态/最近报告) ----------
    def quality_from_reports(self, results_dir):
        """读取最新 eval_report_*.json, 供看板质量区展示"""
        files = sorted(glob.glob(os.path.join(results_dir, "eval_report_*.json")))
        if not files:
            return {"source": "无评估报告", "note": "运行 python 实验脚本/eval_gate.py 生成"}
        path = files[-1]
        try:
            with open(path, encoding="utf-8") as f:
                r = json.load(f)
            return {
                "source": os.path.basename(path),
                "ts": r.get("timestamp", ""),
                "truth_rate": r.get("cur_truth_rate", {}),
                "fails": r.get("fails", []),
                "pass": not r.get("fails"),
            }
        except Exception:
            return {"source": "解析失败", "note": str(files[-1])}


metrics = MetricsCollector()
