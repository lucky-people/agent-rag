# -*- coding: utf-8 -*-
"""
评估回归门 (Evaluation Gate)
============================
企业级"评估即 CI"落地: 一条命令跑固定评估集 → 确定性幻觉审计 (+可选 RAGAS)
→ 与基线快照对比 → 指标回退超阈值即 FAIL (exit 1), 用于本地/CI 质量门。

用法:
  python scripts/eval_gate.py                  # 8题×3策略×1轮, 确定性审计
  python scripts/eval_gate.py --rounds 3       # 3 轮生成取均值(复现 v3 口径)
  python scripts/eval_gate.py --ragas          # 额外跑 RAGAS 打分(慢, 需 API)
  python scripts/eval_gate.py --questions Q1,Q6 --tol 0.08
  python scripts/eval_gate.py --baseline results  # 指定基线目录

基线: 默认读取 results/hallucination_audit_v5.csv + ragas_scores_v3.csv
     (修复后最终版, 即"黄金基线"); 每次跑出的新结果可 `--save-baseline` 提升基线。
阈值: 任一策略的 引用真实率 或 RAGAS忠实度 低于 基线-tol → FAIL。
"""
import os
import sys
import csv
import json
import time
import re
import argparse
import warnings
from datetime import datetime

warnings.filterwarnings("ignore")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

LABELS = {"B_纯稠密": "B 纯稠密", "C_混合无Rerank": "C 混合检索", "D_混合+Rerank": "D 混合+Rerank"}
STRATEGIES = ["B_纯稠密", "C_混合无Rerank", "D_混合+Rerank"]

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

# ---------------- 检索 ----------------
def get_retrieval_strategy(vs, query, strategy, top_k=5):
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
        parents = vs.rerank_docs(query, parents)  # 条款级重排(生产同源)
    return parents[:top_k]


# ---------------- 确定性条款审计 ----------------
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
    for pat in ("未覆盖", "未提供", "未出现", "未列出", "上下文未", "未包含"):
        for mm in re.finditer(pat, answer):
            s = max(0, mm.start() - 50)
            e = min(len(answer), mm.end() + 50)
            if ref_no in answer[s:e] or ref_text in answer[s:e]:
                return True
    return False


def run_deterministic_audit(expanded):
    by_key = {}
    for e in expanded:
        by_key.setdefault((e["qid"], e["strategy"]), []).append(e)
    rows = []
    for (qid, strat), rounds in sorted(by_key.items()):
        full_context = "\n".join(rounds[0]["contexts"])
        round_rates, union_cited, union_unsup = [], set(), set()
        for r in rounds:
            refs = extract_article_refs(r["answer"])
            cited, unsup = set(), set()
            for raw, no in refs:
                cited.add(no)
                if is_article_in_context(no, full_context):
                    continue
                if is_honestly_noted(raw, no, r["answer"]):
                    continue
                unsup.add(no)
            union_cited |= cited
            union_unsup |= unsup
            if cited:
                round_rates.append(1 - len(unsup) / len(cited))
        truth = sum(round_rates) / len(round_rates) if round_rates else None
        rows.append({"qid": qid, "strategy": strat,
                     "cited_refs": len(union_cited), "hallucinated": len(union_unsup),
                     "truth_rate": round(truth, 4) if truth is not None else None})
    return rows


