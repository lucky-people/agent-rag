# -*- coding: utf-8 -*-
"""
替换 jpkb 问答对：备份原法律知识 → 清空 → 插入租房问答对 → 清理 Redis 缓存
用法：python replace_jpkb_data.py
注意：执行后需重启 legal_agent_server(5010) 与 web_server(8501)，BM25 才会用新问题集
"""
import sys
import os
import csv
import time

sys.path.insert(0, r'D:\heima_lesson\多智能体+RAG综合项目')
os.chdir(r'D:\heima_lesson\多智能体+RAG综合项目\Agent\legal_qa')

from Agent.legal_qa.mysql_qa.db.mysql_client import MySQLClient
from Agent.legal_qa.mysql_qa.cache.redis_client import RedisClient
from Agent.legal_qa.mysql_qa.data.rental_qa_data import RENTAL_QA

BACKUP_DIR = os.path.join(os.path.dirname(__file__), "data", "backup")
os.makedirs(BACKUP_DIR, exist_ok=True)


def backup_existing(mc):
    """备份现有 jpkb 数据到 CSV"""
    mc.cursor.execute("SELECT subject_name, question, answer FROM jpkb")
    rows = mc.cursor.fetchall()
    if not rows:
        print("  jpkb 表当前为空，无需备份")
        return
    ts = time.strftime("%Y%m%d_%H%M%S")
    path = os.path.join(BACKUP_DIR, f"jpkb_backup_{ts}.csv")
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["学科名称", "问题", "答案"])
        writer.writerows(rows)
    print(f"  ✅ 已备份 {len(rows)} 条原数据 -> {path}")


def clear_and_insert(mc):
    """清空 jpkb 并插入租房问答对"""
    mc.cursor.execute("DELETE FROM jpkb")
    mc.connection.commit()
    print("  ✅ 已清空 jpkb 表")

    sql = "INSERT INTO jpkb (subject_name, question, answer) VALUES (%s, %s, %s)"
    for subject, question, answer in RENTAL_QA:
        mc.cursor.execute(sql, (subject, question, answer))
    mc.connection.commit()
    print(f"  ✅ 已插入 {len(RENTAL_QA)} 条租房问答对")

    mc.cursor.execute("SELECT subject_name, COUNT(*) FROM jpkb GROUP BY subject_name")
    for row in mc.cursor.fetchall():
        print(f"     - {row[0]}: {row[1]} 条")


def clear_redis_cache(rc):
    """清理 BM25 问题缓存与答案缓存，确保走新数据"""
    keys = ["qa_original_questions", "qa_tokenized_questions"]
    for k in keys:
        try:
            rc.delete_data(k)
            print(f"  ✅ 已删除 Redis 键: {k}")
        except Exception as e:
            print(f"  ⚠️ 删除 {k} 失败: {e}")
    # 清理 answer:* 单条答案缓存
    try:
        rc.delete_data("answer:*") if hasattr(rc, "delete_data") else None
    except Exception:
        pass
    print("  ℹ️  提示: answer:* 与 rag_answer:* 缓存如需彻底清空，用 redis-cli 执行: redis-cli --scan --pattern 'answer:*' | xargs redis-cli del")


if __name__ == "__main__":
    print("=" * 50)
    print("开始替换 jpkb 问答对数据")
    print("=" * 50)
    mc = MySQLClient()
    rc = RedisClient()
    try:
        backup_existing(mc)
        clear_and_insert(mc)
        clear_redis_cache(rc)
    finally:
        mc.close()
    print("\n🎉 数据替换完成！")
    print("下一步：重启 legal_agent_server(5010) 与 web_server(8501)，让 BM25 重新加载租房问题集")
