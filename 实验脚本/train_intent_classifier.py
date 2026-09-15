#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
意图分类器训练启动脚本
完整流程：删除旧模型 -> 加载800条训练数据 -> 训练BERT模型 -> 保存 -> 用测试集验证
使用方法：
    python train_intent_classifier.py
"""
import os
import sys
import shutil
import json

# ============================================================
# 路径配置
# ============================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
LEGAL_QA_DIR = os.path.join(PROJECT_ROOT, "Agent", "legal_qa")
MODEL_DIR = os.path.join(LEGAL_QA_DIR, "rag_qa", "models", "bert_query_classifier")
TRAIN_DATA = os.path.join(SCRIPT_DIR, "data", "intent_train_data.jsonl")
TEST_DATA = os.path.join(SCRIPT_DIR, "data", "intent_test_data.jsonl")

# 把项目根目录加入 sys.path，保证 Agent.legal_qa.* 绝对导入可用
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

print("=" * 60)
print("  意图分类器训练启动脚本")
print("=" * 60)
print(f"  项目根目录: {PROJECT_ROOT}")
print(f"  模型保存路径: {MODEL_DIR}")
print(f"  训练数据: {TRAIN_DATA}")
print(f"  测试数据: {TEST_DATA}")
print("=" * 60)

# ============================================================
# 步骤1：删除旧模型
# ============================================================
print("\n[步骤1] 删除旧模型...")
if os.path.exists(MODEL_DIR):
    shutil.rmtree(MODEL_DIR)
    print(f"  ✅ 已删除旧模型目录: {MODEL_DIR}")
else:
    print(f"  ⏭️  旧模型目录不存在，跳过删除")

# ============================================================
# 步骤2：加载训练数据
# ============================================================
print("\n[步骤2] 加载训练数据...")
if not os.path.exists(TRAIN_DATA):
    print(f"  ❌ 训练数据文件不存在: {TRAIN_DATA}")
    print("  请先运行 generate_intent_train_data.py 生成训练数据")
    sys.exit(1)

with open(TRAIN_DATA, "r", encoding="utf-8") as f:
    train_data = [json.loads(line) for line in f if line.strip()]

gen_count = sum(1 for d in train_data if d["label"] == "通用知识")
pro_count = sum(1 for d in train_data if d["label"] == "专业咨询")
print(f"  ✅ 共加载 {len(train_data)} 条训练数据")
print(f"     - 通用知识: {gen_count} 条")
print(f"     - 专业咨询: {pro_count} 条")
print(f"     - 类别比例: 1:{pro_count/gen_count:.2f}")

# ============================================================
# 步骤3：训练模型
# ============================================================
print("\n[步骤3] 开始训练 BERT 模型...")
print("  （首次训练会加载 bert-base-chinese 预训练模型，请耐心等待）")
print()

from Agent.legal_qa.rag_qa.core.query_classifier import QueryClassifier

# 实例化分类器（此时模型目录已删除，会初始化新模型）
classifier = QueryClassifier(model_path=MODEL_DIR)

# 训练模型
classifier.train_model(data_file=TRAIN_DATA)

print("\n  ✅ 模型训练完成并保存")

# ============================================================
# 步骤4：用测试集验证
# ============================================================
print("\n[步骤4] 用测试集验证模型效果...")
if not os.path.exists(TEST_DATA):
    print(f"  ⚠️  测试数据文件不存在: {TEST_DATA}")
    print("  跳过测试集验证，可手动运行 run_intent_evaluation.py 评估")
else:
    with open(TEST_DATA, "r", encoding="utf-8") as f:
        test_data = [json.loads(line) for line in f if line.strip()]

    correct = 0
    total = len(test_data)
    misclassified = []

    for item in test_data:
        query = item["query"]
        true_label = item["label"]
        pred_label = classifier.predict_category(query)
        if pred_label == true_label:
            correct += 1
        else:
            misclassified.append((query, true_label, pred_label))

    accuracy = correct / total if total > 0 else 0
    print(f"  测试集大小: {total} 条")
    print(f"  预测正确: {correct} 条")
    print(f"  预测错误: {len(misclassified)} 条")
    print(f"  准确率: {accuracy:.2%}")

    if misclassified:
        print(f"\n  误分类案例（前10条）:")
        for q, true, pred in misclassified[:10]:
            print(f"    ❌ '{q}' -> 预测:{pred} 真实:{true}")

# ============================================================
# 步骤5：示例预测
# ============================================================
print("\n[步骤5] 示例预测:")
test_queries = [
    ("你好", "通用知识"),
    ("租房一般多少钱一个月", "通用知识"),
    ("合租好还是整租好", "通用知识"),
    ("物业费一般谁交", "通用知识"),
    ("郑州哪个区租房便宜", "通用知识"),
    ("房东不退押金怎么办", "专业咨询"),
    ("提前退租押金能要回来吗", "专业咨询"),
    ("租客有优先购买权吗", "专业咨询"),
    ("合同没到期房东要收房怎么办", "专业咨询"),
    ("中介隐瞒房屋情况能退中介费吗", "专业咨询"),
]
for q, expected in test_queries:
    pred = classifier.predict_category(q)
    mark = "✅" if pred == expected else "❌"
    print(f"  {mark} '{q}' -> {pred} (预期:{expected})")

print("\n" + "=" * 60)
print("  🎉 训练完成！")
print(f"  模型已保存至: {MODEL_DIR}")
print("  可运行 run_intent_evaluation.py 进行完整评估")
print("=" * 60)
