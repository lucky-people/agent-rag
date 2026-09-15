# -*- coding: utf-8 -*-
"""一次性脚本：
1. house/poi/metro: 清理重复的 getter/formatter 注入行（脚本重跑导致）
2. recommend_server: 从git恢复 → 重跑编排 → 精确删除三个重复方法（保留编排类）
"""
import io
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
A2A = os.path.join(BASE, 'Agent', 'a2a_server')

# ---------- 1) house/poi/metro 清理重复注入 ----------
for fn in ['house_server.py', 'poi_server.py', 'metro_server.py']:
    p = os.path.join(A2A, fn)
    with io.open(p, 'r', encoding='utf-8') as f:
        text = f.read()
    # 找到第一个 self.getter = 行，删除其后的重复块（getter+formatter+input_required_msg 三行成组重复）
    lines = text.split('\n')
    new_lines = []
    seen = set()
    for ln in lines:
        s = ln.strip()
        if s.startswith('self.getter = ') or s.startswith('self.formatter = ') or s.startswith('self.input_required_msg = '):
            if s in seen:
                continue   # 跳过重复
            seen.add(s)
        new_lines.append(ln)
    out = '\n'.join(new_lines)
    with io.open(p, 'w', encoding='utf-8', newline='') as f:
        f.write(out)
    r = subprocess.run([sys.executable, '-m', 'py_compile', p], capture_output=True, text=True)
    print(fn, 'dedup:', 'OK' if r.returncode == 0 else 'FAIL\n' + r.stderr[:300])

# ---------- 2) recommend_server: git恢复 + 编排 + 精确删方法 ----------
p = os.path.join(A2A, 'recommend_server.py')
subprocess.run(['git', 'checkout', '--', 'Agent/a2a_server/recommend_server.py'],
               cwd=BASE, check=True)
print('recommend_server: git restored')

# 2a) 重跑编排
subprocess.run([sys.executable, os.path.join(BASE, '_fix_orchestrator.py')], cwd=BASE, check=True)
print('recommend_server: orchestrator applied')

# 2b) 精确删除三个方法：从 "    # 定义生成SQL查询方法" 到编排注释块之前
with io.open(p, 'r', encoding='utf-8') as f:
    text = f.read()

start_marker = "    # 定义生成SQL查询方法"
start_idx = text.find(start_marker)
if start_idx == -1:
    print('recommend_server: WARN methods start not found')
else:
    # 编排注释锚点（在 orchestrator 注入后的实际文本）
    orch_marker = "\n\n# ============================================================\n# 编排增强"
    end_idx = text.find(orch_marker, start_idx)
    if end_idx == -1:
        print('recommend_server: WARN orchestrator anchor not found')
    else:
        text = text[:start_idx] + text[end_idx + 2:]
        with io.open(p, 'w', encoding='utf-8', newline='') as f:
            f.write(text)
        print('recommend_server: methods removed, orchestrator kept')

r = subprocess.run([sys.executable, '-m', 'py_compile', p], capture_output=True, text=True)
print('recommend_server compile:', 'OK' if r.returncode == 0 else 'FAIL\n' + r.stderr[:400])
