# -*- coding: utf-8 -*-
"""
生成评估对比图（补充）:
  1. 三链路响应时长对比 (MySQL / Redis / RAG) — 对数刻度突出 3 个数量级差距
  2. Agentic RAG vs 朴素 RAG 端到端对比 (耗时/答案长度/反思轮数)
输出: 实验脚本/results/chain_latency_chart.png, agentic_vs_naive_chart.png
"""
import os
import sys
import csv
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# 中文字体
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False

RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
os.makedirs(RESULTS, exist_ok=True)

# ============ 1. 三链路延迟对比 ============
chains = ["A. MySQL\n直答", "B. Redis\n缓存", "C. RAG\n全链路"]
avg_ms = [10.8, 2.4, 8908.1]
per_q = {"MySQL": [27.1, 13.1, 8.1, 7.5, 8.2, 7.0, 7.0, 8.0],
         "Redis": [2.7, 2.8, 2.1, 2.2, 2.1],
         "RAG": [7600.4, 12356.5, 9419.3, 7545.7, 7618.4]}

fig, axes = plt.subplots(1, 2, figsize=(13, 5))

# 左: 平均耗时对数柱状
ax = axes[0]
colors = ["#4C9BE8", "#52C41A", "#F5222D"]
bars = ax.bar(chains, avg_ms, color=colors, width=0.55)
ax.set_yscale("log")
ax.set_ylim(1, 50000)
for b, v in zip(bars, avg_ms):
    ax.text(b.get_x() + b.get_width() / 2, v * 1.3, f"{v:,.1f} ms",
            ha="center", va="bottom", fontsize=11, fontweight="bold")
ax.set_ylabel("平均耗时 (ms, 对数刻度)")
ax.set_title("三链路响应时长对比（数量级差异）", fontsize=13, fontweight="bold")
ax.grid(axis="y", alpha=0.3, linestyle="--")
ax.text(0.98, 0.95, "加速比: Redis≈3700x\nMySQL≈825x (vs RAG)",
        transform=ax.transAxes, ha="right", va="top", fontsize=10,
        bbox=dict(boxstyle="round", facecolor="#FFF7E6", edgecolor="#FAAD14", alpha=0.9))

# 右: 逐问题散点/条形
ax = axes[1]
labels = [f"MySQL ×{len(per_q['MySQL'])}", f"Redis ×{len(per_q['Redis'])}", f"RAG ×{len(per_q['RAG'])}"]
data = [per_q["MySQL"], per_q["Redis"], per_q["RAG"]]
for i, (lab, d, c) in enumerate(zip(labels, data, colors)):
    xs = np.random.normal(i, 0.08, len(d))
    ax.scatter(xs, d, s=45, c=c, alpha=0.8, label=lab, zorder=3)
    ax.hlines(np.mean(d), i - 0.3, i + 0.3, colors=c, linewidths=2.5, zorder=4)
    ax.text(i, np.mean(d) * 1.15, f"均值 {np.mean(d):,.1f}ms", ha="center", fontsize=9)
ax.set_yscale("log")
ax.set_ylim(1, 30000)
ax.set_xticks(range(3))
ax.set_xticklabels(labels)
ax.set_ylabel("单题耗时 (ms, 对数刻度)")
ax.set_title("逐问题耗时分布（点=单题，横线=均值）", fontsize=13, fontweight="bold")
ax.grid(axis="y", alpha=0.3, linestyle="--")
ax.legend(loc="upper left", fontsize=9)

fig.suptitle("链路架构价值量化：MySQL/Redis 毫秒级直答 vs RAG 秒级生成", fontsize=14, fontweight="bold", y=0.98)
plt.tight_layout(rect=[0, 0, 1, 0.95])
plt.savefig(os.path.join(RESULTS, "chain_latency_chart.png"), dpi=150, bbox_inches="tight")
plt.close()
print("✅ chain_latency_chart.png")

