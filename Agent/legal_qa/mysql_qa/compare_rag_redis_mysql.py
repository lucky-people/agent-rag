# -*- coding: utf-8 -*-
"""
三链路响应时长对比测试脚本
  A. MySQL(BM25) 链路: 问题在 jpkb 表（BM25 命中 >= 0.85）→ 直接返回库中答案
  B. Redis 缓存链路 : 问题不在 jpkb，但 RAG 跑过后答案被缓存（rag_answer:*）→ 秒回
  C. RAG 全链路     : 问题不在 jpkb 且无缓存 → BM25 + 向量 + Rerank + LLM 生成

用法:
  1. 先跑 `python compare_rag_redis_mysql.py --warm` 预热 Redis 缓存组（每个问题走一次 RAG 生成缓存）
  2. 再跑 `python compare_rag_redis_mysql.py` 正式对比（RAG 组每次用新问题避免命中缓存）
输出: 控制台表格 + results/chain_compare.csv
"""
import sys
import os
import time
import csv
import argparse

sys.path.insert(0, r'D:\heima_lesson\多智能体+RAG综合项目')
os.chdir(r'D:\heima_lesson\多智能体+RAG综合项目\Agent\legal_qa')

from Agent.legal_qa.new_main import IntegratedQASystem
from Agent.legal_qa.base.config import Config
import redis

# ==================== 测试问题组 ====================
# A 组: 必须与 jpkb 表中问题高度一致（保证 BM25 命中）
MYSQL_QUESTIONS = [
    "房东不退押金怎么办？",
    "押金和定金有什么区别？",
    "房屋维修费应该由谁承担？",
    "房东可以扣押租客身份证吗？",
    "群租房合法吗？",
    "房东可以随意涨房租吗？",
    "物业费一般由谁交？",
    "退租要提前多久通知房东？",
]

# B 组: 不在 jpkb 表中, 但适合走 RAG 的租房法律问题（先 --warm 预热生成缓存）
REDIS_QUESTIONS = [
    "房东拖欠退还押金我可以要求利息赔偿吗",
    "租房合同到期后房东不续租需要提前通知吗",
    "中介隐瞒房屋真实情况租客能要求退中介费吗",
    "房东以房屋有损坏为由扣全部押金合法吗",
    "租客可以自己装宽带并让房东报销吗",
]

# C 组: 每次用新问题, 保证走完整 RAG 链路（不命中缓存）
RAG_QUESTIONS = [
    "房东把房子抵押给银行还不上贷款房子被拍卖租客怎么办",
    "租客发现房子有严重噪音污染影响睡眠可以要求退租吗",
    "租客发现卫生间漏水房东拖延不修可以拒交房租吗",
    "租客在阳台违规搭建被物业处罚责任谁来承担",
    "租客在房间里私自安装大功率电器导致线路跳闸损失谁负责",
]


def measure(qa, question, warm=False):
    """调用 QA 系统, 返回 (耗时ms, 答案前80字, 是否命中缓存标记)"""
    start = time.time()
    collected = ""
    cache_hit = False
    for item in qa.query(question, session_id=None, agentic=False):
        token = item[0]
        if token == "__REFERENCES__":
            continue
        if token:
            collected += token
        if len(item) > 1 and item[1]:
            cache_hit = True  # (answer, True) 标记: 一次性返回（缓存或 MySQL 直答）
    elapsed_ms = round((time.time() - start) * 1000, 1)
    return elapsed_ms, collected[:60], cache_hit


def warm_cache(qa):
    """预热: 让 B 组问题走一次 RAG, 生成 rag_answer:* 缓存"""
    print("=" * 60)
    print("预热阶段: B 组问题走 RAG 生成缓存...")
    print("=" * 60)
    for q in REDIS_QUESTIONS:
        elapsed, head, _ = measure(qa, q)
        print(f"  [预热] {elapsed:>8.1f}ms | {head}...")


