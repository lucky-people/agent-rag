# 评估回归门（Evaluation Gate）使用说明

> **一句话**：一条命令验证"检索 + 生成质量是否退化"，指标回退超阈值即失败（exit 1）。
> 对应 README「实验六」的**持续化**——评估从一次性实验升级为质量门。

## 为什么需要它

RAG 系统的质量退化是**静默**的：代码编译通过、单测全绿，但检索重排一改、提示词一动，
引用真实率可能从 0.913 悄悄掉到 0.80，没有任何报错。传统 CI 测不出这种退化——**评估回归门
就是 RAG 系统的"质量测试"**。

## 本地使用（日常开发 / 提交前）

```bash
# 前提: Docker 中间件已启动 (docker compose up -d), config_local/keys.py 已配好
python 实验脚本/eval_gate.py                    # 8题×3策略×1轮, 确定性审计
python 实验脚本/eval_gate.py --rounds 3         # 3 轮取均值 (复现 v3 口径)
python 实验脚本/eval_gate.py --ragas            # 额外跑 RAGAS 打分 (慢, 需 API)
python 实验脚本/eval_gate.py --questions Q1,Q6  # 只跑子集 (快速自检)
python 实验脚本/eval_gate.py --tol 0.08         # 放宽容差
python 实验脚本/eval_gate.py --save-baseline    # 通过后提升黄金基线 (需 --rounds 3)
```

**输出**：
- 控制台：逐题审计明细 + 基线对比表 + `✅ PASS` / `❌ FAIL`
- 报告：`实验脚本/results/eval_report_<时间戳>.json`（本轮指标 + 基线 + 失败项，可上传/审计）

**判定规则**：任一策略的「引用真实率」或「RAGAS 忠实度」低于 **基线 - 容差(默认 0.05)** → FAIL。

**基线来源**：`实验脚本/results/hallucination_audit_v5.csv`（引用真实率）+ `ragas_scores_v3.csv`
（RAGAS 忠实度）——即条款级重排修复后的**黄金基线**（D 0.913 / 0.595）。`--save-baseline`
用更高分结果提升基线，支持"基线随项目演进"。

## CI 集成（GitHub Actions）

`.github/workflows/eval-ci.yml`：
- **触发**：手动（workflow_dispatch）+ 每周一 02:00（schedule）
- **环境**：Docker service containers 自动起 MySQL / Redis / Milvus；模型走 HuggingFace 自动下载
  （`vector_store.py` 已支持 `RAG_MODEL_ROOT` 环境变量 + HF 兜底）
- **流程**：导入 Schema/种子数据 → 法律知识入库（BM25 语料 + Milvus 向量）→ 跑评估门 → 上传报告

### ⚠️ Gitee 边界（重要）

**Gitee 不执行 GitHub Actions**。`.github/workflows/eval-ci.yml` 在以下场景生效：
1. 仓库**镜像到 GitHub**（推荐：GitHub Actions 免费额度足够每周跑一次）；
2. 本地/服务器手动跑 `eval_gate.py`（最常用路径，一条命令）；
3. 未来接 Gitee Go 流水线（迁移 5 个 step 即可）。

面试话术：「评估门本地一条命令可跑、CI 配置就绪（镜像 GitHub 后自动每周回归），
指标回退超阈值拦截合并——评估不是一次性实验，是持续质量保障。」

## 扩展

- **全量 RAGAS 回归**：CI 里 `--ragas` 全量约 40 分钟 + API 费用，建议作为每周任务；push 触发只跑确定性审计（快、零 API 额外费用）。
- **数据集扩展**：`QUESTIONS` 8 题可从 `实验脚本/data/rag_test_questions.json` 扩充，基线同步提升。
- **阈值治理**：`--tol` 是硬门槛；更细可对"每策略每指标"分别配阈值（改 `main()` 的对比段）。
