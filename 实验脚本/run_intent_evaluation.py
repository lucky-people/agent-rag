#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
意图分类与路由机制量化评估脚本
================================
评估BERT意图分类器在租房场景下的分类效果：
  - 类别: 通用知识 / 专业咨询
  - 指标: 准确率(Accuracy)、精确率(Precision)、召回率(Recall)、F1
  - 输出: 混淆矩阵、分类报告、误分类案例分析

使用方法：
  cd 实验脚本
  python run_intent_evaluation.py

输出：
  results/intent_evaluation_report.txt   - 完整评估报告
  results/intent_confusion_matrix.png    - 混淆矩阵图
  results/intent_misclassified.csv        - 误分类案例明细
"""

import os
import sys
import json
import warnings
warnings.filterwarnings("ignore")

# ==================== 路径配置 ====================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
LEGAL_QA_DIR = os.path.join(PROJECT_ROOT, "Agent", "legal_qa")
# 把项目根目录加入 sys.path，保证 Agent.legal_qa.* 绝对导入可用
sys.path.insert(0, PROJECT_ROOT)

DATA_FILE = os.path.join(SCRIPT_DIR, "data", "intent_test_data.jsonl")
RESULTS_DIR = os.path.join(SCRIPT_DIR, "results")
os.makedirs(RESULTS_DIR, exist_ok=True)

# ==================== 加载测试数据 ====================
print("📋 加载意图分类测试集...")
test_data = []
with open(DATA_FILE, "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line:
            test_data.append(json.loads(line))

print(f"  共 {len(test_data)} 条测试数据")
label_counts = {}
for item in test_data:
    label_counts[item["label"]] = label_counts.get(item["label"], 0) + 1
for label, cnt in label_counts.items():
    print(f"    - {label}: {cnt} 条")

# ==================== 加载分类器 ====================
print("\n🔧 加载BERT意图分类器...")
from Agent.legal_qa.rag_qa.core.query_classifier import QueryClassifier

classifier_path = os.path.join(LEGAL_QA_DIR, "rag_qa", "models", "bert_query_classifier")
classifier = QueryClassifier(classifier_path)
print("  ✅ 分类器加载完成")

# 规则前置兜底关键词（与query_classifier.py中保持一致）
RULE_KEYWORDS = ['注意事项', '租客权益', '权益', '押金', '退租', '租房前',
                 '租房知识', '租房注意事项', '提前退租', '不退押金', '怎么退押金']

# ==================== 执行预测 ====================
print("\n🚀 开始预测...")
y_true = []
y_pred = []
misclassified = []
rule_hits = []

for i, item in enumerate(test_data):
    query = item["query"]
    true_label = item["label"]

    # 检测是否命中规则前置兜底
    hit_rule = any(kw in query for kw in RULE_KEYWORDS)

    # 预测
    pred_label = classifier.predict_category(query)

    y_true.append(true_label)
    y_pred.append(pred_label)

    if hit_rule:
        rule_hits.append({"query": query, "true_label": true_label, "pred_label": pred_label})

    if pred_label != true_label:
        misclassified.append({
            "id": i + 1,
            "query": query,
            "true_label": true_label,
            "pred_label": pred_label,
            "hit_rule": hit_rule
        })

    if (i + 1) % 10 == 0 or i == 0:
        status = "✅" if pred_label == true_label else "❌"
        print(f"  {status} [{i+1:2d}/{len(test_data)}] {query[:20]}... -> 预测:{pred_label} 真实:{true_label}")

# ==================== 计算评估指标 ====================
print("\n📊 计算评估指标...")

# 混淆矩阵
labels = ["通用知识", "专业咨询"]
confusion = {}
for t in labels:
    confusion[t] = {}
    for p in labels:
        confusion[t][p] = 0

for t, p in zip(y_true, y_pred):
    confusion[t][p] += 1

# 计算指标
def calc_metrics(confusion, target_label):
    """计算指定类别的精确率、召回率、F1"""
    tp = confusion[target_label][target_label]
    fp = sum(confusion[other][target_label] for other in labels if other != target_label)
    fn = sum(confusion[target_label][other] for other in labels if other != target_label)
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
    return precision, recall, f1, tp, fp, fn

accuracy = sum(1 for t, p in zip(y_true, y_pred) if t == p) / len(y_true)

metrics = {}
for label in labels:
    p, r, f1, tp, fp, fn = calc_metrics(confusion, label)
    metrics[label] = {"precision": p, "recall": r, "f1": f1, "tp": tp, "fp": fp, "fn": fn}

# 宏平均
macro_p = sum(m["precision"] for m in metrics.values()) / len(labels)
macro_r = sum(m["recall"] for m in metrics.values()) / len(labels)
macro_f1 = sum(m["f1"] for m in metrics.values()) / len(labels)

# 加权平均
total = len(y_true)
weighted_p = sum(metrics[label]["precision"] * label_counts.get(label, 0) for label in labels) / total
weighted_r = sum(metrics[label]["recall"] * label_counts.get(label, 0) for label in labels) / total
weighted_f1 = sum(metrics[label]["f1"] * label_counts.get(label, 0) for label in labels) / total

print(f"  准确率(Accuracy): {accuracy:.4f}")
for label in labels:
    m = metrics[label]
    print(f"  {label}: Precision={m['precision']:.4f} Recall={m['recall']:.4f} F1={m['f1']:.4f}")
print(f"  宏平均: Precision={macro_p:.4f} Recall={macro_r:.4f} F1={macro_f1:.4f}")

# ==================== 保存报告 ====================
print("\n💾 保存评估报告...")

report_path = os.path.join(RESULTS_DIR, "intent_evaluation_report.txt")
with open(report_path, "w", encoding="utf-8") as f:
    f.write("=" * 60 + "\n")
    f.write("意图分类与路由机制 - 量化评估报告\n")
    f.write("=" * 60 + "\n\n")

    f.write("一、数据集概况\n")
    f.write("-" * 40 + "\n")
    f.write(f"  测试样本总数: {len(test_data)}\n")
    for label, cnt in label_counts.items():
        f.write(f"  {label}: {cnt} 条 ({cnt/len(test_data)*100:.1f}%)\n")
    f.write(f"  规则前置兜底命中: {len(rule_hits)} 条\n\n")

    f.write("二、整体指标\n")
    f.write("-" * 40 + "\n")
    f.write(f"  准确率(Accuracy): {accuracy:.4f} ({accuracy*100:.2f}%)\n")
    f.write(f"  宏平均 Precision: {macro_p:.4f}\n")
    f.write(f"  宏平均 Recall:    {macro_r:.4f}\n")
    f.write(f"  宏平均 F1:        {macro_f1:.4f}\n")
    f.write(f"  加权平均 F1:      {weighted_f1:.4f}\n\n")

    f.write("三、各类别详细指标\n")
    f.write("-" * 40 + "\n")
    f.write(f"  {'类别':<12} {'Precision':<12} {'Recall':<12} {'F1':<12} {'TP':<6} {'FP':<6} {'FN':<6}\n")
    for label in labels:
        m = metrics[label]
        f.write(f"  {label:<12} {m['precision']:<12.4f} {m['recall']:<12.4f} {m['f1']:<12.4f} "
                f"{m['tp']:<6} {m['fp']:<6} {m['fn']:<6}\n")
    f.write("\n")

    f.write("四、混淆矩阵\n")
    f.write("-" * 40 + "\n")
    f.write(f"  {'真实' + chr(92) + '预测':<14}")
    for p in labels:
        f.write(f"{p:<14}")
    f.write("\n")
    for t in labels:
        f.write(f"  {t:<14}")
        for p in labels:
            f.write(f"{confusion[t][p]:<14}")
        f.write("\n")
    f.write("\n")

    f.write("五、误分类案例分析\n")
    f.write("-" * 40 + "\n")
    f.write(f"  误分类总数: {len(misclassified)} 条 ({len(misclassified)/len(test_data)*100:.1f}%)\n\n")

    # 按错误类型分组
    false_positive = [m for m in misclassified if m["true_label"] == "通用知识" and m["pred_label"] == "专业咨询"]
    false_negative = [m for m in misclassified if m["true_label"] == "专业咨询" and m["pred_label"] == "通用知识"]

    f.write(f"  5.1 通用知识 → 专业咨询 (误报, {len(false_positive)}条):\n")
    for m in false_positive:
        rule_tag = " [规则命中]" if m["hit_rule"] else ""
        f.write(f"    - {m['query']}{rule_tag}\n")
    f.write("\n")

    f.write(f"  5.2 专业咨询 → 通用知识 (漏报, {len(false_negative)}条):\n")
    for m in false_negative:
        f.write(f"    - {m['query']}\n")
    f.write("\n")

    f.write("六、规则前置兜底分析\n")
    f.write("-" * 40 + "\n")
    f.write(f"  命中规则关键词的样本数: {len(rule_hits)}\n")
    rule_correct = sum(1 for r in rule_hits if r["pred_label"] == r["true_label"])
    f.write(f"  规则命中后分类正确: {rule_correct}/{len(rule_hits)} ({rule_correct/len(rule_hits)*100:.1f}%)\n")
    if rule_hits:
        f.write("  规则命中样本明细:\n")
        for r in rule_hits:
            status = "✅" if r["pred_label"] == r["true_label"] else "❌"
            f.write(f"    {status} {r['query']} (真实:{r['true_label']}, 预测:{r['pred_label']})\n")
    f.write("\n")

    f.write("七、优化建议\n")
    f.write("-" * 40 + "\n")
    if false_positive:
        f.write("  1. 误报问题（通用知识被分为专业咨询）:\n")
        f.write("     - 检查规则前置兜底关键词是否过于宽泛\n")
        f.write("     - 考虑增加'通用知识'类别的训练样本，特别是包含'租房''押金'等关键词的闲聊类问题\n")
    if false_negative:
        f.write("  2. 漏报问题（专业咨询被分为通用知识）:\n")
        f.write("     - 增加专业咨询类别的训练样本多样性\n")
        f.write("     - 考虑对法律术语关键词增加规则前置兜底\n")
    f.write("  3. 模型优化方向:\n")
    f.write("     - 增加训练数据量（当前测试集60条，建议训练集不少于500条）\n")
    f.write("     - 尝试领域继续预训练（Domain-adaptive Pre-training）\n")
    f.write("     - 调整分类阈值，平衡精确率和召回率\n")

print(f"  ✅ 评估报告: {report_path}")

# 保存误分类CSV
import csv
mis_path = os.path.join(RESULTS_DIR, "intent_misclassified.csv")
with open(mis_path, "w", encoding="utf-8-sig", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["序号", "问题", "真实标签", "预测标签", "是否命中规则", "错误类型"])
    for m in misclassified:
        error_type = "误报(通用→专业)" if m["true_label"] == "通用知识" else "漏报(专业→通用)"
        writer.writerow([m["id"], m["query"], m["true_label"], m["pred_label"],
                         "是" if m["hit_rule"] else "否", error_type])
print(f"  ✅ 误分类明细: {mis_path}")

# ==================== 生成混淆矩阵图 ====================
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    # 混淆矩阵热力图
    cm_matrix = np.array([[confusion[t][p] for p in labels] for t in labels])
    im = axes[0].imshow(cm_matrix, cmap="Blues", aspect="auto")
    axes[0].set_xticks(range(len(labels)))
    axes[0].set_yticks(range(len(labels)))
    axes[0].set_xticklabels(labels, fontsize=12)
    axes[0].set_yticklabels(labels, fontsize=12)
    axes[0].set_xlabel("预测标签", fontsize=13)
    axes[0].set_ylabel("真实标签", fontsize=13)
    axes[0].set_title("混淆矩阵", fontsize=14, fontweight="bold")
    for i in range(len(labels)):
        for j in range(len(labels)):
            color = "white" if cm_matrix[i, j] > cm_matrix.max() / 2 else "black"
            axes[0].text(j, i, str(cm_matrix[i, j]), ha="center", va="center",
                         color=color, fontsize=16, fontweight="bold")
    plt.colorbar(im, ax=axes[0])

    # 指标对比柱状图
    x = np.arange(len(labels))
    width = 0.25
    precisions = [metrics[label]["precision"] for label in labels]
    recalls = [metrics[label]["recall"] for label in labels]
    f1s = [metrics[label]["f1"] for label in labels]

    axes[1].bar(x - width, precisions, width, label="Precision", color="#42a5f5")
    axes[1].bar(x, recalls, width, label="Recall", color="#66bb6a")
    axes[1].bar(x + width, f1s, width, label="F1", color="#ff7043")
    axes[1].set_xlabel("类别", fontsize=13)
    axes[1].set_ylabel("分数", fontsize=13)
    axes[1].set_title(f"各类别指标对比 (Accuracy={accuracy:.3f})", fontsize=14, fontweight="bold")
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(labels, fontsize=12)
    axes[1].legend(fontsize=11)
    axes[1].set_ylim(0, 1.1)
    for i, (p, r, f) in enumerate(zip(precisions, recalls, f1s)):
        axes[1].text(i - width, p + 0.02, f"{p:.2f}", ha="center", fontsize=9)
        axes[1].text(i, r + 0.02, f"{r:.2f}", ha="center", fontsize=9)
        axes[1].text(i + width, f + 0.02, f"{f:.2f}", ha="center", fontsize=9)

    plt.suptitle("意图分类与路由机制 - 量化评估", fontsize=16, fontweight="bold", y=1.02)
    plt.tight_layout()
    chart_path = os.path.join(RESULTS_DIR, "intent_confusion_matrix.png")
    plt.savefig(chart_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  ✅ 混淆矩阵图: {chart_path}")
except Exception as e:
    print(f"  ⚠️  图表生成失败（不影响评估结果）: {e}")

# ==================== 完成 ====================
print("\n" + "=" * 60)
print(f"🎉 评估完成！准确率: {accuracy*100:.2f}%, 误分类: {len(misclassified)} 条")
print(f"   结果已保存到 {RESULTS_DIR}/ 目录")
print("=" * 60)
