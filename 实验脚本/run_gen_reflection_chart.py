# -*- coding: utf-8 -*-
"""
反思纠错案例图 v2（三面板独立布局）
  1. 6 题路由与反思状态（柱状图）
  2. 触发题纠错增益（反思前 vs 反思后，双点箭头图）
  3. Q1 典型案例反思纠错流程（流程框图）
"""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False

RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")

fig, axes = plt.subplots(1, 3, figsize=(19, 5.6), gridspec_kw={"width_ratios": [1, 1.05, 1.25]})

# ============ 图1: 路由与反思状态 ============
ax = axes[0]
labels = ["MySQL FAQ\n直答 (3ms)", "RAG 直接通过\n(自检 supported)", "RAG 反思纠错\n(自检拦截+重检)"]
values = [1, 3, 2]
colors = ["#52C41A", "#1890FF", "#722ED1"]
bars = ax.bar(labels, values, color=colors, width=0.52)
for b, v in zip(bars, values):
    ax.text(b.get_x() + b.get_width() / 2, v + 0.08, str(v), ha="center", fontsize=15, fontweight="bold")
ax.set_ylim(0, 4.5)
ax.set_ylabel("题数（共 6 题）", fontsize=11)
ax.set_title("6 题路由与反思状态\n多级路由 3ms 直答 · RAG 自检拦截 2 例证据不足", fontsize=12, fontweight="bold")
ax.grid(axis="y", alpha=0.3, linestyle="--")

# ============ 图2: 纠错增益 ============
ax = axes[1]
names = ["Q1 押金利息\n完整性", "Q1 押金利息\n引用准确", "Q5 装修抵租\n完整性", "Q5 装修抵租\n引用准确"]
before = [4, 3, 4, 4]
after = [5, 5, 5, 5]
x = np.arange(4)
w = 0.32
b1 = ax.bar(x - w / 2, before, w, label="反思前（首轮）", color="#FA8C16")
b2 = ax.bar(x + w / 2, after, w, label="反思后（最终）", color="#722ED1")
for i in range(4):
    ax.text(x[i] - w / 2, before[i] + 0.06, str(before[i]), ha="center", fontsize=10, fontweight="bold")
    ax.text(x[i] + w / 2, after[i] + 0.06, str(after[i]), ha="center", fontsize=10, fontweight="bold")
    ax.annotate("", xy=(x[i] + w / 2 - 0.1, after[i]), xytext=(x[i] - w / 2 + 0.1, before[i]),
                arrowprops=dict(arrowstyle="->", color="#333", lw=1.4))
    ax.text(x[i], min(before[i], after[i]) - 0.55, f"+{after[i]-before[i]}", ha="center",
            fontsize=11, color="#333", fontweight="bold")
ax.set_xticks(x)
ax.set_xticklabels(names, fontsize=9.5)
ax.set_ylim(0, 6)
ax.set_ylabel("LLM 评判得分 (0-5)", fontsize=11)
ax.set_title("反思纠错增益（仅触发反思的 2 题）\n证据补全 → 完整性/引用准确性提升", fontsize=12, fontweight="bold")
ax.legend(fontsize=9)
ax.grid(axis="y", alpha=0.3, linestyle="--")

# ============ 图3: Q1 典型案例流程 ============
ax = axes[2]
ax.axis("off")
ax.set_xlim(0, 10)
ax.set_ylim(0, 10)
ax.set_title("典型案例 Q1：房东拖延退押金能否要利息赔偿\nSelf-RAG 反思循环纠错过程", fontsize=12, fontweight="bold", pad=10)

def box(x, y, w, h, text, fc, ec, fs=8.6, bold=False):
    ax.add_patch(mpatches.FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.08",
                 fc=fc, ec=ec, lw=1.4))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs,
            fontweight="bold" if bold else "normal", linespacing=1.45)

def arrow(x1, y1, x2, y2):
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle="->", color="#555", lw=1.7))

box(0.2, 7.1, 3.0, 2.3, "① 检索规划\n3 个检索词\n(押金/利息/逾期责任)", "#E6F4FF", "#1890FF")
arrow(3.2, 8.25, 3.9, 8.25)
box(3.9, 7.1, 2.6, 2.3, "② 首轮生成\n结论可回答\n依据不足", "#FFF7E6", "#FA8C16")
arrow(6.5, 8.25, 7.2, 8.25)
box(7.2, 7.1, 2.6, 2.3, "③ Self-RAG 反思\nsupported=false\n证据未提及利息赔偿", "#FFF1F0", "#F5222D", 8.4)

arrow(8.5, 7.1, 8.5, 5.9)
box(6.5, 4.7, 3.0, 1.2, "④ 改写检索词\n民法典 押金 逾期返还 利息损失", "#F6FFED", "#52C41A", 8.6)

arrow(7.9, 4.7, 7.2, 3.8)
box(7.2, 1.5, 2.6, 2.3, "⑥ 最终答案\n引用《民法典》584条\n引用准确性 3→5", "#F6FFED", "#52C41A", 8.6)
arrow(7.2, 2.65, 5.8, 2.65)
box(3.1, 1.5, 2.7, 2.3, "⑤ 重检命中\n资金占用损失\n赔偿依据", "#E6F4FF", "#1890FF")

ax.text(5, 0.8, "自检拦截 → 改写补证据 → 重检后引用准确（3→5）",
        ha="center", fontsize=9.5, color="#333", fontweight="bold")

plt.suptitle("Agentic RAG 反思纠错案例实验（Self-RAG：自检 → 改写 → 重检）", fontsize=14, fontweight="bold", y=0.99)
plt.tight_layout(rect=[0, 0, 1, 0.93])
plt.savefig(os.path.join(RESULTS, "reflection_cases_chart.png"), dpi=150, bbox_inches="tight")
plt.close()
print("✅ reflection_cases_chart.png（三面板）")
