# -*- coding: utf-8 -*-
"""验证生产路径 Rerank 耗时: 项目自带 hybrid_search_with_rerank (CANDIDATE_M=2)"""
import os
import sys
import time
import warnings
warnings.filterwarnings("ignore")
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

QUESTIONS = [
    "房东拖延退押金可以要求利息赔偿吗",
    "租客提前退租需要承担什么责任",
    "租客可以装修房屋抵扣租金吗",
]

from Agent.legal_qa.rag_qa import VectorStore

vs = VectorStore()
print(f"设备: {vs.device}")

for q in QUESTIONS:
    t0 = time.time()
    docs = vs.hybrid_search_with_rerank(q)
    el = (time.time() - t0) * 1000
    print(f"  {q[:20]}... -> {len(docs)} 篇 | 生产路径耗时 {el:.1f} ms")