def clear_rag_cache_for(questions):
    """删除指定问题的 rag_answer:* 缓存, 确保 C 组每次走真实 RAG"""
    cfg = Config()
    r = redis.StrictRedis(host=cfg.REDIS_HOST, port=cfg.REDIS_PORT,
                          password=cfg.REDIS_PASSWORD, db=cfg.REDIS_DB, decode_responses=True)
    n = 0
    for q in questions:
        n += r.delete(f"rag_answer:{q}")
    print(f"  🧹 已清除 {n} 个 RAG 答案缓存键（C 组将走真实 RAG 全链路）")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--warm", action="store_true", help="先预热 Redis 缓存再对比")
    args = parser.parse_args()

    print("初始化 RAG 系统（加载 BM25/向量库/BERT 分类器，约 30-90s）...")
    qa = IntegratedQASystem()
    print("RAG 系统就绪\n")

    if args.warm:
        warm_cache(qa)
        print("\n预热完成, 现在可正式对比: python compare_rag_redis_mysql.py\n")
        return

    results = []
    print("=" * 70)
    print("三链路响应时长对比")
    print("=" * 70)

    # 预热: 先发一条通用问题, 触发 BM25/向量库/分类器初始化, 不计入统计
    print("\n[预热] 触发组件初始化(不计时)...")
    measure(qa, "你好", warm=True)

    # A: MySQL 链路（先清除 answer:* 缓存, 保证走真实 BM25+数据库查询）
    print("\n--- A. MySQL(BM25) 链路 ---")
    clear_rag_cache_for(MYSQL_QUESTIONS)  # 复用删除逻辑, 清 answer:* 需单独处理
    cfg = Config()
    r = redis.StrictRedis(host=cfg.REDIS_HOST, port=cfg.REDIS_PORT,
                          password=cfg.REDIS_PASSWORD, db=cfg.REDIS_DB, decode_responses=True)
    n = 0
    for q in MYSQL_QUESTIONS:
        n += r.delete(f"answer:{q}")
    print(f"  🧹 已清除 {n} 个 answer 缓存键（A 组将走真实 BM25→MySQL 查询）")
    for q in MYSQL_QUESTIONS:
        elapsed, head, hit = measure(qa, q)
        results.append(("A.MySQL", q, elapsed, hit))
        print(f"  {elapsed:>8.1f}ms | 命中MySQL={hit} | {head}...")

    # B: Redis 链路（需已预热）
    print("\n--- B. Redis 缓存链路 ---")
    for q in REDIS_QUESTIONS:
        elapsed, head, hit = measure(qa, q)
        results.append(("B.Redis", q, elapsed, hit))
        print(f"  {elapsed:>8.1f}ms | 命中缓存={hit} | {head}...")

    # C: RAG 全链路（先清除 C 组缓存, 保证走真实链路）
    print("\n--- C. RAG 全链路 ---")
    clear_rag_cache_for(RAG_QUESTIONS)
    for q in RAG_QUESTIONS:
        elapsed, head, hit = measure(qa, q)
        results.append(("C.RAG", q, elapsed, hit))
        print(f"  {elapsed:>8.1f}ms | 命中缓存={hit} | {head}...")

    # 汇总
    print("\n" + "=" * 70)
    print("汇总统计（平均耗时）")
    print("=" * 70)
    for tag in ["A.MySQL", "B.Redis", "C.RAG"]:
        items = [r for r in results if r[0] == tag]
        if items:
            avg = sum(r[2] for r in items) / len(items)
            print(f"  {tag:<10} 平均 {avg:>8.1f} ms  ({len(items)} 条)")

    os.makedirs("results", exist_ok=True)
    out = os.path.join("results", "chain_compare.csv")
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["链路", "问题", "耗时ms", "是否直答/缓存"])
        w.writerows(results)
    print(f"\n详细结果已保存: {out}")


if __name__ == "__main__":
    main()
