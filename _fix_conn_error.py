# -*- coding: utf-8 -*-
"""一次性脚本：4个A2A server handle_task 增加 connection_error 处理（直接失败不喂LLM）"""
import io
import os
import subprocess
import sys

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Agent', 'a2a_server')
FILES = ['house_server.py', 'poi_server.py', 'metro_server.py', 'recommend_server.py']

old_branch = '''                elif response.get("status") == "error":
                    # P1-3：SQL 执行报错 → 反馈给 LLM 修正后重试
                    if attempt < max_attempts:'''
new_branch = '''                elif response.get("status") == "connection_error":
                    # 基础设施故障（MCP未启动/超时）→ 直接失败，不浪费 LLM 调用去"修正SQL"
                    task.status = TaskStatus(state=TaskState.FAILED,
                                             message={"role": "agent",
                                                      "content": {"text": response.get("message", "服务暂不可用，请稍后重试。")}})
                    return task
                elif response.get("status") == "error":
                    # P1-3：SQL 执行报错 → 反馈给 LLM 修正后重试
                    if attempt < max_attempts:'''

for fn in FILES:
    p = os.path.join(BASE, fn)
    with io.open(p, 'r', encoding='utf-8') as f:
        text = f.read()
    if old_branch in text:
        text = text.replace(old_branch, new_branch, 1)
        with io.open(p, 'w', encoding='utf-8', newline='') as f:
            f.write(text)
        print(fn, 'OK: connection_error branch added')
    else:
        print(fn, 'WARN: branch pattern not found')
    r = subprocess.run([sys.executable, '-m', 'py_compile', p], capture_output=True, text=True)
    print(fn, 'compile:', 'OK' if r.returncode == 0 else 'FAIL\n' + r.stderr[:300])
