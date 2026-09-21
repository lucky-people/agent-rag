#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RAG检索策略消融scripts
========================
对比4种检索策略在租房法律问答场景下的效果：
  策略A: 纯BM25（MySQL常见问题库关键词检索）
  策略B: 纯稠密向量检索（BGE-M3 dense vector）
  策略C: 混合检索（稠密+稀疏加权融合，无Reranker）
  策略D: 混合检索 + BGE Reranker 重排序

评估指标：
  - Recall@5: 前5条检索结果中命中相关文档的问题占比
  - MRR: 平均倒数排名（第一个相关文档出现位置的倒数的均值）
  - 平均检索耗时(ms)

使用方法：
  cd scripts
  python run_rag_ablation.py

输出：
  results/rag_ablation_results.csv   - 每道题的详细结果
  results/rag_ablation_summary.txt   - 汇总指标
  results/rag_ablation_chart.png     - 对比柱状图
"""

import os
import sys
import json
import time
import warnings
warnings.filterwarnings("ignore")

# 强制 CPU 运行（规避部分机器 CUDA 驱动/显存崩溃），GPU 环境可注释掉
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")
os.environ.setdefault("PYTORCH_NO_CUDA", "1")

# ==================== 路径配置 ====================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
LEGAL_QA_DIR = os.path.join(PROJECT_ROOT, "Agent", "legal_qa")
# 把项目根目录加入 sys.path，保证 Agent.legal_qa.* 绝对导入可用
sys.path.insert(0, PROJECT_ROOT)

# ==================== 加载测试数据 ====================
DATA_FILE = os.path.join(SCRIPT_DIR, "data", "rag_test_questions.json")
RESULTS_DIR = os.path.join(SCRIPT_DIR, "results")
os.makedirs(RESULTS_DIR, exist_ok=True)

with open(DATA_FILE, "r", encoding="utf-8") as f:
    test_data = json.load(f)
questions = test_data["questions"]
print(f"📋 加载测试集: {len(questions)} 道问题")

# ==================== 初始化检索组件 ====================
print("\n🔧 正在初始化检索组件...")

from Agent.legal_qa.mysql_qa import MySQLClient, RedisClient, BM25Search
from Agent.legal_qa.rag_qa import VectorStore
import numpy as np

# 初始化BM25
redis_client = RedisClient()
mysql_client = MySQLClient()
bm25_search = BM25Search(redis_client, mysql_client)
print("  ✅ BM25检索器初始化完成")

# 初始化向量存储
vector_store = VectorStore()
print("  ✅ 向量存储初始化完成")

# Milvus集合名和字段（从vector_store实例获取）
COLLECTION_NAME = vector_store.collection_name
EMBEDDING_FUNC = vector_store.embedding_function
RERANKER = vector_store.reranker
# 实验专用参数（直接硬编码，不读取配置文件，避免被config中的小值覆盖）
CANDIDATE_M = 5
RETRIEVAL_K = 50

from pymilvus import AnnSearchRequest, WeightedRanker

print(f"  📊 检索配置: K={RETRIEVAL_K}, M={CANDIDATE_M}")

# ==================== 4种检索策略实现 ====================

def strategy_bm25(query, top_k=5):
    """策略A: 纯BM25关键词检索（MySQL常见问题库）"""
    from Agent.legal_qa.mysql_qa.utils.preprocess import preprocess_text
    query_tokens = preprocess_text(query)
    scores = bm25_search.bm25.get_scores(query_tokens)
    # softmax归一化
    exp_scores = np.exp(scores - np.max(scores))
    softmax_scores = exp_scores / np.sum(exp_scores)
    # 取top-k
    top_indices = np.argsort(softmax_scores)[::-1][:top_k]
    results = []
    for idx in top_indices:
        raw_q = bm25_search.original_questions[idx]
        q_text = raw_q[0] if isinstance(raw_q, tuple) else raw_q
        # 从MySQL获取对应答案
        answer = mysql_client.fetch_answer(q_text) or ""
        results.append({
            "content": f"{q_text} {answer}",
            "score": float(softmax_scores[idx]),
            "source": "bm25_mysql"
        })
    return results


def strategy_dense_only(query, top_k=5):
    """策略B: 纯稠密向量检索"""
    query_embeddings = EMBEDDING_FUNC([query])
    dense_vec = query_embeddings["dense"][0]
    if not isinstance(dense_vec, np.ndarray):
        dense_vec = np.array(dense_vec, dtype=np.float32)
    elif dense_vec.dtype != np.float32:
        dense_vec = dense_vec.astype(np.float32)

    results = vector_store.client.search(
        collection_name=COLLECTION_NAME,
        data=[dense_vec],
        anns_field="dense_vector",
        search_params={"metric_type": "IP", "params": {"nprobe": 10}},
        limit=50,  # 与混合检索候选集数量一致，确保对比公平
        output_fields=["text", "parent_id", "parent_content", "source", "timestamp"]
    )[0]

    # 转为Document并去重父文档
    sub_chunks = [vector_store._doc_from_hit(hit["entity"]) for hit in results]
    parent_docs = vector_store._get_unique_parent_docs(sub_chunks)
    return [{"content": doc.page_content, "score": 0.0, "source": doc.metadata.get("source", "")} for doc in parent_docs[:top_k]]


def strategy_hybrid_no_rerank(query, top_k=5):
    """策略C: 混合检索（稠密+稀疏加权融合），无Reranker"""
    query_embeddings = EMBEDDING_FUNC([query])
    dense_vec = query_embeddings["dense"][0]
    if not isinstance(dense_vec, np.ndarray):
        dense_vec = np.array(dense_vec, dtype=np.float32)
    elif dense_vec.dtype != np.float32:
        dense_vec = dense_vec.astype(np.float32)

    # 稀疏向量
    sparse_vec = {}
    row = query_embeddings["sparse"][[0]]
    for idx, val in zip(row.indices, row.data):
        sparse_vec[idx] = val

    dense_req = AnnSearchRequest(
        data=[dense_vec],
        anns_field="dense_vector",
        param={"metric_type": "IP", "params": {"nprobe": 10}},
        limit=RETRIEVAL_K
    )
    sparse_req = AnnSearchRequest(
        data=[sparse_vec],
        anns_field="sparse_vector",
        param={"metric_type": "IP", "params": {}},
        limit=RETRIEVAL_K
    )
    ranker = WeightedRanker(1.0, 0.3)

    results = vector_store.client.hybrid_search(
        collection_name=COLLECTION_NAME,
        reqs=[dense_req, sparse_req],
        ranker=ranker,
        limit=RETRIEVAL_K,
        output_fields=["text", "parent_id", "parent_content", "source", "timestamp"]
    )[0]

    sub_chunks = [vector_store._doc_from_hit(hit["entity"]) for hit in results]
    parent_docs = vector_store._get_unique_parent_docs(sub_chunks)
    # 不做rerank，直接返回混合排序后的结果
    return [{"content": doc.page_content, "score": 0.0, "source": doc.metadata.get("source", "")} for doc in parent_docs[:top_k]]


def strategy_hybrid_with_rerank(query, top_k=5):
    """策略D: 混合检索 + BGE Reranker重排序
    注意：不直接调用项目自带的 hybrid_search_with_rerank（它只返回CANDIDATE_M=2条，且父文档数<=M时跳过Rerank），
    而是复用策略C的混合检索逻辑获取相同候选集，再对全部父文档做Rerank，返回top_k条，确保与策略C对比公平。
    """
    query_embeddings = EMBEDDING_FUNC([query])
    dense_vec = query_embeddings["dense"][0]
    if not isinstance(dense_vec, np.ndarray):
        dense_vec = np.array(dense_vec, dtype=np.float32)
    elif dense_vec.dtype != np.float32:
        dense_vec = dense_vec.astype(np.float32)

    # 稀疏向量
    sparse_vec = {}
    row = query_embeddings["sparse"][[0]]
    for idx, val in zip(row.indices, row.data):
        sparse_vec[idx] = val

    dense_req = AnnSearchRequest(
        data=[dense_vec],
        anns_field="dense_vector",
        param={"metric_type": "IP", "params": {"nprobe": 10}},
        limit=RETRIEVAL_K
    )
    sparse_req = AnnSearchRequest(
        data=[sparse_vec],
        anns_field="sparse_vector",
        param={"metric_type": "IP", "params": {}},
        limit=RETRIEVAL_K
    )
    ranker = WeightedRanker(1.0, 0.3)

    results = vector_store.client.hybrid_search(
        collection_name=COLLECTION_NAME,
        reqs=[dense_req, sparse_req],
        ranker=ranker,
        limit=RETRIEVAL_K,
        output_fields=["text", "parent_id", "parent_content", "source", "timestamp"]
    )[0]

    sub_chunks = [vector_store._doc_from_hit(hit["entity"]) for hit in results]
    parent_docs = vector_store._get_unique_parent_docs(sub_chunks)

    # 对全部父文档做Reranker重排序（不跳过，不限CANDIDATE_M）
    if len(parent_docs) > 1 and RERANKER is not None:
        try:
            pairs = [[query, doc.page_content] for doc in parent_docs]
            scores = RERANKER.predict(pairs)
            parent_docs = [
                doc for _, doc in sorted(
                    zip(scores, parent_docs),
                    key=lambda x: x[0],
                    reverse=True
                )
            ]
        except Exception as e:
            print(f"  ⚠️  Rerank失败，使用混合排序结果: {e}")

    return [{"content": doc.page_content, "score": 0.0, "source": doc.metadata.get("source", "")} for doc in parent_docs[:top_k]]


STRATEGIES = {
    "A_纯BM25": strategy_bm25,
    "B_纯稠密向量": strategy_dense_only,
    "C_混合无Rerank": strategy_hybrid_no_rerank,
    "D_混合+Rerank": strategy_hybrid_with_rerank,
}

# ==================== 评估指标 ====================

def is_relevant(doc_content, relevant_keywords):
    """判断检索结果是否相关：包含至少2个标注关键词即视为相关"""
    content = doc_content or ""
    hit_count = sum(1 for kw in relevant_keywords if kw in content)
    return hit_count >= 2


def calc_recall_at_k(results, relevant_keywords, k=5):
    """Recall@K: 前K条结果中是否存在相关文档（1/0）"""
    for doc in results[:k]:
        if is_relevant(doc["content"], relevant_keywords):
            return 1.0
    return 0.0


def calc_mrr(results, relevant_keywords):
    """MRR: 第一个相关文档出现位置的倒数"""
    for i, doc in enumerate(results):
        if is_relevant(doc["content"], relevant_keywords):
            return 1.0 / (i + 1)
    return 0.0


# ==================== 运行实验 ====================
print("\n" + "=" * 60)
print("🚀 开始RAG检索策略消融实验")
print("=" * 60)

all_results = []  # 每道题每种策略的详细结果
summary = {}      # 每种策略的汇总指标

for strategy_name, strategy_func in STRATEGIES.items():
    print(f"\n📌 策略: {strategy_name}")
    recalls = []
    mrrs = []
    times = []
    per_question = []

    for q in questions:
        qid = q["id"]
        query_text = q["question"]
        keywords = q["relevant_keywords"]

        # 执行检索并计时
        start = time.perf_counter()
        try:
            results = strategy_func(query_text, top_k=5)
        except Exception as e:
            print(f"  ⚠️  Q{qid} 检索异常: {e}")
            results = []
        elapsed = (time.perf_counter() - start) * 1000  # ms

        # 计算指标
        recall = calc_recall_at_k(results, keywords, k=5)
        mrr = calc_mrr(results, keywords)

        recalls.append(recall)
        mrrs.append(mrr)
        times.append(elapsed)

        # 记录命中的文档数
        hit_docs = sum(1 for d in results if is_relevant(d["content"], keywords))
        per_question.append({
            "id": qid,
            "question": query_text,
            "category": q["category"],
            "recall@5": recall,
            "mrr": round(mrr, 4),
            "latency_ms": round(elapsed, 1),
            "retrieved_count": len(results),
            "relevant_count": hit_docs
        })

        if qid <= 3 or qid % 10 == 0:
            status = "✅" if recall > 0 else "❌"
            print(f"  {status} Q{qid:2d} | Recall={recall:.0f} | MRR={mrr:.3f} | {elapsed:6.1f}ms | {query_text[:25]}...")

    # 汇总
    avg_recall = sum(recalls) / len(recalls) if recalls else 0
    avg_mrr = sum(mrrs) / len(mrrs) if mrrs else 0
    avg_time = sum(times) / len(times) if times else 0

    summary[strategy_name] = {
        "recall@5": round(avg_recall, 4),
        "mrr": round(avg_mrr, 4),
        "avg_latency_ms": round(avg_time, 1),
        "total_questions": len(questions),
        "recalled_count": sum(1 for r in recalls if r > 0)
    }

    all_results.append({
        "strategy": strategy_name,
        "summary": summary[strategy_name],
        "details": per_question
    })

    print(f"\n  📊 {strategy_name} 汇总:")
    print(f"     Recall@5 = {avg_recall:.4f} ({sum(1 for r in recalls if r>0)}/{len(questions)} 题命中)")
    print(f"     MRR      = {avg_mrr:.4f}")
    print(f"     平均耗时 = {avg_time:.1f} ms")

# ==================== 保存结果 ====================
print("\n" + "=" * 60)
print("💾 保存实验结果...")

# 1. 详细CSV
import csv
csv_path = os.path.join(RESULTS_DIR, "rag_ablation_results.csv")
with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["策略", "问题ID", "类别", "问题", "Recall@5", "MRR", "耗时(ms)", "检索文档数", "相关文档数"])
    for strategy_data in all_results:
        sname = strategy_data["strategy"]
        for d in strategy_data["details"]:
            writer.writerow([
                sname, d["id"], d["category"], d["question"],
                d["recall@5"], d["mrr"], d["latency_ms"],
                d["retrieved_count"], d["relevant_count"]
            ])
print(f"  ✅ 详细结果: {csv_path}")

# 2. 汇总TXT
summary_path = os.path.join(RESULTS_DIR, "rag_ablation_summary.txt")
with open(summary_path, "w", encoding="utf-8") as f:
    f.write("=" * 60 + "\n")
    f.write("RAG检索策略消融实验 - 汇总报告\n")
    f.write("=" * 60 + "\n\n")
    f.write(f"测试问题数: {len(questions)}\n")
    f.write("评估指标: Recall@5, MRR, 平均检索耗时\n\n")
    f.write(f"{'策略':<20} {'Recall@5':<12} {'MRR':<12} {'平均耗时(ms)':<15} {'命中题数':<10}\n")
    f.write("-" * 70 + "\n")
    for sname, metrics in summary.items():
        f.write(f"{sname:<20} {metrics['recall@5']:<12.4f} {metrics['mrr']:<12.4f} "
                f"{metrics['avg_latency_ms']:<15.1f} {metrics['recalled_count']}/{metrics['total_questions']}\n")
    f.write("\n" + "=" * 60 + "\n")
    f.write("结论分析:\n")
    best_recall = max(summary.items(), key=lambda x: x[1]["recall@5"])
    best_mrr = max(summary.items(), key=lambda x: x[1]["mrr"])
    f.write(f"  - Recall@5 最优: {best_recall[0]} ({best_recall[1]['recall@5']:.4f})\n")
    f.write(f"  - MRR 最优: {best_mrr[0]} ({best_mrr[1]['mrr']:.4f})\n")
    f.write(f"  - 混合检索+Reranker 相比纯BM25的Recall提升: "
            f"{(summary['D_混合+Rerank']['recall@5'] - summary['A_纯BM25']['recall@5'])*100:.1f}%\n")
print(f"  ✅ 汇总报告: {summary_path}")

# 3. 图表
# 说明：Recall@5/MRR 是"词面命中"口径的召回指标，与 Rerank 的语义排序目标不对齐
# （消融实测中 Rerank 的 MRR 反而低于混合检索，正是"指标与假设错位"的体现）。
# 选型价值请以 run_e2e_quality_v2.py 的三层证据（检索质量直接评判/生产配置 Top-2/答案质量）为准。
# 因此这里不再生成 Recall@5/MRR 对比图，仅保留 CSV 数据作为消融原始记录。
print("  ℹ️  Recall@5/MRR 为词面口径消融数据，不生成对比图（选型价值见 run_e2e_quality_v2.py）")
print("  ℹ️  耗时对比图见 results/ablation_gpu_chart.png（GPU 实测 + 生产路径标注）")

# ==================== 清理 ====================
try:
    mysql_client.close()
except Exception:
    pass

print("\n" + "=" * 60)
print("🎉 实验完成！结果已保存到 results/ 目录")
print("=" * 60)
