# -*- coding: utf-8 -*-
"""RAGAS 打分 v2（4 路并行 + timeout=180, 复用 v3 已生成答案）
faith 慢调用(timeout=180) + 4 路线程并行, 72 样本约 40-50 分钟
"""
import os
import sys
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
RESULTS_DIR = os.path.join(PROJECT_ROOT, "scripts", "results")

from Agent.legal_qa.base.config import Config
from Agent.legal_qa.rag_qa import VectorStore

cfg = Config()
vs = VectorStore()

from ragas import SingleTurnSample
from ragas.metrics import Faithfulness, AnswerRelevancy
from ragas.llms import LangchainLLMWrapper
from ragas.embeddings import LangchainEmbeddingsWrapper
from langchain_openai import ChatOpenAI
from langchain_core.embeddings import Embeddings

chat = ChatOpenAI(model=cfg.LLM_MODEL, api_key=cfg.DASHSCOPE_API_KEY,
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
answer_relevancy = AnswerRelevancy(llm=llm_wrapper, embeddings=emb_wrapper)

with open(os.path.join(RESULTS_DIR, "ragas_raw_samples_v3.json"), encoding="utf-8") as f:
    data = json.load(f)
expanded = data["expanded"]
print(f"共 {len(expanded)} 样本, 4 路并行打分", flush=True)

_print_lock = threading.Lock()
results = [None] * len(expanded)


def score_one(i, e):
    sample = SingleTurnSample(user_input=e["question"], response=e["answer"],
                              retrieved_contexts=e["contexts"][:5])
    fth = rel = None
    try:
        fth = float(faithfulness.single_turn_score(sample))
    except Exception as ex:
        with _print_lock:
            print(f"  ⚠️ {e['qid']} {e['strategy']} r{e['round']} faith 失败: {type(ex).__name__}: {str(ex)[:60]}", flush=True)
    try:
        rel = float(answer_relevancy.single_turn_score(sample))
    except Exception as ex:
        with _print_lock:
            print(f"  ⚠️ {e['qid']} {e['strategy']} r{e['round']} relev 失败: {type(ex).__name__}: {str(ex)[:60]}", flush=True)
    e["faithfulness"] = fth
    e["answer_relevancy"] = rel
    with _print_lock:
        done = sum(1 for r in results if r is not None)
        print(f"  [{done+1}/{len(expanded)}] {e['qid']} {e['strategy']} r{e['round']} f={fth if fth is not None else 'N/A'} r={rel if rel is not None else 'N/A'}", flush=True)
    return i, e


with ThreadPoolExecutor(max_workers=4) as pool:
    futures = [pool.submit(score_one, i, e) for i, e in enumerate(expanded)]
    for fut in as_completed(futures):
        i, e = fut.result()
        results[i] = e

# 按原顺序保存
ordered = [r for r in results if r is not None]
with open(os.path.join(RESULTS_DIR, "ragas_v3_scored.json"), "w", encoding="utf-8") as f:
    json.dump(ordered, f, ensure_ascii=False, indent=1)

print("=" * 60, flush=True)
for strat in ["B_纯稠密", "C_混合无Rerank", "D_混合+Rerank"]:
    es = [r for r in ordered if r["strategy"] == strat]
    by_q = {}
    for r in es:
        by_q.setdefault(r["qid"], []).append(r)
    avg_f, avg_r = [], []
    for qid, lst in by_q.items():
        fs = [x["faithfulness"] for x in lst if x["faithfulness"] is not None]
        rs = [x["answer_relevancy"] for x in lst if x["answer_relevancy"] is not None]
        if fs:
            avg_f.append(sum(fs) / len(fs))
        if rs:
            avg_r.append(sum(rs) / len(rs))
    mf = sum(avg_f) / len(avg_f) if avg_f else None
    mr = sum(avg_r) / len(avg_r) if avg_r else None
    print(f"  {strat:<12} 忠实度={mf if mf is not None else 'N/A'} 相关性={mr if mr is not None else 'N/A'}", flush=True)
print("完成 ✅", flush=True)
