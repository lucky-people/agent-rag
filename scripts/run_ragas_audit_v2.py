# -*- coding: utf-8 -*-
"""
RAGAS 标准基准交叉验证 + 确定性幻觉率审计 (v2)
================================================
v1 教训:
  1. 单次生成噪声大 (Q6/Q7 的 D 答案误写"上下文未覆盖", 拉低 faithfulness)
     → 每(题,策略) 生成 3 次, RAGAS 按 3 个样本取均值
  2. LLM 审计会误判 (Q8 引用明明在上下文, 审计 LLM 判 false)
     → 幻觉审计改为【确定性条款命中校验】: 提取答案引用的条款号,
       归一化(中文数字→阿拉伯)后在完整上下文中做字符串匹配, 客观可复现
  3. RAGAS 上下文不可截断 (截断会切掉法条导致误判)

复用 v1 阶段 A 的检索上下文 (ragas_raw_samples.json, 8题×3策略 Top-5),
只重新生成答案并计算, 节省检索时间。
输出:
  results/ragas_scores_v2.csv          RAGAS 三策略 (3次生成均值)
  results/hallucination_audit_v2.csv   确定性引用命中率
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
RESULTS_DIR = os.path.join(PROJECT_ROOT, "scripts", "results")
GEN_ROUNDS = 3
LABELS = {"B_纯稠密": "B 纯稠密", "C_混合无Rerank": "C 混合检索", "D_混合+Rerank": "D 混合+Rerank"}


def cn_num_to_arabic(s):
    """中文数字片段 → 阿拉伯数字字符串"""
    digits = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    units = {"十": 10, "百": 100, "千": 1000}
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
    """提取文本中所有'第X条'/'第X条X款'引用 → 归一化条款号列表"""
    refs = set()
    # 中文数字与阿拉伯数字条款
    for m in re.finditer(r"第\s*([一二三四五六七八九十百千零〇两0-9]+)\s*条", text):
        raw = m.group(1).replace(" ", "")
        if raw.isdigit():
            refs.add(str(int(raw)))
        else:
            num = cn_num_to_arabic(raw)
            if num:
                refs.add(num)
    return refs


def is_article_in_context(article_no, context):
    """确定性校验: 归一化后的条款号(如'725')是否出现在上下文中"""
    # 直接搜阿拉伯形式 '第725条'
    if f"第{article_no}条" in context:
        return True
    # 上下文可能用中文数字, 归一化上下文条款再比 (只对候选行, 避免误匹配)
    for m in re.finditer(r"第\s*([一二三四五六七八九十百千零〇两]+)\s*条", context):
        if cn_num_to_arabic(m.group(1)) == article_no:
            return True
    return False


def main():
    print("=" * 70)
    print("RAGAS 标准基准交叉验证 + 确定性幻觉审计 (v2, 3次生成均值)")
    print("=" * 70)

    # 1. 复用 v1 检索上下文
    raw_path = os.path.join(RESULTS_DIR, "ragas_raw_samples.json")
    with open(raw_path, encoding="utf-8") as f:
        samples = json.load(f)
    print(f"复用检索上下文: {len(samples)} 样本 (8题×3策略)")

    # 2. LLM
    from Agent.legal_qa.base.config import Config
    from openai import OpenAI
    cfg = Config()
    llm_client = OpenAI(api_key=cfg.DASHSCOPE_API_KEY, base_url=cfg.DASHSCOPE_BASE_URL)
    llm_model = cfg.LLM_MODEL

    def llm_complete(prompt, temperature=0.2, retries=3):
        for attempt in range(retries):
            try:
                resp = llm_client.chat.completions.create(
                    model=llm_model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=temperature,
                )
                return resp.choices[0].message.content.strip()
            except Exception:
                if attempt < retries - 1:
                    time.sleep(3)
                else:
                    raise
        return ""

    # 3. 每样本生成 GEN_ROUNDS 次
    print(f"\n阶段 A：{GEN_ROUNDS} 次生成 ({len(samples)}×{GEN_ROUNDS}={len(samples)*GEN_ROUNDS} 答案)")
    expanded = []  # 每个元素: 原样本 + round + answer
    for s in samples:
        context = "\n\n".join(s["contexts"]) if s["contexts"] else "(无检索结果)"
        prompt = f"""你是一名专业的房屋租赁法律顾问。请仅依据下面提供的法律条文/案例上下文回答用户问题。
要求：1) 直接给出结论；2) 引用具体法条（如"民法典第X条"/"住房租赁条例第X条"）支撑；3) 若上下文不足以回答，明确说明"上下文未覆盖"。

[上下文开始]
{context}
[上下文结束]

