# -*- coding: utf-8 -*-
"""一次性脚本：web_server.py 会话状态加固（过期清理 + history 写回锁内）"""
import io
import os
import subprocess
import sys

p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Agent', 'web_server.py')
with io.open(p, 'r', encoding='utf-8') as f:
    text = f.read()
n = 0

# ---- 1) sessions 增加 last_access + 过期清理 ----
old = '''sessions = {}           # session_id -> {network, llm, history, messages}
sessions_lock = threading.Lock()'''
new = '''sessions = {}           # session_id -> {network, llm, history, messages, last_access}
sessions_lock = threading.Lock()
SESSION_TTL = 3600     # 会话空闲过期时间（秒）：1小时无访问自动清理

def _cleanup_sessions():
    """清理空闲超时的会话，防止内存无限增长（重启后历史丢失属预期）。"""
    now = time.time()
    with sessions_lock:
        expired = [sid for sid, s in sessions.items()
                   if now - s.get("last_access", 0) > SESSION_TTL]
        for sid in expired:
            del sessions[sid]
        if expired:
            logger.info(f"已清理 {len(expired)} 个空闲超时会话")'''
if old in text:
    text = text.replace(old, new, 1)
    n += 1
    print('[sessions cleanup] OK')
else:
    print('[sessions cleanup] WARN')

# ---- 2) get_session 里记录 last_access ----
old = '''            sessions[session_id] = {
                "network": network,
                "llm": llm,
                "history": "",
                "messages": [],
            }
        return sessions[session_id]'''
new = '''            sessions[session_id] = {
                "network": network,
                "llm": llm,
                "history": "",
                "messages": [],
                "last_access": time.time(),
            }
        sessions[session_id]["last_access"] = time.time()
        return sessions[session_id]'''
if old in text:
    text = text.replace(old, new, 1)
    n += 1
    print('[last_access] OK')
else:
    print('[last_access] WARN')

# ---- 3) history 写回锁内：所有 sess["history"] += 统一加锁 ----
# 具体到本文件的 4 处（各在不同函数，模式相同但上下文不同，逐个替换）
replacements = [
    # process() 内
    ('    sess["history"] += f"\\nUser: {prompt}"\n',
     '    with sessions_lock:\n        sess["history"] += f"\\nUser: {prompt}"\n'),
    ('    sess["history"] += f"\\nAssistant: {response}"\n',
     '    with sessions_lock:\n        sess["history"] += f"\\nAssistant: {response}"\n'),
    # chat_stream() 内
    ('    sess["history"] += f"\\nUser: {message}"\n',
     '    with sessions_lock:\n        sess["history"] += f"\\nUser: {message}"\n'),
    # chat_stream 生成器内（out_of_scope 与最后两处）
    ('                sess["history"] += f"\\nAssistant: {reply}"\n',
     '                with sessions_lock:\n                    sess["history"] += f"\\nAssistant: {reply}"\n'),
]
for old_s, new_s in replacements:
    cnt = text.count(old_s)
    if cnt > 0:
        text = text.replace(old_s, new_s)
        n += cnt
        print(f'[history lock] x{cnt}: {old_s.strip()[:40]}')
    else:
        print('[history lock] WARN:', old_s.strip()[:40])

with io.open(p, 'w', encoding='utf-8', newline='') as f:
    f.write(text)

r = subprocess.run([sys.executable, '-m', 'py_compile', p], capture_output=True, text=True)
print('compile:', 'OK' if r.returncode == 0 else 'FAIL\n' + r.stderr[:500])
print('total changes:', n)
