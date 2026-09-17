# -*- coding: utf-8 -*-
"""
反思纠错案例实验（Agentic RAG 价值证据）
=====================================
目标: 用具体案例证明 Self-RAG 反思机制的价值——
     朴素 RAG 首轮答案证据不足/引用悬空 → Agentic 反思判定 supported=false
     → 改写查询重检 → 最终答案补全缺失证据。

对 6 道代表题分别运行:
  - 朴素 RAG  (agentic=False): 固定 pipeline，记录首轮答案/引用/耗时
  - Agentic RAG (agentic=True): Self-RAG 反思循环，记录每轮反思轨迹
    (queries/docs/supported/reason/missing/answer)

量化指标:
  - 反思触发率: 首轮 supported=false 的题数占比
  - 纠错成功率: 触发反思的题中，最终轮 supported=true 的占比
  - 纠错增益: LLM 对触发题的首轮 vs 最终答案对比打分（完整性/引用准确性）

输出:
  - results/reflection_cases.csv       每题汇总（耗时/轮次/触发/纠错）
  - results/reflection_cases_report.txt 完整案例报告（每轮轨迹原文）
"""
import os
import sys
import time
import csv
import json
import warnings

warnings.filterwarnings("ignore")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

RESULTS_DIR = os.path.join(PROJECT_ROOT, "实验脚本", "results")
os.makedirs(RESULTS_DIR, exist_ok=True)

TEST_QUESTIONS = [
    ("Q1_押金利息", "房东拖延退押金可以要求利息赔偿吗", "困难"),
    ("Q2_扣损坏押金", "房东以房屋有损坏为由扣全部押金合法吗", "中等"),
    ("Q3_提前退租责任", "租客提前退租需要承担什么责任", "中等"),
    ("Q4_卖房搬离", "房东卖房后租客能拒绝搬走吗", "中等"),
    ("Q5_装修抵租", "租客可以装修房屋抵扣租金吗", "困难"),
    ("Q6_漏水拒交", "房东拖延维修卫生间漏水可以拒交房租吗", "中等"),
]


def run_query(qa, question, agentic, clear_cache=True):
    """运行一次查询，返回 (耗时ms, 答案, 引用数, 反思轨迹dict)"""
    if clear_cache:
        try:
            qa.redis_client.client.delete(f"rag_answer:{question.strip()}")
        except Exception:
            pass
    start = time.time()
    collected = ""
    refs = []
    for item in qa.query(question, session_id=None, agentic=agentic):
        token = item[0]
        if token == "__REFERENCES__":
            if len(item) > 1:
                refs = item[1] or []
            continue
        if token:
            collected += token
    elapsed_ms = round((time.time() - start) * 1000, 1)
    trace = {}
    try:
        trace = qa.rag_system.last_agentic_trace or {}
    except Exception:
        trace = {}
    return elapsed_ms, collected, refs, trace


