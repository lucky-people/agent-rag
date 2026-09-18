# -*- coding: utf-8 -*-
"""
RAGAS 标准基准交叉验证 + 确定性幻觉率审计 (v3) —— 修复条款级重排后重跑
=====================================================================
修复: VectorStore.rerank_docs 条款级重排 (长文档按"第X条"切分打分取 max),
      解决 BGE-Reranker 整篇打分时关键法条相关性被同文档其他条款稀释的问题。

流程: 重新检索(修复后) → 3次生成 → RAGAS(Faithfulness/AnswerRelevancy)
      → 确定性条款命中审计(幻觉=未标注的编造)
输出:
  results/ragas_raw_samples_v3.json      检索+生成明细
  results/ragas_scores_v3.csv            RAGAS 三策略均值
  results/hallucination_audit_v3.csv     确定性审计(修复口径)
"""
import os
import sys
import time
import csv
import json
import re
import warnings

warnings.filterwarnings("ignore")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
RESULTS_DIR = os.path.join(PROJECT_ROOT, "实验脚本", "results")
GEN_ROUNDS = 3
LABELS = {"B_纯稠密": "B 纯稠密", "C_混合无Rerank": "C 混合检索", "D_混合+Rerank": "D 混合+Rerank"}

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
STRATEGIES = ["B_纯稠密", "C_混合无Rerank", "D_混合+Rerank"]


def get_retrieval_strategy(vs, query, strategy, top_k=5):
    """按策略检索 Top-k 父文档（D 使用条款级重排）"""
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
        # 修复: 条款级重排（与生产 hybrid_search_with_rerank 一致）
        parents = vs.rerank_docs(query, parents)
    return parents[:top_k]


def cn_num_to_arabic(s):
    digits = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    units = {"十": 10, "百": 100, "千": 1000}
    if s.startswith("十"):
        s = "一" + s
    total, section, num = 0, 0, 0
    for ch in s:
        if ch in digits:
            num = digits[ch]
        elif ch in units:
            section = (section + num) * units[ch]
            total += section
            section, num = 0, 0
        else:
            total += section + num
            section, num = 0, 0
    total += section + num
    return str(total) if total else ""


def extract_article_refs(text):
    refs = []
    for m in re.finditer(r"第\s*([一二三四五六七八九十百千零〇两0-9]+)\s*条", text):
        raw = m.group(1).replace(" ", "")
        if raw.isdigit():
            refs.append((raw, str(int(raw))))
        else:
            num = cn_num_to_arabic(raw)
            if num:
                refs.append((raw, num))
    return refs


def is_article_in_context(article_no, context):
    if f"第{article_no}条" in context:
        return True
    for m in re.finditer(r"第\s*([一二三四五六七八九十百千零〇两]+)\s*条", context):
        if cn_num_to_arabic(m.group(1)) == article_no:
            return True
    return False


def is_honestly_noted(ref_text, ref_no, answer):
    for m in re.finditer(r"[^。\n]{0,60}(?:未覆盖|未提供|未出现|未列出|上下文未|未包含)[^。\n]{0,40}", answer):
        snippet = m.group(0)
        if ref_no in snippet or ref_text in snippet:
            return True
    for pat in ("未覆盖", "未提供", "未出现", "未列出", "上下文未", "未包含"):
        for mm in re.finditer(pat, answer):
            s = max(0, mm.start() - 50)
            e = min(len(answer), mm.end() + 50)
            if ref_no in answer[s:e] or ref_text in answer[s:e]:
                return True
    return False


