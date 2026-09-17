# -*- coding: utf-8 -*-
"""
端到端答案质量评估：不同检索策略 → LLM 答案质量
=============================================
核心逻辑：同一批问题，用三种检索策略（纯稠密 B / 混合无Rerank C / 混合+Rerank D）
分别检索 Top-5 作为 LLM 上下文，生成答案，再由 LLM 评判:
  - 忠实度(0-5): 答案是否严格基于给定上下文, 不臆造
  - 引用准确率(0-5): 引用的法条/条文是否真实存在于上下文
  - 信息完整性(0-5): 是否覆盖问题的关键法律要点
结论预期: 混合+Rerank 保证进入上下文的文档最相关 → 答案忠实度/引用准确率最高。
"""
import os
import sys
import json
import time
import csv
import warnings

warnings.filterwarnings("ignore")
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")  # 优先 GPU

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

RESULTS = os.path.join(PROJECT_ROOT, "实验脚本", "results")
os.makedirs(RESULTS, exist_ok=True)

# 代表性 8 题（覆盖简单/中等/困难 + 消融中 D 赢回/丢失的题目）
QUESTIONS = [
    ("Q1", "房东拖延退押金可以要求利息赔偿吗", "困难"),
    ("Q2", "房东以房屋有损坏为由扣全部押金合法吗", "中等"),
    ("Q3", "提前退租押金能要回来吗", "中等"),
    ("Q4", "押金和定金有什么区别？租房时交的是哪个", "简单"),
    ("Q5", "租客提前退租需要承担什么责任", "中等"),
    ("Q6", "房东卖房后租客能拒绝搬走吗", "中等"),
    ("Q7", "租客可以装修房屋抵扣租金吗", "困难"),
    ("Q8", "未经房东同意转租会有什么后果", "中等"),
]


def get_retrieval_strategy(vs, query, strategy):
    """按策略检索 Top-5 父文档, 返回文档列表"""
    import numpy as np
    from pymilvus import AnnSearchRequest, WeightedRanker
    emb = vs.embedding_function([query])
    dense_vec = np.array(emb["dense"][0], dtype=np.float32)
    sparse = {}
    row = emb["sparse"][[0]]
    for idx, val in zip(row.indices, row.data):
        sparse[idx] = val

    if strategy == "B_纯稠密":
        hits = vs.client.search(
            collection_name=vs.collection_name, data=[dense_vec],
            anns_field="dense_vector",
            search_params={"metric_type": "IP", "params": {"nprobe": 10}},
            limit=50, output_fields=["text", "parent_id", "parent_content", "source", "timestamp"])[0]
        subs = [vs._doc_from_hit(h["entity"]) for h in hits]
        parents = vs._get_unique_parent_docs(subs)
        return parents[:5]

    # C/D 共用混合检索候选
    dense_req = AnnSearchRequest(data=[dense_vec], anns_field="dense_vector",
                                 param={"metric_type": "IP", "params": {"nprobe": 10}}, limit=50)
    sparse_req = AnnSearchRequest(data=[sparse], anns_field="sparse_vector",
                                  param={"metric_type": "IP", "params": {}}, limit=50)
    hits = vs.client.hybrid_search(
        collection_name=vs.collection_name, reqs=[dense_req, sparse_req],
        ranker=WeightedRanker(1.0, 0.3), limit=50,
        output_fields=["text", "parent_id", "parent_content", "source", "timestamp"])[0]
    subs = [vs._doc_from_hit(h["entity"]) for h in hits]
    parents = vs._get_unique_parent_docs(subs)

    if strategy == "C_混合无Rerank":
        return parents[:5]
    # D: 全部父文档 Rerank 后取 Top-5
    if len(parents) > 1 and vs.reranker is not None:
        pairs = [[query, d.page_content] for d in parents]
        scores = vs.reranker.predict(pairs)
        parents = [d for _, d in sorted(zip(scores, parents), key=lambda x: x[0], reverse=True)]
    return parents[:5]