问题：{s['question']}"""
        for r in range(GEN_ROUNDS):
            try:
                answer = llm_complete(prompt, temperature=0.3)
            except Exception as e:
                print(f"  ⚠️ {s['qid']} {s['strategy']} r{r+1} 失败: {e}")
                answer = ""
            expanded.append({**s, "round": r + 1, "answer": answer})
            time.sleep(0.15)
        print(f"  [{s['strategy']}] {s['qid']} 3次生成完成")
    with open(os.path.join(RESULTS_DIR, "ragas_v2_expanded.json"), "w", encoding="utf-8") as f:
        json.dump(expanded, f, ensure_ascii=False, indent=1)

    # 4. RAGAS (上下文不截断)
    print("\n阶段 B：RAGAS Faithfulness + AnswerRelevancy")
    from ragas import EvaluationDataset, SingleTurnSample, evaluate
    from ragas.metrics import Faithfulness, AnswerRelevancy
    from ragas.llms import LangchainLLMWrapper
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from langchain_openai import ChatOpenAI
    from langchain_core.embeddings import Embeddings
    from Agent.legal_qa.rag_qa import VectorStore

    vs = VectorStore()
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
        SingleTurnSample(
            user_input=e["question"], response=e["answer"],
            retrieved_contexts=e["contexts"][:5],  # 不截断
        ) for e in expanded
    ])
    result = evaluate(ds, metrics=[
        Faithfulness(llm=llm_wrapper),
        AnswerRelevancy(llm=llm_wrapper, embeddings=emb_wrapper),
    ])
    pdf = result.to_pandas()
    for i, e in enumerate(expanded):
        row = pdf.iloc[i]
        e["faithfulness"] = float(row.get("faithfulness", 0))
        e["answer_relevancy"] = float(row.get("answer_relevancy", 0))
    print(f"  ✅ RAGAS 完成 ({len(expanded)} 样本)")

    # 5. 确定性幻觉审计
    print("\n阶段 C：确定性条款命中校验")
    audit_rows = []
    for s in samples:
        rounds = [e for e in expanded if e["qid"] == s["qid"] and e["strategy"] == s["strategy"]]
        full_context = "\n".join(s["contexts"])
        cited_sets = [extract_article_refs(r["answer"]) for r in rounds]
        all_cited = set().union(*cited_sets) if cited_sets else set()
        supported = {a for a in all_cited if is_article_in_context(a, full_context)}
        # 每轮独立命中率
        round_rates = []
        for r in rounds:
            refs = extract_article_refs(r["answer"])
            if refs:
                hits = sum(1 for a in refs if is_article_in_context(a, full_context))
                round_rates.append(hits / len(refs))
        hit_rate = sum(round_rates) / len(round_rates) if round_rates else None
        audit_rows.append({
            "qid": s["qid"], "strategy": s["strategy"],
            "cited_refs_union": len(all_cited), "supported_refs_union": len(supported),
            "union_hit_rate": round(len(supported) / len(all_cited), 4) if all_cited else "",
            "avg_round_hit_rate": round(hit_rate, 4) if hit_rate is not None else "",
            "hallucination_rate": round(1 - hit_rate, 4) if hit_rate is not None else "",
        })
        print(f"  [{s['strategy']}] {s['qid']}: 引用并集{len(all_cited)}条 命中{len(supported)}条 "
              f"平均命中率={hit_rate if hit_rate is not None else 'N/A'}")
    with open(os.path.join(RESULTS_DIR, "hallucination_audit_v2.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["qid", "strategy", "cited_refs_union", "supported_refs_union",
                                          "union_hit_rate", "avg_round_hit_rate", "hallucination_rate"])
        w.writeheader()
        w.writerows(audit_rows)

    # 6. 汇总
    print("\n" + "=" * 70)
    print("汇总 (3 次生成均值)")
    print("=" * 70)
    ragas_rows = []
    for strat in ["B_纯稠密", "C_混合无Rerank", "D_混合+Rerank"]:
        es = [e for e in expanded if e["strategy"] == strat]
        by_q = {}
        for e in es:
            by_q.setdefault(e["qid"], []).append(e)
        avg_f, avg_r = [], []
        for qid, lst in by_q.items():
            avg_f.append(sum(e["faithfulness"] for e in lst) / len(lst))
            avg_r.append(sum(e["answer_relevancy"] for e in lst) / len(lst))
        mf, mr = sum(avg_f) / len(avg_f), sum(avg_r) / len(avg_r)
        ar = [a for a in audit_rows if a["strategy"] == strat and a["avg_round_hit_rate"] != ""]
        hit = sum(float(a["avg_round_hit_rate"]) for a in ar) / len(ar) if ar else None
        print(f"  {LABELS[strat]:<12} 忠实度={mf:.3f} 相关性={mr:.3f}"
              f"  | 引用命中率={hit:.3f} 幻觉率={1-hit:.3f}" if hit else
              f"  {LABELS[strat]:<12} 忠实度={mf:.3f} 相关性={mr:.3f} | 引用命中率=N/A")
        ragas_rows.append({"strategy": strat, "faithfulness_mean": round(mf, 4),
                           "answer_relevancy_mean": round(mr, 4)})
    with open(os.path.join(RESULTS_DIR, "ragas_scores_v2.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["strategy", "faithfulness_mean", "answer_relevancy_mean"])
        w.writeheader()
        w.writerows(ragas_rows)
    print("\n完成 ✅")


if __name__ == "__main__":
    main()
