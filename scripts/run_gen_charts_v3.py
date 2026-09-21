# -*- coding: utf-8 -*-
"""生成修复版评估对比图 v3:
  1. 检索质量直接评判（相关性/支撑性）— Rerank 排序价值
  2. 生产配置 Top-2 对比 — CANDIDATE_M=2 下 Rerank 优势
  3. 答案质量对比（可见上下文评判）
"""
import os
import csv
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False

RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")

STRATS = ["B_纯稠密", "C_混合无Rerank", "D_混合+Rerank"]
LABELS = {"B_纯稠密": "B 纯稠密", "C_混合无Rerank": "C 混合检索", "D_混合+Rerank": "D 混合+Rerank"}
COLORS = {"B_纯稠密": "#FA8C16", "C_混合无Rerank": "#52C41A", "D_混合+Rerank": "#722ED1"}


def load(name):
    rows = []
    with open(os.path.join(RESULTS, name), encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            rows.append(r)
    return rows


# ============ 图1: 检索质量直接评判 ============
retr = load("e2e_retrieval_scores.csv")
fig, axes = plt.subplots(1, 3, figsize=(18, 5.2))

ax = axes[0]
x = np.arange(2)
w = 0.26
for i, s in enumerate(STRATS):
    sr = [r for r in retr if r["strategy"] == s]
    rel = sum(float(r["relevance"]) for r in sr) / len(sr)
    sup = sum(float(r["support"]) for r in sr) / len(sr)
    bars = ax.bar(x + (i - 1) * w, [rel, sup], w, label=LABELS[s], color=COLORS[s])
    for b, v in zip(bars, [rel, sup]):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.08, f"{v:.2f}", ha="center", fontsize=10, fontweight="bold")
ax.set_xticks(x)
ax.set_xticklabels(["相关性\n(文档是否相关)", "支撑性\n(能否支撑回答)"], fontsize=10)
ax.set_ylim(0, 5.4)
ax.set_ylabel("LLM 评判得分 (0-5)")
ax.set_title("检索质量直接评判（不经过生成）\nRerank 让进 LLM 的文档最相关", fontsize=12.5, fontweight="bold")
ax.legend(fontsize=9)
ax.grid(axis="y", alpha=0.3, linestyle="--")
ax.annotate("", xy=(0 + w, 4.0), xytext=(0 - w, 2.75),
            arrowprops=dict(arrowstyle="->", color="#333", lw=1.5))
ax.text(0, 4.4, "相关性 +45%", ha="center", fontsize=11, color="#333", fontweight="bold")

# ============ 图2: 逐题相关性对比 ============
ax = axes[1]
qids = []
for r in retr:
    if r["qid"] not in qids:
        qids.append(r["qid"])
b_rel, c_rel, d_rel = [], [], []
for qid in qids:
    qr = {r["strategy"]: r for r in retr if r["qid"] == qid}
    b_rel.append(float(qr["B_纯稠密"]["relevance"]))
    c_rel.append(float(qr["C_混合无Rerank"]["relevance"]))
    d_rel.append(float(qr["D_混合+Rerank"]["relevance"]))
x2 = np.arange(len(qids))
w2 = 0.26
ax.bar(x2 - w2, b_rel, w2, label="B 纯稠密", color=COLORS["B_纯稠密"])
ax.bar(x2, c_rel, w2, label="C 混合", color=COLORS["C_混合无Rerank"])
ax.bar(x2 + w2, d_rel, w2, label="D 混合+Rerank", color=COLORS["D_混合+Rerank"])
ax.set_xticks(x2)
ax.set_xticklabels(qids, fontsize=10)
ax.set_ylim(0, 5.6)
ax.set_ylabel("相关性得分 (0-5)")
ax.set_title("逐题检索相关性：D 在 8 题中 6 题领先\n（Q1/Q5/Q6 差距最大）", fontsize=12.5, fontweight="bold")
ax.legend(fontsize=9)
ax.grid(axis="y", alpha=0.3, linestyle="--")

# ============ 图3: 生产配置 Top-2 对比 ============
ax = axes[2]
prod = load("e2e_prod_top2_scores.csv")
pstats = {}
for s in ["C_混合无Rerank", "D_混合+Rerank"]:
    sr = [r for r in prod if r["strategy"] == s]
    pstats[s] = {
        "faith": sum(float(r["faithfulness"]) for r in sr) / len(sr),
        "cit": sum(float(r["citation"]) for r in sr) / len(sr),
        "comp": sum(float(r["completeness"]) for r in sr) / len(sr),
    }
    pstats[s]["total"] = (pstats[s]["faith"] + pstats[s]["cit"] + pstats[s]["comp"]) / 3
labels3 = ["忠实度", "引用准确率", "完整性", "综合分"]
x3 = np.arange(4)
w3 = 0.32
c_vals = [pstats["C_混合无Rerank"][m] for m in ["faith", "cit", "comp", "total"]]
d_vals = [pstats["D_混合+Rerank"][m] for m in ["faith", "cit", "comp", "total"]]
ax.bar(x3 - w3 / 2, c_vals, w3, label="C 混合 Top-2", color=COLORS["C_混合无Rerank"])
ax.bar(x3 + w3 / 2, d_vals, w3, label="D 混合+Rerank Top-2", color=COLORS["D_混合+Rerank"])
for i, v in enumerate(c_vals):
    ax.text(i - w3 / 2, v + 0.06, f"{v:.2f}", ha="center", fontsize=9.5, fontweight="bold")
for i, v in enumerate(d_vals):
    ax.text(i + w3 / 2, v + 0.06, f"{v:.2f}", ha="center", fontsize=9.5, fontweight="bold")
ax.set_xticks(x3)
ax.set_xticklabels(labels3, fontsize=10)
ax.set_ylim(0, 5.6)
ax.set_ylabel("LLM 评判得分 (0-5)")
ax.set_title("生产配置（CANDIDATE_M=2, Top-2 进 LLM）\n排序质量直接决定答案：D 综合 +55%", fontsize=12.5, fontweight="bold")
ax.legend(fontsize=9)
ax.grid(axis="y", alpha=0.3, linestyle="--")

fig.suptitle("混合检索 + Rerank 选型价值评估（修复版：评判可见上下文，GPU 实测）", fontsize=14.5, fontweight="bold", y=0.98)
plt.tight_layout(rect=[0, 0, 1, 0.94])
plt.savefig(os.path.join(RESULTS, "e2e_v2_chart.png"), dpi=150, bbox_inches="tight")
plt.close()
print("✅ e2e_v2_chart.png")
