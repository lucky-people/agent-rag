# -*- coding: utf-8 -*-
"""确定性条款命中审计 v4 —— 修正幻觉口径
幻觉 = 引用条款不在上下文 且 答案未声明"上下文未覆盖/未提供"
      (Agentic 设计允许诚实标注缺失证据; 标注不算幻觉, 未标注的编造才算)
复用 ragas_v2_expanded.json, 纯本地计算
"""
import os
import sys
import csv
import json
import re

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS_DIR = os.path.join(PROJECT_ROOT, "实验脚本", "results")
LABELS = {"B_纯稠密": "B 纯稠密", "C_混合无Rerank": "C 混合检索", "D_混合+Rerank": "D 混合+Rerank"}
HONEST_PATTERNS = ["未覆盖", "未提供", "未出现", "未列出", "上下文未", "无相关条文", "未包含"]


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
    """提取'第X条'引用 → [(原文, 归一化号)]"""
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
    """答案是否对这条引用声明了'上下文未覆盖/未提供'"""
    # 在答案中找含'未覆盖/未提供'等字样的句子, 看该句/附近是否提到该条款
    for m in re.finditer(r"[^。\n]{0,60}(?:未覆盖|未提供|未出现|未列出|上下文未|未包含)[^。\n]{0,40}", answer):
        snippet = m.group(0)
        if ref_no in snippet or ref_text in snippet:
            return True
    # 兜底: 条款号紧邻声明词
    for pat in HONEST_PATTERNS:
        for mm in re.finditer(pat, answer):
            s = max(0, mm.start() - 50)
            e = min(len(answer), mm.end() + 50)
            seg = answer[s:e]
            if ref_no in seg or ref_text in seg:
                return True
    return False


def main():
    with open(os.path.join(RESULTS_DIR, "ragas_v2_expanded.json"), encoding="utf-8") as f:
        expanded = json.load(f)
    samples = {}
    for e in expanded:
        samples.setdefault((e["qid"], e["strategy"]), []).append(e)

    print("确定性条款命中审计 v4（诚实标注不算幻觉）")
    audit_rows = []
    for (qid, strat), rounds in sorted(samples.items()):
        full_context = "\n".join(rounds[0]["contexts"])
        round_stats = []
        union_cited, union_supported, union_unsupported = set(), set(), set()
        for r in rounds:
            refs = extract_article_refs(r["answer"])
            cited, sup, unsup, noted = set(), set(), set(), set()
            for raw, no in refs:
                cited.add(no)
                if is_article_in_context(no, full_context):
                    sup.add(no)
                elif is_honestly_noted(raw, no, r["answer"]):
                    noted.add(no)  # 诚实标注缺失证据
                else:
                    unsup.add(no)  # 未标注的编造 = 真幻觉
            union_cited |= cited
            union_supported |= sup
            union_unsupported |= unsup
            if cited:
                # 幻觉率 = 未标注的编造 / 全部引用
                hallu = len(unsup) / len(cited)
                round_stats.append(1 - hallu)
        avg_truth = sum(round_stats) / len(round_stats) if round_stats else None
        hallu_rate = len(union_unsupported) / len(union_cited) if union_cited else None
        audit_rows.append({
            "qid": qid, "strategy": strat,
            "cited_refs": len(union_cited),
            "supported": len(union_supported),
            "honest_noted": len({no for r in rounds for raw, no in extract_article_refs(r["answer"])
                                 if no not in union_supported and is_honestly_noted(raw, no, r["answer"])}),
            "hallucinated": len(union_unsupported),
            "truth_rate": round(avg_truth, 4) if avg_truth is not None else "",
            "hallucination_rate": round(hallu_rate, 4) if hallu_rate is not None else "",
        })
        print(f"  [{strat}] {qid}: 引用{len(union_cited)}条 命中{len(union_supported)} "
              f"诚实标注{audit_rows[-1]['honest_noted']} 幻觉{len(union_unsupported)} "
              f"| 真实率={avg_truth if avg_truth is not None else 'N/A'}")

    with open(os.path.join(RESULTS_DIR, "hallucination_audit_v4.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["qid", "strategy", "cited_refs", "supported",
                                          "honest_noted", "hallucinated", "truth_rate", "hallucination_rate"])
        w.writeheader()
        w.writerows(audit_rows)

    print("\n" + "=" * 70)
    print("汇总（幻觉率 = 未标注的编造引用 / 全部引用）")
    print("=" * 70)
    for strat in ["B_纯稠密", "C_混合无Rerank", "D_混合+Rerank"]:
        ar = [a for a in audit_rows if a["strategy"] == strat and a["truth_rate"] != ""]
        hallu = [a for a in audit_rows if a["strategy"] == strat and a["hallucination_rate"] != ""]
        tr = sum(float(a["truth_rate"]) for a in ar) / len(ar) if ar else None
        hr = sum(float(a["hallucination_rate"]) for a in hallu) / len(hallu) if hallu else None
        print(f"  {LABELS[strat]:<12} 引用真实率={tr:.3f} 幻觉率={hr:.3f} ({len(ar)}题)")
    print("完成 ✅")


if __name__ == "__main__":
    main()