def main():
    print("=" * 60)
    print("端到端答案质量评估：检索策略 → LLM 答案质量")
    print("=" * 60)

    from Agent.legal_qa.rag_qa import VectorStore
    from Agent.legal_qa.base.config import Config
    from openai import OpenAI

    print("初始化 VectorStore（GPU）...")
    vs = VectorStore()
    print(f"  设备: {vs.device}")

    cfg = Config()
    client = OpenAI(api_key=cfg.DASHSCOPE_API_KEY, base_url=cfg.DASHSCOPE_BASE_URL)
    llm_model = cfg.LLM_MODEL

    def llm_complete(prompt):
        resp = client.chat.completions.create(
            model=llm_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        return resp.choices[0].message.content.strip()

    strategies = ["B_纯稠密", "C_混合无Rerank", "D_混合+Rerank"]
    rows = []
    raw_answers = {}

    for qid, question, diff in QUESTIONS:
        print(f"\n--- {qid} [{diff}] {question} ---")
        q_answers = {}
        for strat in strategies:
            t0 = time.time()
            docs = get_retrieval_strategy(vs, question, strat)
            retr_ms = round((time.time() - t0) * 1000, 1)
            context = "\n\n".join([d.page_content for d in docs]) if docs else "(无检索结果)"
            srcs = ",".join(sorted({d.metadata.get("source", "") for d in docs}))

            prompt = f"""你是一名专业的房屋租赁法律顾问。请仅依据下面提供的法律条文/案例上下文回答用户问题。
要求：1) 直接给出结论；2) 引用具体法条（如"民法典第X条"/"住房租赁条例第X条"）支撑；3) 若上下文不足以回答，明确说明"上下文未覆盖"。

[上下文开始]
{context}
[上下文结束]

问题：{question}"""
            t1 = time.time()
            answer = llm_complete(prompt)
            gen_ms = round((time.time() - t1) * 1000, 1)
            q_answers[strat] = {"answer": answer, "docs": len(docs), "sources": srcs,
                                "retr_ms": retr_ms, "gen_ms": gen_ms}
            print(f"  [{strat}] 检索{len(docs)}篇({retr_ms}ms) 生成({gen_ms}ms) 答案{len(answer)}字")
        raw_answers[qid] = q_answers
        time.sleep(0.5)

    # LLM 评判
    print("\n" + "=" * 60)
    print("LLM 评判阶段：忠实度 / 引用准确率 / 完整性")
    print("=" * 60)
    judge_prompt_tpl = """请作为评估专家，对下面三份"房屋租赁法律问答"答案进行打分（0-5 整数）。

问题：{question}

评判标准：
- 忠实度：答案是否严格基于给定上下文，是否臆造法条/事实（5=完全基于上下文）
- 引用准确率：答案引用的法条编号/内容是否真实来自上下文（5=全部引用准确）
- 完整性：答案是否覆盖问题的关键法律要点（5=完整覆盖）

三份答案分别来自三种检索策略（B=纯稠密向量 / C=混合检索 / D=混合+Rerank）：

[B 纯稠密向量] {b_ans}

[C 混合检索] {c_ans}

[D 混合+Rerank] {d_ans}

请按格式输出（每行一个策略，逗号分隔三项）：
B,忠实度,引用准确率,完整性
C,忠实度,引用准确率,完整性
D,忠实度,引用准确率,完整性"""

    for qid, question, diff in QUESTIONS:
        q_answers = raw_answers[qid]
        try:
            judge = llm_complete(judge_prompt_tpl.format(
                question=question,
                b_ans=q_answers["B_纯稠密"]["answer"],
                c_ans=q_answers["C_混合无Rerank"]["answer"],
                d_ans=q_answers["D_混合+Rerank"]["answer"]))
        except Exception as e:
            print(f"  {qid} 评判失败: {e}")
            judge = ""
        print(f"  {qid} 评判: {judge[:100]}...")

        parsed = {"B": None, "C": None, "D": None}
        for line in judge.strip().splitlines():
            line = line.strip()
            if line.startswith(("B", "C", "D")) and "," in line:
                parts = [p.strip() for p in line.split(",")]
                if len(parts) == 4 and parts[0] in parsed:
                    try:
                        parsed[parts[0]] = [int(float(parts[1])), int(float(parts[2])), int(float(parts[3]))]
                    except ValueError:
                        pass
        for strat, key in [("B_纯稠密", "B"), ("C_混合无Rerank", "C"), ("D_混合+Rerank", "D")]:
            scores = parsed[key]
            if scores:
                rows.append({
                    "qid": qid, "question": question, "difficulty": diff, "strategy": strat,
                    "faithfulness": scores[0], "citation": scores[1], "completeness": scores[2],
                    "docs": q_answers[strat]["docs"], "sources": q_answers[strat]["sources"],
                    "retr_ms": q_answers[strat]["retr_ms"], "gen_ms": q_answers[strat]["gen_ms"],
                    "answer_len": len(q_answers[strat]["answer"]),
                })
        time.sleep(0.3)

    # 保存
    csv_path = os.path.join(RESULTS, "e2e_answer_quality.csv")
    if rows:
        with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        print(f"\n✅ 详细结果: {csv_path}")

    # 汇总
    print("\n" + "=" * 60)
    print("汇总（平均分 0-5）")
    print("=" * 60)
    for strat in strategies:
        sr = [r for r in rows if r["strategy"] == strat]
        if sr:
            n = len(sr)
            fth = sum(r["faithfulness"] for r in sr) / n
            cit = sum(r["citation"] for r in sr) / n
            cmp = sum(r["completeness"] for r in sr) / n
            total = (fth + cit + cmp) / 3
            print(f"  {strat:<14} 忠实度={fth:.2f} 引用准确={cit:.2f} 完整={cmp:.2f} 综合={total:.2f} (n={n})")
    return csv_path if rows else None


if __name__ == "__main__":
    main()
