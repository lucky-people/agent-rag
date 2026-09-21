# -*- coding: utf-8 -*-
"""GPU 可行性验证: 加载 BGE-Reranker 到 GPU 并测单题耗时"""
import os
import sys
import time
import warnings
warnings.filterwarnings("ignore")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import torch
print(f"CUDA available: {torch.cuda.is_available()}")
if torch.cuda.is_available():
    print(f"GPU: {torch.cuda.get_device_name(0)}")
    print(f"显存: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.1f} GB")
    free, total = torch.cuda.mem_get_info(0)
    print(f"当前可用: {free / 1024**3:.2f} GB / {total / 1024**3:.1f} GB")

from Agent.legal_qa.rag_qa.core.vector_store import VectorStore

print("\n加载 VectorStore (GPU 模式)...")
start = time.time()
vs = VectorStore()
print(f"加载完成: {time.time() - start:.1f}s, device={vs.device}")

if torch.cuda.is_available():
    free, total = torch.cuda.mem_get_info(0)
    print(f"加载后可用显存: {free / 1024**3:.2f} GB")

# 测 Rerank 单题耗时（模拟 5 对 query-doc）
pairs = [["房东拖延退押金可以要求利息赔偿吗", "民法典 第五百八十八条 当事人既约定违约金，又约定定金的，一方违约时，对方可以选择适用违约金或者定金条款。"]] * 5
start = time.time()
scores = vs.reranker.predict(pairs)
print(f"\nRerank 5 对耗时: {(time.time()-start)*1000:.1f} ms（GPU）")
print(f"scores: {[round(float(s),4) for s in scores]}")

# 测 BGE-M3 embedding
start = time.time()
emb = vs.embedding_function(["房东拖延退押金可以要求利息赔偿吗"])
print(f"Embedding 1 条耗时: {(time.time()-start)*1000:.1f} ms（GPU）")
print(f"dense dim: {emb['dense'].shape}")
