# -*- coding: utf-8 -*-
"""从打分日志解析 70 个样本结果 + 跑确定性审计 + 汇总（修复后 v3 最终数据）"""
import os
import sys
import re
import json
import csv

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
RESULTS_DIR = os.path.join(PROJECT_ROOT, "实验脚本", "results")

# 1. 读原始样本（含 contexts）
with open(os.path.join(RESULTS_DIR, "ragas_raw_samples_v3.json"), encoding="utf-8") as f:
    data = json.load(f)
samples, expanded = data["samples"], data["expanded"]

# 2. 从日志解析打分
log_path = os.path.join(RESULTS_DIR, "ragas_scores_only.log")
log = open(log_path, encoding="utf-8").read()
score_map = {}  # (qid, strategy, round) -> (f, r)
for m in re.finditer(r"\[(\d+)/72\] (Q\d) (\S+) r(\d) f=([\d.]+|N/A) r=([\d.]+|N/A)", log):
    idx, qid, strat, rnd, f, r = m.groups()
    f = float(f) if f != "N/A" else None
    r = float(r) if r != "N/A" else None
    score_map[(qid, strat, int(rnd))] = (f, r)

scored = []
for e in expanded:
    key = (e["qid"], e["strategy"], e["round"])
    if key in score_map:
        e["faithfulness"], e["answer_relevancy"] = score_map[key]
    else:
        e["faithfulness"] = e["answer_relevancy"] = None
    scored.append(e)

with open(os.path.join(RESULTS_DIR, "ragas_v3_scored.json"), "w", encoding="utf-8") as f:
    json.dump(scored, f, ensure_ascii=False, indent=1)
print(f"解析完成: {sum(1 for s in scored if s['faithfulness'] is not None)}/72 faith, "
      f"{sum(1 for s in scored if s['answer_relevancy'] is not None)}/72 relev")

# 3. 确定性审计（v4 口径，复用 run_hallucination_audit_v4 逻辑）
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
        if ref_no in m.group(0) or ref_text in m.group(0):
            return True
    for pat in ("未覆盖", "未提供", "未出现", "未列出", "上下文未", "未包含"):
        for mm in re.finditer(pat, answer):
            s = max(0, mm.start() - 50)
            e = min(len(answer), mm.end() + 50)
            if ref_no in answer[s:e] or ref_text in answer[s:e]:
                return True
    return False


print("\n确定性条款命中审计（修复后）")
by_key = {}
for e in scored:
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
                pass
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
with open(os.path.join(RESULTS_DIR, "hallucination_audit_v5.csv"), "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["qid", "strategy", "cited_refs", "supported",
                                      "hallucinated", "truth_rate", "hallucination_rate"])
    w.writeheader()
    w.writerows(audit_rows)

# 4. 汇总
print("\n" + "=" * 70)
print("汇总（条款级重排修复后, 3 次生成均值）")
print("=" * 70)
ragas_rows = []
for strat in ["B_纯稠密", "C_混合无Rerank", "D_混合+Rerank"]:
    es = [e for e in scored if e["strategy"] == strat]
    by_q = {}
    for e in es:
        by_q.setdefault(e["qid"], []).append(e)
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
    ar = [a for a in audit_rows if a["strategy"] == strat and a["truth_rate"] != ""]
    hit = sum(float(a["truth_rate"]) for a in ar) / len(ar) if ar else None
    print(f"  {strat:<12} 忠实度={mf if mf is not None else 'N/A':.3f} 相关性={mr if mr is not None else 'N/A':.3f}"
          f" | 引用真实率={hit if hit is not None else 'N/A':.3f}"
          f" 幻觉率={1-hit if hit is not None else 'N/A':.3f}")
    ragas_rows.append({"strategy": strat,
                       "faithfulness_mean": round(mf, 4) if mf else "",
                       "answer_relevancy_mean": round(mr, 4) if mr else ""})
with open(os.path.join(RESULTS_DIR, "ragas_scores_v3.csv"), "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["strategy", "faithfulness_mean", "answer_relevancy_mean"])
    w.writeheader()
    w.writerows(ragas_rows)
print("\n完成 ✅")
