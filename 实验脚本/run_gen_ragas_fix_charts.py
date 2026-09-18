# -*- coding: utf-8 -*-
"""生成 RAGAS 修复前后对比图 + 修复后三策略图"""
import os
import csv

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS_DIR = os.path.join(PROJECT_ROOT, "实验脚本", "results")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei"]
plt.rcParams["axes.unicode_minus"] = False

# 修复前 (v2, ragas_scores_v2.csv + hallucination_audit_v4.csv)
before = {"D_混合+Rerank": {"f": 0.429, "r": 0.691, "truth": 0.896},
          "C_混合无Rerank": {"f": 0.615, "r": 0.855, "truth": 0.965},
          "B_纯稠密": {"f": 0.635, "r": 0.768, "truth": 0.858}}
# 修复后 (v3)
after = {}
with open(os.path.join(RESULTS_DIR, "ragas_scores_v3.csv"), encoding="utf-8-sig") as f:
    for row in csv.DictReader(f):
        after[row["strategy"]] = {"f": float(row["faithfulness_mean"]),
                                  "r": float(row["answer_relevancy_mean"])}
with open(os.path.join(RESULTS_DIR, "hallucination_audit_v5.csv"), encoding="utf-8-sig") as f:
    truths = {s: [] for s in ["B_纯稠密", "C_混合无Rerank", "D_混合+Rerank"]}
    for row in csv.DictReader(f):
        if row["truth_rate"] != "":
            truths[row["strategy"]].append(float(row["truth_rate"]))
for s, vals in truths.items():
    after[s]["truth"] = sum(vals) / len(vals) if vals else None

STRATS = ["B 纯稠密", "C 混合检索", "D 混合+Rerank"]
KEY = {"B_纯稠密": "B 纯稠密", "C_混合无Rerank": "C 混合检索", "D_混合+Rerank": "D 混合+Rerank"}

# ============ 图 1: 修复前 vs 修复后（D 策略三指标） ============
fig, axes = plt.subplots(1, 3, figsize=(15, 4.4))
metrics = [("f", "RAGAS 忠实度\n(Faithfulness)", 0.35, 0.75),
           ("r", "RAGAS 答案相关性\n(AnswerRelevancy)", 0.6, 1.05),
           ("truth", "引用真实率\n(确定性条款命中)", 0.75, 1.05)]
for ax, (mk, title, lo, hi) in zip(axes, metrics):
    b = before["D_混合+Rerank"][mk]
    a = after["D_混合+Rerank"][mk]
    bars = ax.bar(["修复前\n(文档级重排)", "修复后\n(条款级重排)"], [b, a],
                  color=["#94a3b8", "#f97316"], width=0.5)
    for bar, v in zip(bars, [b, a]):
        ax.text(bar.get_x() + bar.get_width() / 2, v + 0.01, f"{v:.3f}", ha="center",
                fontsize=12, fontweight="bold")
    ax.set_title(title, fontsize=12)
    ax.set_ylim(lo, hi)
    if mk == "f":
        ax.text(0.5, 0.42, f"提升 {(a-b)/b*100:+.0f}%", ha="center", color="#dc2626", fontsize=10, fontweight="bold")
    ax.tick_params(axis="x", labelsize=10)
fig.suptitle("D 策略（混合+Rerank）：条款级重排修复前后对比", fontsize=13, y=1.02)
fig.tight_layout()
out1 = os.path.join(RESULTS_DIR, "ragas_fix_before_after.png")
fig.savefig(out1, dpi=150, bbox_inches="tight")
print("✅", out1)

# ============ 图 2: 修复后三策略对比 ============
fig, axes = plt.subplots(1, 3, figsize=(16, 4.6))
x = range(3)
colors = ["#94a3b8", "#60a5fa", "#f97316"]
for ax, (mk, title) in zip(axes, [("f", "RAGAS 忠实度"), ("r", "RAGAS 相关性"), ("truth", "引用真实率")]):
    vals = [after[k][mk] for k in ["B_纯稠密", "C_混合无Rerank", "D_混合+Rerank"]]
    bars = ax.bar(list(x), vals, color=colors, width=0.55)
    for bar, v in zip(bars, vals):
        ax.text(bar.get_x() + bar.get_width() / 2, v + 0.01, f"{v:.3f}", ha="center",
                fontsize=11, fontweight="bold")
    ax.set_title(title, fontsize=12)
    ax.set_xticks(list(x)); ax.set_xticklabels(STRATS, fontsize=10)
    ax.set_ylim(0.35 if mk == "f" else 0.6, 1.08)
fig.suptitle("RAGAS 交叉验证 + 确定性引用审计（条款级重排修复后, 8题×3策略×3次生成均值）", fontsize=13, y=1.02)
fig.tight_layout()
out2 = os.path.join(RESULTS_DIR, "ragas_cross_validation_chart_v2.png")
fig.savefig(out2, dpi=150, bbox_inches="tight")
print("✅", out2)