# ============ 2. Agentic vs 朴素 RAG 端到端对比 ============
rows = []
csv_path = os.path.join(RESULTS, "agentic_vs_naive.csv")
with open(csv_path, encoding="utf-8-sig") as f:
    for r in csv.DictReader(f):
        rows.append(r)

qids = [r["qid"] for r in rows]
naive_ms = [float(r["naive_ms"]) for r in rows]
agentic_ms = [float(r["agentic_ms"]) for r in rows]
naive_len = [int(r["naive_len"]) for r in rows]
agentic_len = [int(r["agentic_len"]) for r in rows]
rounds = [int(r["agentic_rounds"]) for r in rows]

fig, axes = plt.subplots(1, 3, figsize=(16, 5))

# 左: 耗时对比
ax = axes[0]
x = np.arange(len(qids))
w = 0.35
ax.bar(x - w / 2, naive_ms, w, label="朴素 RAG", color="#4C9BE8")
ax.bar(x + w / 2, agentic_ms, w, label="Agentic RAG", color="#722ED1")
ax.set_yscale("log")
ax.set_xticks(x)
ax.set_xticklabels(qids, rotation=30, ha="right", fontsize=8)
ax.set_ylabel("端到端耗时 (ms, 对数)")
ax.set_title("端到端耗时对比\n(Agentic 含反思+重检索)", fontsize=12, fontweight="bold")
ax.legend(fontsize=9)
ax.grid(axis="y", alpha=0.3, linestyle="--")
for i in range(len(qids)):
    ax.text(i - w / 2, naive_ms[i] * 1.25, f"{naive_ms[i]/1000:.1f}s", ha="center", fontsize=7.5, color="#4C9BE8")
    ax.text(i + w / 2, agentic_ms[i] * 1.25, f"{agentic_ms[i]/1000:.0f}s", ha="center", fontsize=7.5, color="#722ED1")

# 中: 答案长度对比
ax = axes[1]
ax.bar(x - w / 2, naive_len, w, label="朴素 RAG", color="#4C9BE8")
ax.bar(x + w / 2, agentic_len, w, label="Agentic RAG", color="#722ED1")
ax.set_xticks(x)
ax.set_xticklabels(qids, rotation=30, ha="right", fontsize=8)
ax.set_ylabel("答案长度 (字)")
ax.set_title("答案生成长度对比", fontsize=12, fontweight="bold")
ax.legend(fontsize=9)
ax.grid(axis="y", alpha=0.3, linestyle="--")

# 右: 反思轮数与耗时关系
ax = axes[2]
avg_naive = np.mean(naive_ms)
avg_agentic = np.mean(agentic_ms)
bar_labels = ["朴素 RAG\n(0 反思)", "Agentic\n(平均反思 1.3 轮)"]
bars = ax.bar(bar_labels, [avg_naive / 1000, avg_agentic / 1000],
              color=["#4C9BE8", "#722ED1"], width=0.5)
for b, v in zip(bars, [avg_naive / 1000, avg_agentic / 1000]):
    ax.text(b.get_x() + b.get_width() / 2, v + 1, f"{v:.1f}s", ha="center", fontsize=12, fontweight="bold")
ax.set_ylabel("平均耗时 (s)")
ax.set_title("反思机制成本量化\n(Agentic 代价 ≈10.4x)", fontsize=12, fontweight="bold")
ax.grid(axis="y", alpha=0.3, linestyle="--")
ax.text(0.98, 0.95, "成功率均为 100%\nAgentic 答案平均更长\n(376 vs 347 字)",
        transform=ax.transAxes, ha="right", va="top", fontsize=9,
        bbox=dict(boxstyle="round", facecolor="#F6FFED", edgecolor="#52C41A", alpha=0.9))

fig.suptitle("Agentic RAG (Self-RAG 反思) vs 朴素 RAG 端到端对比", fontsize=14, fontweight="bold", y=0.98)
plt.tight_layout(rect=[0, 0, 1, 0.95])
plt.savefig(os.path.join(RESULTS, "agentic_vs_naive_chart.png"), dpi=150, bbox_inches="tight")
plt.close()
print("✅ agentic_vs_naive_chart.png")