def main():
    print("=" * 70)
    print("RAGAS + 幻觉审计 v3 —— 条款级重排修复后重跑")
    print("=" * 70)
    from Agent.legal_qa.rag_qa import VectorStore
    from Agent.legal_qa.base.config import Config
    from openai import OpenAI

    vs = VectorStore()
    print(f"设备: {vs.device}")
    cfg = Config()
    llm_client = OpenAI(api_key=cfg.DASHSCOPE_API_KEY, base_url=cfg.DASHSCOPE_BASE_URL)
    llm_model = cfg.LLM_MODEL

    def llm_complete(prompt, temperature=0.2, retries=3):
        for attempt in range(retries):
            try:
                resp = llm_client.chat.completions.create(
                    model=llm_model, messages=[{"role": "user", "content": prompt}],
                    temperature=temperature)
                return resp.choices[0].message.content.strip()
            except Exception as e:
                if attempt < retries - 1:
                    time.sleep(3)
                else:
                    raise
        return ""

    # ===== 阶段 A: 检索(修复后) + 3次生成 =====
    print(f"\n阶段 A：检索(条款级重排) + {GEN_ROUNDS}次生成")
    samples, expanded = [], []
    for qid, question, diff in QUESTIONS:
        for strat in STRATEGIES:
            t0 = time.time()
            docs = get_retrieval_strategy(vs, question, strat)
            el = (time.time() - t0) * 1000
            context = "\n\n".join([d.page_content for d in docs]) if docs else "(无检索结果)"
            prompt = f"""你是一名专业的房屋租赁法律顾问。请仅依据下面提供的法律条文/案例上下文回答用户问题。
要求：1) 直接给出结论；2) 引用具体法条（如"民法典第X条"/"住房租赁条例第X条"）支撑；3) 若上下文不足以回答，明确说明"上下文未覆盖"。

[上下文开始]
{context}
[上下文结束]

问题：{question}"""
            sample = {"qid": qid, "strategy": strat, "question": question,
                      "contexts": [d.page_content for d in docs],
                      "retr_ms": el, "n_docs": len(docs)}
            samples.append(sample)
            for r in range(GEN_ROUNDS):
                try:
                    answer = llm_complete(prompt, temperature=0.3)
                except Exception as e:
                    print(f"  ⚠️ {qid} {strat} r{r+1} 失败: {e}")
                    answer = ""
                expanded.append({**sample, "round": r + 1, "answer": answer})
                time.sleep(0.15)
            print(f"  [{strat}] {qid} 检索{len(docs)}篇({el:.0f}ms) 3次生成完成")
    with open(os.path.join(RESULTS_DIR, "ragas_raw_samples_v3.json"), "w", encoding="utf-8") as f:
        json.dump({"samples": samples, "expanded": expanded}, f, ensure_ascii=False, indent=1)

    # ===== 阶段 B: RAGAS =====
    print("\n阶段 B：RAGAS Faithfulness + AnswerRelevancy")
    from ragas import EvaluationDataset, SingleTurnSample, evaluate
    from ragas.metrics import Faithfulness, AnswerRelevancy
    from ragas.llms import LangchainLLMWrapper
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from langchain_openai import ChatOpenAI
    from langchain_core.embeddings import Embeddings

    chat = ChatOpenAI(model=llm_model, api_key=cfg.DASHSCOPE_API_KEY,
                      base_url=cfg.DASHSCOPE_BASE_URL, temperature=0)
    llm_wrapper = LangchainLLMWrapper(chat)

    class BGE3LangchainEmbeddings(Embeddings):
        def embed_documents(self, texts):
            return [vs.embedding_function([t])["dense"][0].tolist() for t in texts]
        def embed_query(self, text):
            return vs.embedding_function([text])["dense"][0].tolist()
    emb_wrapper = LangchainEmbeddingsWrapper(BGE3LangchainEmbeddings())

    ds = EvaluationDataset(samples=[
        SingleTurnSample(user_input=e["question"], response=e["answer"],
                         retrieved_contexts=e["contexts"][:5]) for e in expanded
    ])
    result = evaluate(ds, metrics=[Faithfulness(llm=llm_wrapper),
                                   AnswerRelevancy(llm=llm_wrapper, embeddings=emb_wrapper)])
    pdf = result.to_pandas()
    for i, e in enumerate(expanded):
        row = pdf.iloc[i]
        e["faithfulness"] = float(row.get("faithfulness", 0))
        e["answer_relevancy"] = float(row.get("answer_relevancy", 0))
    print(f"  ✅ RAGAS 完成 ({len(expanded)} 样本)")

    # ===== 阶段 C: 确定性审计 =====
    print("\n阶段 C：确定性条款命中审计（幻觉=未标注编造）")
    by_key = {}
    for e in expanded:
        by_key.setdefault((e["qid"], e["strategy"]), []).append(e)
    audit_rows = []
    for (qid, strat), rounds in sorted(by_key.items()):
        full_context = "\n".join(rounds[0]["contexts"])
        round_rates = []
        union_cited, union_sup, union_unsup = set(), set(), set()
        for r in rounds:
            refs = extract_article_refs(r["answer"])
            cited, sup, unsup = set(), set(), set()
            for raw, no in refs:
                cited.add(no)
                if is_article_in_context(no, full_context):
                    sup.add(no)
                elif is_honestly_noted(raw, no, r["answer"]):
                    pass  # 诚实标注缺失证据, 不算幻觉
                else:
                    unsup.add(no)
            union_cited |= cited; union_sup |= sup; union_unsup |= unsup
            if cited:
                round_rates.append(1 - len(unsup) / len(cited))
        truth = sum(round_rates) / len(round_rates) if round_rates else None
        hallu = len(union_unsup) / len(union_cited) if union_cited else None
        audit_rows.append({"qid": qid, "strategy": strat, "cited_refs": len(union_cited),
                           "supported": len(union_sup), "hallucinated": len(union_unsup),
                           "truth_rate": round(truth, 4) if truth is not None else "",
                           "hallucination_rate": round(hallu, 4) if hallu is not None else ""})
        print(f"  [{strat}] {qid}: 引用{len(union_cited)} 命中{len(union_sup)} 幻觉{len(union_unsup)}"
              f" | 真实率={truth if truth is not None else 'N/A'}")
    with open(os.path.join(RESULTS_DIR, "hallucination_audit_v3.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["qid", "strategy", "cited_refs", "supported",
                                          "hallucinated", "truth_rate", "hallucination_rate"])
        w.writeheader()
        w.writerows(audit_rows)

    # ===== 汇总 =====
    print("\n" + "=" * 70)
    print("汇总（修复后, 3 次生成均值）")
    print("=" * 70)
    ragas_rows = []
    for strat in STRATEGIES:
        es = [e for e in expanded if e["strategy"] == strat]
        by_q = {}
        for e in es:
            by_q.setdefault(e["qid"], []).append(e)
        avg_f, avg_r = [], []
        for qid, lst in by_q.items():
            avg_f.append(sum(e["faithfulness"] for e in lst) / len(lst))
            avg_r.append(sum(e["answer_relevancy"] for e in lst) / len(lst))
        mf, mr = sum(avg_f) / len(avg_f), sum(avg_r) / len(avg_r)
        ar = [a for a in audit_rows if a["strategy"] == strat and a["truth_rate"] != ""]
        hit = sum(float(a["truth_rate"]) for a in ar) / len(ar) if ar else None
        print(f"  {LABELS[strat]:<12} 忠实度={mf:.3f} 相关性={mr:.3f} | 引用真实率={hit:.3f} "
              f"幻觉率={1-hit:.3f}" if hit else
              f"  {LABELS[strat]:<12} 忠实度={mf:.3f} 相关性={mr:.3f} | 引用真实率=N/A")
        ragas_rows.append({"strategy": strat, "faithfulness_mean": round(mf, 4),
                           "answer_relevancy_mean": round(mr, 4)})
    with open(os.path.join(RESULTS_DIR, "ragas_scores_v3.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["strategy", "faithfulness_mean", "answer_relevancy_mean"])
        w.writeheader()
        w.writerows(ragas_rows)
    print("\n完成 ✅")


if __name__ == "__main__":
    main()
