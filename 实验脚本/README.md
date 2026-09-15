# 毕业设计实验脚本 - 多智能体+RAG租房咨询系统

本目录包含毕业设计所需的两组核心实验，可直接运行并产出论文/PPT所需的图表和数据。

## 📁 目录结构

```
实验脚本/
├── README.md                          # 本说明文档
├── data/
│   ├── rag_test_questions.json        # RAG检索测试集（30道租房法律问题，带标注关键词）
│   └── intent_test_data.jsonl         # 意图分类测试集（60条，通用知识/专业咨询各30条）
├── results/                           # 实验结果输出目录（运行后自动生成）
│   ├── rag_ablation_results.csv       # RAG消融实验详细结果
│   ├── rag_ablation_summary.txt       # RAG消融实验汇总报告
│   ├── rag_ablation_chart.png         # RAG消融实验对比柱状图
│   ├── intent_evaluation_report.txt   # 意图分类评估完整报告
│   ├── intent_confusion_matrix.png    # 意图分类混淆矩阵图
│   └── intent_misclassified.csv       # 意图分类误分类案例明细
├── run_rag_ablation.py                # 实验一：RAG检索策略消融实验
└── run_intent_evaluation.py           # 实验二：意图分类与路由机制量化评估
```

---

## 🧪 实验一：RAG检索策略消融实验

### 实验目的
对比4种检索策略在租房法律问答场景下的检索效果，论证"混合检索+Reranker"方案的优越性。

### 4种对比策略

| 策略 | 名称 | 说明 |
|---|---|---|
| A | 纯BM25 | 基于MySQL常见问题库的关键词检索（传统方案基线） |
| B | 纯稠密向量 | BGE-M3稠密向量语义检索 |
| C | 混合检索（无Rerank） | 稠密向量+稀疏向量加权融合（权重1.0:0.7） |
| D | 混合检索+Reranker | 混合检索后经BGE Reranker重排序（系统当前方案） |

### 评估指标
- **Recall@5**：前5条检索结果中命中相关文档的问题占比
- **MRR**（Mean Reciprocal Rank）：第一个相关文档出现位置的倒数的均值
- **平均检索耗时**：单条查询的平均检索时间（ms）

### 相关度判定标准
检索结果文档内容包含至少2个标注关键词即视为相关。

### 运行方法

```bash
cd 实验脚本
python run_rag_ablation.py
```

### 预期产出
- `results/rag_ablation_results.csv`：30道题 × 4种策略的详细结果
- `results/rag_ablation_summary.txt`：汇总指标 + 结论分析
- `results/rag_ablation_chart.png`：Recall@5 / MRR / 耗时 三联柱状图

### 论文/PPT使用建议
- 在"系统设计"章节说明4种策略的技术原理
- 在"实验与分析"章节展示对比柱状图和数据表格
- 核心论点：**混合检索+Reranker在Recall@5和MRR上均显著优于纯BM25和纯向量检索，证明了多策略融合的有效性**

---

## 🧪 实验二：意图分类与路由机制量化评估

### 实验目的
评估BERT意图分类器在租房场景下的分类效果，分析误分类案例并提出优化方向。

### 分类类别
- **通用知识**：不需要检索法律文档，LLM可直接回答（如"你好"、"郑州哪个区租房便宜"）
- **专业咨询**：需要检索法律文档的专业问题（如"房东不退押金怎么办"）

### 评估指标
- **准确率（Accuracy）**：整体分类正确的比例
- **精确率（Precision）**：各类别预测正确的比例
- **召回率（Recall）**：各类别被正确识别的比例
- **F1分数**：精确率和召回率的调和平均
- **混淆矩阵**：展示预测标签与真实标签的匹配情况

### 特殊分析
- **规则前置兜底分析**：系统对"押金""退租"等关键词强制走专业咨询，评估该规则的命中率和准确率
- **误分类案例分析**：按"误报（通用→专业）"和"漏报（专业→通用）"分组展示

### 运行方法

```bash
cd 实验脚本
python run_intent_evaluation.py
```

### 预期产出
- `results/intent_evaluation_report.txt`：完整评估报告（7个章节）
- `results/intent_confusion_matrix.png`：混淆矩阵热力图 + 各类别指标对比图
- `results/intent_misclassified.csv`：误分类案例明细（含错误类型、是否命中规则）

### 论文/PPT使用建议
- 在"系统设计"章节说明意图分类的架构（BERT二分类 + 规则前置兜底）
- 在"实验与分析"章节展示混淆矩阵和分类报告
- 核心论点：**意图分类器在租房场景下达到较高准确率，规则前置兜底有效提升了专业咨询的召回率，同时分析了误分类案例并提出了数据增强和领域预训练的优化方向**

---

## 📊 数据集说明

### RAG检索测试集 (`data/rag_test_questions.json`)
- 共30道租房法律问题，覆盖10个类别
- 每道题包含：问题ID、类别、问题文本、相关关键词（5个）、难度
- 类别分布：押金退还(5)、合同签订(4)、提前退租(4)、维修责任(3)、房东卖房(3)、租金上涨(2)、转租(2)、违约责任(3)、居住安全(2)、中介费(2)

### 意图分类测试集 (`data/intent_test_data.jsonl`)
- 共60条标注数据，JSONL格式（每行一个JSON对象）
- 通用知识30条 + 专业咨询30条，类别均衡
- 通用知识涵盖：问候、天气、租房常识、区域咨询、价格咨询等
- 专业咨询涵盖：押金、合同、退租、维修、转租、违约等法律问题

---

## ⚙️ 环境依赖

实验脚本依赖项目已有的Python环境，需要以下库（项目环境中应已安装）：

```
torch
transformers
pymilvus
rank_bm25
numpy
mysql-connector-python
redis
matplotlib
scikit-learn
openai
```

如果缺少matplotlib，可通过 `pip install matplotlib` 安装（仅用于生成图表，不影响实验数据）。

---

## 📝 注意事项

1. **运行前确保后端服务已启动**：RAG实验需要连接Milvus向量库、MySQL、Redis，请先启动项目后端
2. **首次运行较慢**：BERT分类器和BGE嵌入模型首次加载需要时间，后续运行会缓存
3. **结果可复现**：测试集固定，模型固定，每次运行结果应一致（检索耗时可能有轻微波动）
4. **可扩展测试集**：如需更多数据，可在`data/`目录下的JSON/JSONL文件中追加条目，格式保持一致即可
