# -*- coding: utf-8 -*-
"""
生成"体现选型优点"的评估对比图（v2）:
  1. 端到端答案质量对比（忠实度/引用准确率/完整性/综合分）— 核心图
  2. 消融策略 GPU 耗时 + 生产路径对比
输出: 实验脚本/results/e2e_quality_chart.png, ablation_gpu_chart.png
"""
import os
import sys
import csv
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False

RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
os.makedirs(RESULTS, exist_ok=True)

# ============ 1. 端到端答案质量 ============
rows = []
with open(os.path.join(RESULTS, "e2e_answer_quality.csv"), encoding="utf-8-sig") as f:
    for r in csv.DictReader(f):
        rows.append(r)

strategies = ["B_纯稠密", "C_混合无Rerank", "D_混合+Rerank"]
labels = {"B_纯稠密": "B 纯稠密向量", "C_混合无Rerank": "C 混合检索", "D_混合+Rerank": "D 混合+Rerank"}
colors = {"B_纯稠密": "#FA8C16", "C_混合无Rerank": "#52C41A", "D_混合+Rerank": "#722ED1"}

agg = {}
for s in strategies:
    sr = [r for r in rows if r["strategy"] == s]
    n = len(sr)
    agg[s] = {
        "faith": sum(float(r["faithfulness"]) for r in sr) / n,
        "cit": sum(float(r["citation"]) for r in sr) / n,
        "comp": sum(float(r["completeness"]) for r in sr) / n,
    }
    agg[s]["total"] = (agg[s]["faith"] + agg[s]["cit"] + agg[s]["comp"]) / 3

metrics = ["faith", "cit", "comp", "total"]
metric_names = ["忠实度", "引用准确率", "完整性", "综合分"]

fig, axes = plt.subplots(1, 2, figsize=(15, 5.6))

# 左: 三项质量维度 + 综合分
ax = axes[0]
x = np.arange(len(metrics))
w = 0.26
for i, s in enumerate(strategies):
    vals = [agg[s][m] for m in metrics]
    bars = ax.bar(x + (i - 1) * w, vals, w, label=labels[s], color=colors[s])
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.05, f"{v:.2f}",
                ha="center", fontsize=8.5, fontweight="bold")
ax.set_xticks(x)
ax.set_xticklabels(metric_names, fontsize=11)
ax.set_ylim(0, 5.5)
ax.set_ylabel("LLM 评判得分 (0-5)")
ax.set_title("端到端答案质量：混合检索提升 37%\n（Rerank 保证进入 LLM 的上下文最相关）", fontsize=12.5, fontweight="bold")
ax.legend(fontsize=9)
ax.grid(axis="y", alpha=0.3, linestyle="--")
ax.axhline(0, color="black", linewidth=0.8)
ax.annotate("", xy=(3 + w, agg["C_混合无Rerank"]["total"]), xytext=(3 - w, agg["B_纯稠密"]["total"]),
            arrowprops=dict(arrowstyle="->", color="#333", lw=1.5))
ax.text(3, 4.6, f"+{(agg['C_混合无Rerank']['total'] - agg['B_纯稠密']['total'])/agg['B_纯稠密']['total']*100:.0f}%",
        ha="center", fontsize=12, color="#333", fontweight="bold")

# 右: 逐题综合分对比（Q5 困难题亮点）
ax = axes[1]
qids = []
b_scores, c_scores, d_scores = [], [], []
for r in rows:
    qid = r["qid"]
    if qid not in qids:
        qids.append(qid)
for qid in qids:
    qr = {r["strategy"]: r for r in rows if r["qid"] == qid}
    for s, lst in [("B_纯稠密", b_scores), ("C_混合无Rerank", c_scores), ("D_混合+Rerank", d_scores)]:
        rr = qr[s]
        lst.append((float(rr["faithfulness"]) + float(rr["citation"]) + float(rr["completeness"])) / 3)

x2 = np.arange(len(qids))
w2 = 0.26
ax.bar(x2 - w2, b_scores, w2, label="B 纯稠密", color=colors["B_纯稠密"])
ax.bar(x2, c_scores, w2, label="C 混合", color=colors["C_混合无Rerank"])
ax.bar(x2 + w2, d_scores, w2, label="D 混合+Rerank", color=colors["D_混合+Rerank"])
ax.set_xticks(x2)
ax.set_xticklabels(qids, fontsize=10)
ax.set_ylim(0, 5.5)
ax.set_ylabel("综合分 (0-5)")
ax.set_title("逐题综合质量：困难题 Q5 上 Rerank 优势明显\n（B/C 均失败，D 找回证据得 3 分）", fontsize=12.5, fontweight="bold")
ax.legend(fontsize=9, loc="lower right")
ax.grid(axis="y", alpha=0.3, linestyle="--")

fig.suptitle("RAG 检索策略 → 端到端答案质量（LLM 评判，GPU 实测）", fontsize=14.5, fontweight="bold", y=0.98)
plt.tight_layout(rect=[0, 0, 1, 0.94])
plt.savefig(os.path.join(RESULTS, "e2e_quality_chart.png"), dpi=150, bbox_inches="tight")
plt.close()
print("✅ e2e_quality_chart.png")

# ============ 2. 消融 GPU 耗时 + 生产路径 ============
# 消融实验 GPU 实测（最新一轮）
ablation_gpu = {
    "A 纯BM25": 38.0,          # BM25 走 MySQL，CPU/GPU 无差
    "B 纯稠密": 356.8,
    "C 混合": 275.6,
    "D 混合+Rerank\n(全量重排)": 30039.2,
}
# 生产路径 CANDIDATE_M=2 GPU 实测
prod_d = 1816.4  # 取稳定态中间值

fig, ax = plt.subplots(figsize=(9.5, 5))
strategies2 = list(ablation_gpu.keys())
vals = list(ablation_gpu.values())
colors2 = ["#4C9BE8", "#4C9BE8", "#4C9BE8", "#F5222D"]
bars = ax.bar(strategies2, vals, color=colors2, width=0.55)
ax.set_yscale("log")
ax.set_ylim(10, 60000)
for b, v in zip(bars, vals):
    ax.text(b.get_x() + b.get_width() / 2, v * 1.15, f"{v:,.0f} ms" if v >= 100 else f"{v} ms",
            ha="center", va="bottom", fontsize=10, fontweight="bold")
# 生产路径标注
ax.axhline(prod_d, color="#722ED1", linestyle="--", linewidth=2)
ax.text(1.45, prod_d * 1.25, f"生产路径(CANDIDATE_M=2) D+Rerank ≈ {prod_d:.0f} ms",
        fontsize=10, color="#722ED1", fontweight="bold")
ax.set_ylabel("平均耗时 (ms, 对数刻度)")
ax.set_title("RAG 检索策略 GPU 实测耗时\n（消融为公平对比全量重排；生产代码仅精排 Top-2）", fontsize=12.5, fontweight="bold")
ax.grid(axis="y", alpha=0.3, linestyle="--")
ax.text(0.02, 0.95, "GPU: RTX 4060\nBGE-M3 + BGE-Reranker-Large",
        transform=ax.transAxes, fontsize=9, va="top",
        bbox=dict(boxstyle="round", facecolor="#F6FFED", edgecolor="#52C41A"))
plt.tight_layout()
plt.savefig(os.path.join(RESULTS, "ablation_gpu_chart.png"), dpi=150, bbox_inches="tight")
plt.close()
print("✅ ablation_gpu_chart.png")
