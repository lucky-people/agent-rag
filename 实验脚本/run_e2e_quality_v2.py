# -*- coding: utf-8 -*-
"""
端到端答案质量评估 v2（修复版）
==============================
修复缺陷:
  1. 评判 LLM 现在能"看到"每份答案对应的检索上下文，真正验证引用真实性
  2. 新增"检索质量直接评判"：让 LLM 对三个策略的 Top-5 文档列表打分
     (相关性/支撑性)，绕开 LLM 生成噪声，直接测 Rerank 的排序价值
  3. 生产配置对比：CANDIDATE_M=2 只取 Top-2 进 LLM，排序质量直接影响答案
  4. 答案质量评判 2 次取均值，抗 LLM 评判噪声

阶段:
  A. 检索: B/C/D 各取 Top-5, 记录文档
  B. 检索质量评判: LLM 比较三策略文档列表 (相关性/支撑性 0-5)  ← 核心新增
  C. 答案生成: 每策略 Top-5 上下文 → LLM 生成答案
  D. 答案质量评判: 问题+该策略上下文+答案 → 忠实度/引用/完整性 (2次均值)
  E. 生产配置: C/D 各取 Top-2 生成答案并评判 (4 道代表题)
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
PROD_QUESTIONS = ["Q1", "Q5", "Q2", "Q8"]  # 生产配置对比代表题

STRATEGIES = ["B_纯稠密", "C_混合无Rerank", "D_混合+Rerank"]


def get_retrieval_strategy(vs, query, strategy, top_k=5):
    """按策略检索 Top-k 父文档"""
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
        return parents[:top_k]

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
        return parents[:top_k]
    if len(parents) > 1 and vs.reranker is not None:
        pairs = [[query, d.page_content] for d in parents]
        scores = vs.reranker.predict(pairs)
        parents = [d for _, d in sorted(zip(scores, parents), key=lambda x: x[0], reverse=True)]
    return parents[:top_k]


def docs_to_prompt(docs, max_len=180):
    """文档列表 → 截断后的 prompt 文本"""
    parts = []
    for i, d in enumerate(docs[:5]):
        src = d.metadata.get("source", "未知来源")
        text = (d.page_content or "")[:max_len].replace("\n", " ")
        parts.append(f"[文档{i+1}|{src}] {text}")
    return "\n".join(parts)


def main():
    print("=" * 70)
    print("端到端答案质量评估 v2（修复版：评判可见上下文 + 检索质量直接评判）")
    print("=" * 70)

    from Agent.legal_qa.rag_qa import VectorStore
    from Agent.legal_qa.base.config import Config
    from openai import OpenAI

    print("初始化 VectorStore（GPU）...")
    vs = VectorStore()
    print(f"  设备: {vs.device}")

    cfg = Config()
    client = OpenAI(api_key=cfg.DASHSCOPE_API_KEY, base_url=cfg.DASHSCOPE_BASE_URL)
    llm_model = cfg.LLM_MODEL

    def llm_complete(prompt, temperature=0.2, retries=3):
        for attempt in range(retries):
            try:
                resp = client.chat.completions.create(
                    model=llm_model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=temperature,
                )
                return resp.choices[0].message.content.strip()
            except Exception as e:
                if attempt < retries - 1:
                    print(f"    ⚠️ LLM 调用失败({e}), 重试 {attempt+2}/{retries}")
                    time.sleep(2)
                else:
                    raise
        return ""

    # ============ 阶段 A+B: 检索 + 检索质量直接评判 ============
    print("\n" + "=" * 70)
    print("阶段 A+B：检索 Top-5 + 检索质量直接评判（LLM 比较三策略文档列表）")
    print("=" * 70)
    retrieval_scores = []  # 每策略检索质量分
    per_q_docs = {}

    for qid, question, diff in QUESTIONS:
        print(f"\n--- {qid} [{diff}] {question} ---")
        q_docs = {}
        for strat in STRATEGIES:
            t0 = time.time()
            docs = get_retrieval_strategy(vs, question, strat)
            el = (time.time() - t0) * 1000
            q_docs[strat] = docs
            print(f"  [A|{strat}] 检索 {len(docs)} 篇 ({el:.0f}ms)")
        per_q_docs[qid] = q_docs

        # 阶段 B：检索质量评判（一次调用比较三策略）
        prompt = f"""你是信息检索质量评估专家。针对下面的租房法律问题，三个检索策略分别返回了 5 篇候选文档。
请评估每个策略的检索结果质量：是否包含能真正回答问题/支撑法律结论的相关文档。
只输出三行，格式：策略,相关性得分(0-5),支撑性得分(0-5)

问题：{question}

[B 纯稠密向量 检索结果]
{docs_to_prompt(q_docs["B_纯稠密"])}

