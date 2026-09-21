# 毕业设计scripts - 多智能体+RAG租房咨询系统

本目录包含毕业设计所需的评估实验，可直接运行并产出论文/PPT/面试展示所需的图表和数据。

## 📁 目录结构

```
scripts/
├── README.md                          # 本说明文档
├── data/
│   ├── rag_test_questions.json        # RAG 检索测试集（30道租房法律问题，带标注关键词）
│   ├── intent_train_data.jsonl        # 意图分类训练集（BERT 微调）
│   └── intent_test_data.jsonl         # 意图分类测试集（60条，通用知识/专业咨询各30条）
├── results/                           # 实验结果输出目录（关键图表已入库）
│   ├── intent_confusion_matrix.png    # 意图分类混淆矩阵 + 类别 P/R/F1
│   ├── e2e_v2_chart.png               # 【核心】混合+Rerank 选型价值三层证据图
│   ├── ablation_gpu_chart.png         # GPU 实测耗时 + 生产路径标注
│   ├── chain_latency_chart.png        # MySQL/Redis/RAG 三链路延迟对比
│   ├── rag_ablation_results.csv       # RAG 消融原始数据（Recall@5/MRR/耗时）
│   └── e2e_retrieval_scores.csv 等    # v2 评估明细（检索质量/答案质量/生产配置）
├── run_intent_evaluation.py           # 实验一：意图分类与路由机制量化评估
├── run_e2e_quality_v2.py              # 实验二：混合+Rerank 选型价值评估（三层证据）★核心
├── run_agentic_vs_naive.py            # 实验三：Agentic vs 朴素端到端对比
├── run_rag_ablation.py                # 补充实验：RAG 检索策略消融（仅出数据，不出图）
├── run_gen_charts_v3.py               # 生成 e2e_v2_chart.png
└── generate_intent_train_data.py      # 生成意图分类训练数据
```

---

## 🧪 实验一：意图分类与路由机制量化评估

### 实验目的
评估 BERT 意图分类器在租房场景下的分类效果，分析误分类案例并提出优化方向。

### 分类类别
- **通用知识**：不需要检索法律文档，LLM 可直接回答（如"你好"、"郑州哪个区租房便宜"）
- **专业咨询**：需要检索法律文档的专业问题（如"房东不退押金怎么办"）

### 评估指标
准确率 / 精确率 / 召回率 / F1 / 混淆矩阵（实测 Accuracy=98.3%，仅 1 条误分）。

### 运行方法

```bash
python run_intent_evaluation.py
```

### 预期产出
- `results/intent_evaluation_report.txt`：完整评估报告
- `results/intent_confusion_matrix.png`：混淆矩阵 + 类别指标
- `results/intent_misclassified.csv`：误分类案例明细

---

## 🧪 实验二：混合检索 + Rerank 选型价值评估（三层证据）★核心

> 对应 README「实验二」。针对"为什么需要混合检索 + Rerank"这一核心选型问题，
> 设计三层评估，每层均由 LLM 独立评判（0-5 分），评判时**可见对应检索上下文**，GPU 实测。

| 证据层 | 结论 |
|---|---|
| 检索质量直接评判 | D 相关性 4.00 vs C 2.75（+45%）vs B 2.12——Rerank 让进 LLM 的文档最相关 |
| 生产配置 Top-2（CANDIDATE_M=2） | D 综合 2.33 vs C 1.50（+55%）——排序质量直接决定答案质量 |
| 答案质量（Top-5 可见上下文） | D 引用准确率 2.19 全场最高 |

> **方法论要点**：最初用 Recall@5/MRR（词面命中口径）评估时，Rerank 反而更低——
> 这是"指标与待验证假设错位"的典型例子（Rerank 优化的是语义排序，词面口径测不到）。
> 修复评估方法（评判可见上下文 + 直接评检索质量 + 生产配置对比）后，选型价值稳定显现。

### 运行方法

```bash
python run_e2e_quality_v2.py    # 生成 e2e_retrieval_scores.csv / e2e_answer_quality_v2.csv / e2e_prod_top2_scores.csv
python run_gen_charts_v3.py     # 生成 results/e2e_v2_chart.png
```

---

## 🧪 实验三：Agentic RAG vs 朴素 RAG 端到端对比

同一批 6 道题（含困难样本），对比朴素 RAG（固定 pipeline）与 Agentic RAG（检索规划 + 反思循环 + 查询改写）。

实测：朴素 6.9s / Agentic 71.2s（含反思+重检索，CPU 推理），成功率均 100%，Agentic 平均反思 1.3 轮、答案更长（376 vs 347 字）。

> **设计权衡**：反思循环的价值不在于"总是更好"，而在于**首轮证据不足时自我修正**。
> 生产实践采用混合策略：普通问题走朴素 RAG，仅当自检不通过才升级反思重检。

### 运行方法

```bash
python run_agentic_vs_naive.py
```

---

## 🧪 补充实验：RAG 检索策略消融（仅出数据）

4 策略（纯 BM25 / 纯稠密 / 混合无 Rerank / 混合+Rerank）在 30 道题上的 Recall@5 / MRR / 耗时。

> **注意**：该实验使用**词面命中（≥2 个标注关键词）**判定相关性，与 Rerank 的语义排序目标不对齐，
> 因此 Rerank 的 MRR 反而偏低——这是评估方法论的教材级案例，不作为选型依据。
> 选型价值以实验二（v2 三层证据）为准。脚本仅输出 CSV 数据，不生成对比图。

```bash
python run_rag_ablation.py
```

---

## ⚙️ 环境依赖

```
torch  transformers  pymilvus  rank_bm25  numpy
mysql-connector-python  redis  matplotlib  scikit-learn  openai
```

## 📝 注意事项

1. **运行前确保后端服务已启动**：RAG 实验需要 Milvus（db_name=`laws_all`）、MySQL、Redis
2. **GPU 加速**：设 `CUDA_VISIBLE_DEVICES=0` 并使用 GPU 版模型（详见 README 实验三）
3. **清理缓存**：评估/对比脚本运行前需清 Redis `rag_answer:*` 缓存键，避免污染结果
4. **结果展示**：`results/` 内已内置关键结果图，可直接用于论文/PPT/面试展示
