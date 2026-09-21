# -*- coding: utf-8 -*-
"""
Agentic RAG vs 朴素 RAG 端到端对比评估
=====================================
对同一批测试问题分别运行:
  - 朴素 RAG  (agentic=False): 固定 pipeline (BM25 + 向量 + Rerank + LLM)
  - Agentic RAG (agentic=True): Self-RAG 反思循环 (检索规划 + 生成 + 自检 + 改写重检)
对比维度: 端到端耗时 / 答案长度 / 引用条数 / 反思轮数 / 回答成功率

注意: 会真实调用 LLM API (qwen-plus)，产生少量费用。
输出: scripts/results/agentic_vs_naive.csv + summary
"""
import os
import sys
import time
import csv
import warnings

warnings.filterwarnings("ignore")

# 强制 CPU（规避本机 CUDA 崩溃）
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")
os.environ.setdefault("PYTORCH_NO_CUDA", "1")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

RESULTS_DIR = os.path.join(PROJECT_ROOT, "scripts", "results")
os.makedirs(RESULTS_DIR, exist_ok=True)

# 代表性测试问题（含消融实验中的高难度/低命中问题，体现反思价值）
TEST_QUESTIONS = [
    ("Q1_押金利息", "房东拖延退押金可以要求利息赔偿吗", "困难"),
    ("Q2_扣损坏押金", "房东以房屋有损坏为由扣全部押金合法吗", "中等"),
    ("Q3_提前退租责任", "租客提前退租需要承担什么责任", "中等"),
    ("Q4_卖房搬离", "房东卖房后租客能拒绝搬走吗", "中等"),
    ("Q5_装修抵租", "租客可以装修房屋抵扣租金吗", "困难"),
    ("Q6_漏水拒交", "房东拖延维修卫生间漏水可以拒交房租吗", "中等"),
]


def run_query(qa, question, agentic, clear_cache=False):
    """运行一次查询，返回 (耗时ms, 答案文本, 引用数, 反思轮数)"""
    if clear_cache:
        try:
            qa.redis_client.client.delete(f"rag_answer:{question.strip()}")
        except Exception:
            pass
    start = time.time()
    collected = ""
    refs = []
    trace = {}
    for item in qa.query(question, session_id=None, agentic=agentic):
        token = item[0]
        if token == "__REFERENCES__":
            if len(item) > 1:
                refs = item[1] or []
            continue
        if token:
            collected += token
    elapsed_ms = round((time.time() - start) * 1000, 1)
    # 取反思轨迹
    try:
        trace = qa.rag_system.last_agentic_trace or {}
    except Exception:
        trace = {}
    rounds = len(trace.get("rounds", [])) if trace else 0
    return elapsed_ms, collected, len(refs), rounds


def is_success(answer):
    """粗判回答是否成功: 非空且不是占位/错误文案"""
    if not answer or not answer.strip():
        return False
    bad = ["抱歉", "未找到答案", "处理您的专业咨询问题时出错", "请联系人工客服"]
    return not any(b in answer for b in bad)


def main():
    print("=" * 60)
    print("Agentic RAG vs 朴素 RAG 端到端对比")
    print("=" * 60)
    print("初始化 RAG 系统（加载模型，约 30-90s）...")
    from Agent.legal_qa.new_main import IntegratedQASystem
    qa = IntegratedQASystem()
    print("RAG 系统就绪\n")

    rows = []
    for qid, question, difficulty in TEST_QUESTIONS:
        print(f"--- {qid} [{difficulty}] {question} ---")

        # 朴素 RAG（清除缓存，走真实全链路）
        t0, ans0, refs0, rounds0 = run_query(qa, question, agentic=False, clear_cache=True)
        ok0 = is_success(ans0)
        print(f"  朴素RAG : {t0:>9.1f}ms | 答案{len(ans0)}字 | 引用{refs0}条 | 成功={ok0}")

        # Agentic RAG（清除缓存，走真实反思流程）
        t1, ans1, refs1, rounds1 = run_query(qa, question, agentic=True, clear_cache=True)
        ok1 = is_success(ans1)
        print(f"  Agentic : {t1:>9.1f}ms | 答案{len(ans1)}字 | 引用{refs1}条 | 反思{rounds1}轮 | 成功={ok1}")

        rows.append({
            "qid": qid, "question": question, "difficulty": difficulty,
            "naive_ms": t0, "naive_len": len(ans0), "naive_refs": refs0, "naive_success": ok0,
            "agentic_ms": t1, "agentic_len": len(ans1), "agentic_refs": refs1,
            "agentic_rounds": rounds1, "agentic_success": ok1,
        })
        print()

    # 汇总
    n = len(rows)
    naive_ms = sum(r["naive_ms"] for r in rows) / n
    agentic_ms = sum(r["agentic_ms"] for r in rows) / n
    naive_ok = sum(1 for r in rows if r["naive_success"]) / n
    agentic_ok = sum(1 for r in rows if r["agentic_success"]) / n
    naive_refs = sum(r["naive_refs"] for r in rows) / n
    agentic_refs = sum(r["agentic_refs"] for r in rows) / n
    avg_rounds = sum(r["agentic_rounds"] for r in rows) / n

    print("=" * 60)
    print("汇总统计")
    print("=" * 60)
    print(f"  朴素 RAG : 平均耗时 {naive_ms:.0f}ms | 成功率 {naive_ok:.0%} | 平均引用 {naive_refs:.1f}条")
    print(f"  Agentic  : 平均耗时 {agentic_ms:.0f}ms | 成功率 {agentic_ok:.0%} | 平均引用 {agentic_refs:.1f}条 | 平均反思 {avg_rounds:.1f}轮")
    print(f"  成功率提升: {agentic_ok - naive_ok:+.0%}")

    # 保存
    csv_path = os.path.join(RESULTS_DIR, "agentic_vs_naive.csv")
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"\n详细结果: {csv_path}")

    # 保存答案文本便于人工核验
    ans_path = os.path.join(RESULTS_DIR, "agentic_vs_naive_answers.txt")
    with open(ans_path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(f"### {r['qid']} [{r['difficulty']}] {r['question']}\n")
            f.write(f"[朴素RAG] 耗时{r['naive_ms']}ms 引用{r['naive_refs']}条 成功={r['naive_success']}\n")
            f.write(f"[Agentic] 耗时{r['agentic_ms']}ms 反思{r['agentic_rounds']}轮 引用{r['agentic_refs']}条 成功={r['agentic_success']}\n\n")
    print(f"答案详情: {ans_path}")


if __name__ == "__main__":
    main()