[C 混合检索 检索结果]
{docs_to_prompt(q_docs["C_混合无Rerank"])}

[D 混合+Rerank 检索结果]
{docs_to_prompt(q_docs["D_混合+Rerank"])}"""
        try:
            judge = llm_complete(prompt, temperature=0.0)
        except Exception as e:
            print(f"  ⚠️ 检索评判失败: {e}")
            judge = ""
        print(f"  [B|检索评判] {judge[:150]}...")

        for strat, key in [("B_纯稠密", "B"), ("C_混合无Rerank", "C"), ("D_混合+Rerank", "D")]:
            for line in judge.strip().splitlines():
                line = line.strip()
                if line.startswith(key) and "," in line:
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) >= 3:
                        try:
                            retrieval_scores.append({
                                "qid": qid, "strategy": strat,
                                "relevance": int(float(parts[1])),
                                "support": int(float(parts[2])),
                            })
                        except ValueError:
                            pass
        time.sleep(0.3)

    # ============ 阶段 C: 答案生成 ============
    print("\n" + "=" * 70)
    print("阶段 C：每策略 Top-5 上下文 → LLM 生成答案")
    print("=" * 70)
    raw_answers = {}
    for qid, question, diff in QUESTIONS:
        q_answers = {}
        for strat in STRATEGIES:
            docs = per_q_docs[qid][strat]
            context = "\n\n".join([d.page_content for d in docs]) if docs else "(无检索结果)"
            prompt = f"""你是一名专业的房屋租赁法律顾问。请仅依据下面提供的法律条文/案例上下文回答用户问题。
要求：1) 直接给出结论；2) 引用具体法条（如"民法典第X条"/"住房租赁条例第X条"）支撑；3) 若上下文不足以回答，明确说明"上下文未覆盖"。

[上下文开始]
{context}
[上下文结束]

问题：{question}"""
            try:
                answer = llm_complete(prompt, temperature=0.3)
            except Exception as e:
                print(f"  ⚠️ {qid} {strat} 生成失败: {e}")
                answer = ""
            q_answers[strat] = {"answer": answer, "docs": len(docs)}
            print(f"  [C|{strat}] 答案 {len(answer)} 字")
        raw_answers[qid] = q_answers
        time.sleep(0.3)

    # ============ 阶段 D: 答案质量评判（可见上下文, 2次均值） ============
    print("\n" + "=" * 70)
    print("阶段 D：答案质量评判（评判 LLM 可见该策略的检索上下文，2 次取均值）")
    print("=" * 70)
    answer_scores = []  # qid, strategy, faithfulness, citation, completeness
    for qid, question, diff in QUESTIONS:
        for strat in STRATEGIES:
            docs = per_q_docs[qid][strat]
            answer = raw_answers[qid][strat]["answer"]
            ctx_text = docs_to_prompt(docs, max_len=200)
            prompt = f"""请作为评估专家，对下面的"房屋租赁法律问答"进行打分（0-5 整数）。

问题：{question}

[该答案实际使用的检索上下文]
{ctx_text}

[答案]
{answer}

评判标准：
- 忠实度：答案是否严格基于给定上下文（不臆造法条/事实）？引用的内容是否真的出现在上下文中？
- 引用准确率：答案引用的法条编号/具体内容，是否真实存在于上下文？（0=大量引用不在上下文中, 5=全部引用都可在上下文中找到）
- 完整性：答案是否覆盖问题的关键法律要点？（5=完整覆盖）

只输出一行：忠实度,引用准确率,完整性"""
            scores = []
            for rd in range(2):
                try:
                    judge = llm_complete(prompt, temperature=0.0)
                except Exception as e:
                    print(f"  ⚠️ {qid} {strat} 评判失败: {e}")
                    judge = ""
                parts = [p.strip() for p in judge.strip().split(",")]
                if len(parts) >= 3:
                    try:
                        scores.append([int(float(parts[0])), int(float(parts[1])), int(float(parts[2]))])
                    except ValueError:
                        pass
                time.sleep(0.2)
            if scores:
                n = len(scores)
                avg = [sum(s[i] for s in scores) / n for i in range(3)]
                answer_scores.append({
                    "qid": qid, "strategy": strat, "faithfulness": avg[0],
                    "citation": avg[1], "completeness": avg[2],
                })
                print(f"  [D|{strat}] 忠实={avg[0]:.1f} 引用={avg[1]:.1f} 完整={avg[2]:.1f}")
            else:
                print(f"  [D|{strat}] 评判解析失败")

    # ============ 阶段 E: 生产配置对比 (CANDIDATE_M=2) ============
    print("\n" + "=" * 70)
    print("阶段 E：生产配置对比——只取 Top-2 进 LLM（CANDIDATE_M=2）")
    print("=" * 70)
    prod_scores = []
    for qid in PROD_QUESTIONS:
        question = next(q for qid_, q, _ in QUESTIONS if qid_ == qid)
        for strat in ["C_混合无Rerank", "D_混合+Rerank"]:
            docs = get_retrieval_strategy(vs, question, strat, top_k=2)
            context = "\n\n".join([d.page_content for d in docs]) if docs else "(无检索结果)"
            prompt = f"""你是一名专业的房屋租赁法律顾问。请仅依据下面提供的法律条文/案例上下文回答用户问题。