def main():
    print("=" * 70)
    print("反思纠错案例实验（Agentic RAG 价值证据）")
    print("=" * 70)
    print("初始化 RAG 系统（GPU，加载模型约 30-90s）...")
    from Agent.legal_qa.new_main import IntegratedQASystem
    from Agent.legal_qa.base.config import Config
    from openai import OpenAI

    qa = IntegratedQASystem()
    print("RAG 系统就绪")

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
            except Exception as e:
                if attempt < retries - 1:
                    print(f"    ⚠️ LLM 失败({e}) 重试 {attempt+2}")
                    time.sleep(2)
                else:
                    raise
        return ""

    rows = []
    report_lines = []
    report_lines.append("# 反思纠错案例报告（Agentic RAG 价值证据）\n")

    for qid, question, difficulty in TEST_QUESTIONS:
        print(f"\n--- {qid} [{difficulty}] {question} ---")
        report_lines.append(f"\n## {qid} [{difficulty}] {question}\n")

        # 朴素 RAG
        t0, ans0, refs0, _ = run_query(qa, question, agentic=False)
        print(f"  朴素RAG : {t0:>9.1f}ms | 答案{len(ans0)}字 | 引用{len(refs0)}条")

        # Agentic RAG
        t1, ans1, refs1, trace = run_query(qa, question, agentic=True)
        rounds = trace.get("rounds", [])
        print(f"  Agentic : {t1:>9.1f}ms | 答案{len(ans1)}字 | 引用{len(refs1)}条 | 反思{len(rounds)}轮")

        # 解析轨迹
        triggered = False          # 是否触发反思（有 supported=false）
        corrected = False          # 纠错成功（最终轮 supported=true）
        first_answer = ans0        # 首轮答案（朴素路径）
        final_answer = ans1        # 最终答案
        first_supported = None
        for rnd_i, r in enumerate(rounds):
            sup = r.get("supported")
            if rnd_i == 0:
                first_supported = sup
            if sup is False:
                triggered = True
            if rnd_i == len(rounds) - 1 and sup is True:
                corrected = True

        # 报告轨迹详情
        for r in rounds:
            report_lines.append(f"  - 第{r.get('round')}轮 | 检索词: {r.get('queries')} | 文档数: {r.get('docs')}")
            report_lines.append(f"    supported={r.get('supported')} | reason={r.get('reason')} | missing={r.get('missing')}")
            ans_r = r.get("answer", "")
            report_lines.append(f"    该轮答案({len(ans_r)}字): {ans_r[:200]}")
        report_lines.append(f"  [朴素RAG] 耗时{t0:.0f}ms 引用{len(refs0)}条 | 答案({len(ans0)}字): {ans0[:200]}")
        report_lines.append(f"  [Agentic] 耗时{t1:.0f}ms 反思{len(rounds)}轮 引用{len(refs1)}条 | 最终答案({len(ans1)}字): {ans1[:200]}")

        # 反思纠错的增益评判（仅触发反思的题）
        gain = None
        if triggered:
            judge_prompt = f"""请比较同一租房法律问题的两版 RAG 回答：{question}

[第一版（初始检索+生成）]
{ans0[:600]}

[第二版（Self-RAG 反思后改写重检的最终答案）]
{ans1[:600]}

请只输出三行：
完整性_第一版,完整性_第二版 (0-5)
引用准确性_第一版,引用准确性_第二版 (0-5)
是否改善(是/否)"""
            try:
                judge = llm_complete(judge_prompt, temperature=0.0)
                report_lines.append(f"\n  [增益评判] {judge}")
                gain = judge
            except Exception as e:
                print(f"    ⚠️ 增益评判失败: {e}")

        rows.append({
            "qid": qid, "question": question, "difficulty": difficulty,
            "naive_ms": t0, "naive_len": len(ans0), "naive_refs": len(refs0),
            "agentic_ms": t1, "agentic_len": len(ans1), "agentic_refs": len(refs1),
            "agentic_rounds": len(rounds), "first_supported": first_supported,
            "reflection_triggered": triggered, "corrected": corrected,
            "gain_judge": (gain or "").replace("\n", " | "),
        })

    # 保存
    csv_path = os.path.join(RESULTS_DIR, "reflection_cases.csv")
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"\n✅ {csv_path}")

    txt_path = os.path.join(RESULTS_DIR, "reflection_cases_report.txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))
    print(f"✅ {txt_path}")

    # 汇总
    n = len(rows)
    triggered_n = sum(1 for r in rows if r["reflection_triggered"])
    corrected_n = sum(1 for r in rows if r["reflection_triggered"] and r["corrected"])
    print("\n" + "=" * 70)
    print("汇总")
    print("=" * 70)
    print(f"  总题数: {n}")
    print(f"  触发反思(supported=false): {triggered_n}/{n}")
    print(f"  纠错成功(最终 supported=true): {corrected_n}/{triggered_n}")
    for r in rows:
        mark = "🔴触发反思" if r["reflection_triggered"] else "🟢直接通过"
        print(f"  {r['qid']:<12} 反思{r['agentic_rounds']}轮 | {mark} | 首轮supported={r['first_supported']}")

    print("\n完成")


if __name__ == "__main__":
    main()
