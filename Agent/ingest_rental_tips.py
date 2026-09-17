#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
租房知识普及指南 入库脚本
- 解析《租房知识普及指南.md》，按章节/条目切分
- 用 BGE-M3 生成向量，存入 Milvus 集合（与法律条文同库）
- 供 web_server 的 house 意图伴随检索"租房常识"使用
用法: 先启动 Milvus，再执行本脚本
"""
import os
import sys
import re
import hashlib

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LEGAL_QA_DIR = os.path.join(BASE_DIR, 'legal_qa')
PROJECT_ROOT = os.path.dirname(BASE_DIR)
sys.path.insert(0, PROJECT_ROOT)  # 保证 Agent.legal_qa.* 绝对导入可用

from Agent.legal_qa.rag_qa.core.vector_store import VectorStore
from langchain_core.documents import Document

# 租房知识普及指南路径（相对项目根，兼容任意克隆路径：数据位于 数据集/法律条文/房租法）
MD_PATH = os.path.join(PROJECT_ROOT, '数据集', '法律条文', '房租法', '租房知识普及指南.md')


def parse_md(path):
    """按 ## 分节，节内按 数字. 条目切分，返回 list[Document]"""
    with open(path, 'r', encoding='utf-8') as f:
        text = f.read()
    docs = []
    sections = re.split(r'\n##\s+', text)
    for sec in sections[1:]:
        lines = sec.split('\n')
        sec_title = lines[0].strip()
        body = '\n'.join(lines[1:]).strip()
        items = re.split(r'\n(?=\d+\.\s)', body)
        for it in items:
            it = it.strip()
            if not it:
                continue
            content = f"{sec_title}\n{it}"
            metadata = {
                "source": "租房知识普及指南",
                "law_name": "租房知识普及指南",
                "chapter": sec_title,
                "article": "",
                "doc_type": "租房常识",
                "category": "房屋租赁",
                "parent_id": f"租房常识_{hashlib.md5(content.encode('utf-8')).hexdigest()[:8]}",
                "parent_content": content,
                "timestamp": "2026-09-02",
            }
            docs.append(Document(page_content=content, metadata=metadata))
    return docs


def main():
    print("=" * 60)
    print("租房知识普及指南 入库开始")
    print("=" * 60)

    print("\n[1/3] 初始化向量库（加载 BGE-M3 模型）...")
    vs = VectorStore()
    print(f"  集合: {vs.collection_name}  设备: {vs.device}")

    print("\n[2/3] 解析 md...")
    docs = parse_md(MD_PATH)
    print(f"  解析到 {len(docs)} 个条目")
    if not docs:
        print("  无内容，退出")
        return

    seen = set()
    unique_docs = []
    for doc in docs:
        h = hashlib.md5(doc.page_content.encode('utf-8')).hexdigest()
        if h not in seen:
            seen.add(h)
            unique_docs.append(doc)
    print(f"  去重后 {len(unique_docs)} 个")

    print("\n[3/3] 写入 Milvus...")
    vs.add_documents(unique_docs)
    print(f"入库完成！共写入 {len(unique_docs)} 条")

    print("\n" + "=" * 60)
    print("验证：测试检索")
    print("=" * 60)
    for test_query in ["租房前需要确认哪些事项 租客有哪些权益", "房东不退押金怎么办", "买卖不破租赁"]:
        results = vs.hybrid_search_with_rerank(test_query, k=3)
        print(f"\n查询: {test_query}")
        for i, doc in enumerate(results, 1):
            chapter = doc.metadata.get('chapter', '')
            print(f"  [{i}] {chapter} | {doc.page_content[:60]}...")


if __name__ == '__main__':
    main()