要求：1) 直接给出结论；2) 引用具体法条支撑；3) 若上下文不足以回答，明确说明"上下文未覆盖"。

[上下文开始]
{context}
[上下文结束]

问题：{question}"""
            try:
                answer = llm_complete(prompt, temperature=0.3)
            except Exception as e:
                print(f"  ⚠️ 生产配置 {qid} {strat} 生成失败: {e}")
                answer = ""
            # 评判（可见 Top-2 上下文）
            ctx_text = docs_to_prompt(docs, max_len=250)
            jprompt = f"""请评估下面的"房屋租赁法律问答"（0-5 整数）。

问题：{question}

[该答案实际使用的检索上下文（仅 Top-2 文档）]
{ctx_text}

[答案]
{answer}

评判标准：
- 忠实度：答案是否严格基于给定上下文？引用的内容是否真的出现在上下文中？
- 引用准确率：答案引用的法条编号/内容，是否真实存在于上下文？
- 完整性：答案是否覆盖问题的关键法律要点？

只输出一行：忠实度,引用准确率,完整性"""
            try:
                judge = llm_complete(jprompt, temperature=0.0)
            except Exception as e:
                judge = ""
                print(f"  ⚠️ 生产配置评判失败: {e}")
            parts = [p.strip() for p in judge.strip().split(",")]
            if len(parts) >= 3:
                try:
                    prod_scores.append({
                        "qid": qid, "strategy": strat,
                        "faithfulness": int(float(parts[0])),
                        "citation": int(float(parts[1])),
                        "completeness": int(float(parts[2])),
                        "answer_len": len(answer),
                    })
                    print(f"  [E|{strat}] {qid}: 忠实={parts[0]} 引用={parts[1]} 完整={parts[2]} 答案{len(answer)}字")
                except ValueError:
                    pass
            else:
                print(f"  [E|{strat}] {qid}: 评判解析失败")
            time.sleep(0.3)

    # ============ 保存 ============
    def save_csv(name, rows):
        path = os.path.join(RESULTS, name)
        if rows:
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerows(rows)
            print(f"  ✅ {name}: {len(rows)} 行")
        return path

    print("\n" + "=" * 70)
    print("保存结果")
    print("=" * 70)
    save_csv("e2e_retrieval_scores.csv", retrieval_scores)
    save_csv("e2e_answer_quality_v2.csv", answer_scores)
    save_csv("e2e_prod_top2_scores.csv", prod_scores)

    # ============ 汇总 ============
    print("\n" + "=" * 70)
    print("汇总")
    print("=" * 70)

    def avg_score(rows, key, n=None):
        sr = rows[:n] if n else rows
        return sum(r[key] for r in sr) / len(sr) if sr else 0

    print("\n--- 检索质量直接评判（LLM 对三策略文档列表打分）---")
    for strat in STRATEGIES:
        sr = [r for r in retrieval_scores if r["strategy"] == strat]
        if sr:
            rel = avg_score(sr, "relevance")
            sup = avg_score(sr, "support")
            print(f"  {strat:<14} 相关性={rel:.2f} 支撑性={sup:.2f} (n={len(sr)})")

    print("\n--- 答案质量（评判可见上下文, 2次均值）---")
    for strat in STRATEGIES:
        sr = [r for r in answer_scores if r["strategy"] == strat]
        if sr:
            fth = avg_score(sr, "faithfulness")
            cit = avg_score(sr, "citation")
            cmp = avg_score(sr, "completeness")
            print(f"  {strat:<14} 忠实度={fth:.2f} 引用准确={cit:.2f} 完整={cmp:.2f} 综合={(fth+cit+cmp)/3:.2f} (n={len(sr)})")

    print("\n--- 生产配置（Top-2 进 LLM, CANDIDATE_M=2）---")
    for strat in ["C_混合无Rerank", "D_混合+Rerank"]:
        sr = [r for r in prod_scores if r["strategy"] == strat]
        if sr:
            fth = avg_score(sr, "faithfulness")
            cit = avg_score(sr, "citation")
            cmp = avg_score(sr, "completeness")
            print(f"  {strat:<14} 忠实度={fth:.2f} 引用准确={cit:.2f} 完整={cmp:.2f} 综合={(fth+cit+cmp)/3:.2f} (n={len(sr)})")

    print("\n完成")


if __name__ == "__main__":
    main()