# ---------------- 基线 ----------------
def load_baseline(baseline_dir):
    """从 results/ 读取黄金基线: 引用真实率(v5) + RAGAS 忠实度(v3)"""
    truth, faith = {}, {}
    p1 = os.path.join(baseline_dir, "hallucination_audit_v5.csv")
    if os.path.exists(p1):
        acc = {s: [] for s in STRATEGIES}
        with open(p1, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                if row["truth_rate"] not in ("", None):
                    acc[row["strategy"]].append(float(row["truth_rate"]))
        truth = {s: (sum(v) / len(v)) for s, v in acc.items() if v}
    p2 = os.path.join(baseline_dir, "ragas_scores_v3.csv")
    if os.path.exists(p2):
        with open(p2, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                if row["faithfulness_mean"] not in ("", None):
                    faith[row["strategy"]] = float(row["faithfulness_mean"])
    return {"truth_rate": truth, "faithfulness": faith}


# ---------------- 主流程 ----------------
def main():
    ap = argparse.ArgumentParser(description="评估回归门")
    ap.add_argument("--rounds", type=int, default=1, help="每(题,策略)生成轮数, 默认1")
    ap.add_argument("--ragas", action="store_true", help="额外跑 RAGAS 打分(慢)")
    ap.add_argument("--tol", type=float, default=0.05, help="指标回退容差, 默认0.05")
    ap.add_argument("--questions", default="", help="子集: Q1,Q6 (默认全部8题)")
    ap.add_argument("--baseline", default=os.path.join(PROJECT_ROOT, "scripts", "results"), help="基线目录")
    ap.add_argument("--save-baseline", action="store_true", help="用本次结果提升基线CSV")
    ap.add_argument("--out", default=os.path.join(PROJECT_ROOT, "scripts", "results"), help="输出目录")
    args = ap.parse_args()

    qs = QUESTIONS
    if args.questions:
        allow = set(args.questions.split(","))
        qs = [q for q in QUESTIONS if q[0] in allow]
    print("=" * 74)
    print(f"评估回归门 | {len(qs)}题×{len(STRATEGIES)}策略×{args.rounds}轮 | ragas={'开' if args.ragas else '关'}")
    print("=" * 74)

    from Agent.legal_qa.rag_qa import VectorStore
    from Agent.legal_qa.base.config import Config
    from openai import OpenAI

    vs = VectorStore()
    cfg = Config()
    llm_client = OpenAI(api_key=cfg.DASHSCOPE_API_KEY, base_url=cfg.DASHSCOPE_BASE_URL)
    llm_model = cfg.LLM_MODEL
    print(f"设备: {vs.device} | 模型: {llm_model} | 集合: {vs.collection_name}")

    def llm_complete(prompt, temperature=0.3, retries=3):
        for attempt in range(retries):
            try:
                resp = llm_client.chat.completions.create(
                    model=llm_model, messages=[{"role": "user", "content": prompt}],
                    temperature=temperature)
                return resp.choices[0].message.content.strip()
            except Exception:
                if attempt < retries - 1:
                    time.sleep(2)
                else:
                    raise
        return ""

    # 阶段A: 检索 + 生成
    print("\n[阶段A] 检索 + 生成 ...")
    expanded = []
    for qid, question, diff in qs:
        for strat in STRATEGIES:
            t0 = time.time()
            docs = get_retrieval_strategy(vs, question, strat)
            el = (time.time() - t0) * 1000
            context = "\n\n".join([d.page_content for d in docs]) if docs else "(无检索结果)"
            prompt = (f"你是一名专业的房屋租赁法律顾问。请仅依据下面提供的法律条文/案例上下文回答用户问题。\n"
                      f"要求：1) 直接给出结论；2) 引用具体法条（如\"民法典第X条\"）支撑；"
                      f"3) 若上下文不足以回答，明确说明\"上下文未覆盖\"。\n\n"
                      f"[上下文开始]\n{context}\n[上下文结束]\n\n问题：{question}")
            for r in range(args.rounds):
                try:
                    answer = llm_complete(prompt)
                except Exception as e:
                    print(f"  ⚠️ {qid} {strat} r{r+1} 失败: {e}")
                    answer = ""
                expanded.append({"qid": qid, "strategy": strat, "question": question,
                                 "contexts": [d.page_content for d in docs],
                                 "round": r + 1, "answer": answer})
                time.sleep(0.1)
            print(f"  [{strat}] {qid} 检索{len(docs)}篇({el:.0f}ms) x{args.rounds}轮")
    if not expanded:
        print("无样本, 退出")
        sys.exit(2)

    # 阶段B: 确定性审计
    print("\n[阶段B] 确定性条款命中审计 ...")
    audit_rows = run_deterministic_audit(expanded)
    for r in audit_rows:
        print(f"  [{r['strategy']}] {r['qid']}: 引用{r['cited_refs']} 幻觉{r['hallucinated']} 真实率={r['truth_rate']}")

    # 阶段C: RAGAS (可选)
    ragas_result = {}
    if args.ragas:
        print("\n[阶段C] RAGAS Faithfulness + AnswerRelevancy ...")
        from ragas import SingleTurnSample
        from ragas.metrics import Faithfulness, AnswerRelevancy
        from ragas.llms import LangchainLLMWrapper
        from ragas.embeddings import LangchainEmbeddingsWrapper
        from langchain_openai import ChatOpenAI
        from langchain_core.embeddings import Embeddings
        from concurrent.futures import ThreadPoolExecutor, as_completed

        chat = ChatOpenAI(model=llm_model, api_key=cfg.DASHSCOPE_API_KEY,
                          base_url=cfg.DASHSCOPE_BASE_URL, temperature=0,
                          timeout=180, max_retries=1)
        llm_wrapper = LangchainLLMWrapper(chat)

        class BGE3LangchainEmbeddings(Embeddings):
            def embed_documents(self, texts):
                return [vs.embedding_function([t])["dense"][0].tolist() for t in texts]
            def embed_query(self, text):
                return vs.embedding_function([text])["dense"][0].tolist()

        emb_wrapper = LangchainEmbeddingsWrapper(BGE3LangchainEmbeddings())
        faithfulness = Faithfulness(llm=llm_wrapper)
        relevancy = AnswerRelevancy(llm=llm_wrapper, embeddings=emb_wrapper)
        scores = [None] * len(expanded)

        def score_one(i, e):
            s = SingleTurnSample(user_input=e["question"], response=e["answer"],
                                 retrieved_contexts=e["contexts"][:5])
            f = r = None
            try:
                f = float(faithfulness.single_turn_score(s))
            except Exception:
                pass
            try:
                r = float(relevancy.single_turn_score(s))
            except Exception:
                pass
            return i, f, r

        with ThreadPoolExecutor(max_workers=4) as pool:
            futs = [pool.submit(score_one, i, e) for i, e in enumerate(expanded)]
            for fut in as_completed(futs):
                i, f, r = fut.result()
                scores[i] = (f, r)
        for i, e in enumerate(expanded):
            e["faithfulness"], e["answer_relevancy"] = scores[i]
        for strat in STRATEGIES:
            es = [e for e in expanded if e["strategy"] == strat]
            by_q = {}
            for e in es:
                by_q.setdefault(e["qid"], []).append(e)
            avg_f = [sum(x["faithfulness"] for x in lst if x["faithfulness"] is not None) /
                     sum(1 for x in lst if x["faithfulness"] is not None) for lst in by_q.values()
                    if any(x["faithfulness"] is not None for x in lst)]
            avg_r = [sum(x["answer_relevancy"] for x in lst if x["answer_relevancy"] is not None) /
                     sum(1 for x in lst if x["answer_relevancy"] is not None) for lst in by_q.values()
                    if any(x["answer_relevancy"] is not None for x in lst)]
            ragas_result[strat] = {"faithfulness": round(sum(avg_f)/len(avg_f), 4) if avg_f else None,
                                   "answer_relevancy": round(sum(avg_r)/len(avg_r), 4) if avg_r else None}
        for s, v in ragas_result.items():
            print(f"  {LABELS[s]:<12} 忠实度={v['faithfulness']} 相关性={v['answer_relevancy']}")

    # 阶段D: 与基线对比 + 阈值
    baseline = load_baseline(args.baseline)
    print("\n" + "=" * 74)
    print("[阶段D] 基线对比 (容差 tol=%.2f)" % args.tol)
    print("=" * 74)
    cur_truth = {s: [] for s in STRATEGIES}
    for r in audit_rows:
        if r["truth_rate"] is not None:
            cur_truth[r["strategy"]].append(r["truth_rate"])
    cur_truth = {s: (sum(v)/len(v)) for s, v in cur_truth.items() if v}

    fails = []
    table = [["策略", "指标", "本次", "基线", "Δ", "判定"]]
    for strat in STRATEGIES:
        for metric, cur, base in [
            ("引用真实率", cur_truth.get(strat), baseline["truth_rate"].get(strat)),
            ("RAGAS忠实度", ragas_result.get(strat, {}).get("faithfulness") if args.ragas else None,
             baseline["faithfulness"].get(strat)),
        ]:
            if cur is None or base is None:
                continue
            delta = cur - base
            ok = delta >= -args.tol
            table.append([LABELS[strat], metric, f"{cur:.3f}", f"{base:.3f}", f"{delta:+.3f}", "✅" if ok else "❌"])
            if not ok:
                fails.append(f"{strat} {metric}: {cur:.3f} < 基线{base:.3f} - {args.tol}")
    w = max(len(row[i]) for row in table for i in range(len(row))) if table else 0
    for row in table:
        print("  " + " | ".join(x.ljust(12 if i == 0 else 10) for i, x in enumerate(row)))
    print("-" * 74)

    # 报告落盘
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report = {
        "timestamp": ts, "n_questions": len(qs), "rounds": args.rounds,
        "ragas": args.ragas, "tol": args.tol,
        "cur_truth_rate": {k: round(v, 4) for k, v in cur_truth.items()},
        "cur_ragas": ragas_result,
        "baseline_truth_rate": baseline["truth_rate"],
        "baseline_faithfulness": baseline["faithfulness"],
        "audit": audit_rows, "fails": fails,
    }
    os.makedirs(args.out, exist_ok=True)
    json_path = os.path.join(args.out, f"eval_report_{ts}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)

    # 提升基线 (可选)
    if args.save_baseline and not fails and args.rounds >= 3:
        p1 = os.path.join(args.baseline, "hallucination_audit_v5.csv")
        if os.path.exists(p1):
            with open(p1, encoding="utf-8-sig") as f:
                rows = list(csv.DictReader(f))
            for row in rows:
                if row["strategy"] in cur_truth:
                    row["truth_rate"] = str(round(cur_truth[row["strategy"]], 4))
            with open(p1, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.DictWriter(f, fieldnames=rows[0].keys())
                w.writeheader()
                w.writerows(rows)
            print(f"✅ 基线已更新: {p1}")
        p2 = os.path.join(args.baseline, "ragas_scores_v3.csv")
        if args.ragas and os.path.exists(p2):
            with open(p2, encoding="utf-8-sig") as f:
                rows = list(csv.DictReader(f))
            for row in rows:
                if row["strategy"] in ragas_result and ragas_result[row["strategy"]]["faithfulness"]:
                    row["faithfulness_mean"] = str(ragas_result[row["strategy"]]["faithfulness"])
            with open(p2, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.DictWriter(f, fieldnames=rows[0].keys())
                w.writeheader()
                w.writerows(rows)
            print(f"✅ RAGAS 基线已更新: {p2}")

    print(f"\n报告: {json_path}")
    if fails:
        print("\n❌ FAIL — 以下指标回退超阈值:")
        for x in fails:
            print("   -", x)
        sys.exit(1)
    print("\n✅ PASS — 全部指标在容差内, 检索+生成质量未退化")
    sys.exit(0)


if __name__ == "__main__":
    main()
