# -*- coding: utf-8 -*-
"""一次性脚本：
1. 闲聊路线 llm.invoke → llm.astream 真流式（逐 token 推送）
2. 4个 agent card capabilities streaming 改为 False（与服务端实现一致，避免声明未实现的诚信瑕疵）
"""
import io
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))

# ============ 1) web_server.py 闲聊真流式 ============
p = os.path.join(BASE, 'Agent', 'web_server.py')
with io.open(p, 'r', encoding='utf-8') as f:
    text = f.read()

old = '''                # === 通用对话路线：直接调用大模型，分块模拟流式 ===
                if agent_name == "ChatLLM":
                    route = "chat"
                    chat_start = time.time()
                    yield 'data: {"type":"start","route":"chat"}\\n\\n'
                    chat_prompt = f"你是一个友好的智能助手，请用简洁自然的中文回答用户问题。\\n用户问题：{query_str}"
                    chat_response = sess["llm"].invoke(chat_prompt).content.strip()
                    add_trace_step(trace, "ChatLLM", "通用对话LLM",
                                    input_data=query_str, output_data=chat_response,
                                    start_time=chat_start)
                    all_responses.append(chat_response)
                    # 分块推送（每 6 个字一个块，模拟流式效果）
                    for i in range(0, len(chat_response), 6):
                        chunk = chat_response[i:i+6]
                        safe = chunk.replace('\\\\', '\\\\\\\\').replace('"', '\\\\"').replace('\\n', '\\\\n')
                        yield f'data: {{"type":"token","content":"{safe}"}}\\n\\n'
                    continue'''

new = '''                # === 通用对话路线：LLM 真流式（astream 逐 token 推送） ===
                if agent_name == "ChatLLM":
                    route = "chat"
                    chat_start = time.time()
                    yield 'data: {"type":"start","route":"chat"}\\n\\n'
                    chat_prompt = f"你是一个友好的智能助手，请用简洁自然的中文回答用户问题。\\n用户问题：{query_str}"
                    chat_collected = []
                    # 真流式：直接消费 LLM 的 token 流，不再先收完整结果再切块
                    async def _chat_stream():
                        async for chunk in sess["llm"].astream(chat_prompt):
                            token_text = getattr(chunk, "content", "")
                            if token_text:
                                chat_collected.append(token_text)
                                safe = token_text.replace('\\\\', '\\\\\\\\').replace('"', '\\\\"').replace('\\n', '\\\\n')
                                yield f'data: {{"type":"token","content":"{safe}"}}\\n\\n'
                    try:
                        async for evt in _chat_stream():
                            yield evt
                    except Exception as e:
                        logger.error(f"闲聊流式输出异常: {str(e)}")
                        yield f'data: {{"type":"token","content":"（回答中断，请重试）"}}\\n\\n'
                    chat_response = "".join(chat_collected).strip()
                    add_trace_step(trace, "ChatLLM", "通用对话LLM",
                                    input_data=query_str, output_data=chat_response,
                                    start_time=chat_start)
                    all_responses.append(chat_response or "抱歉，暂时没有生成回答。")
                    continue'''

if old in text:
    text = text.replace(old, new, 1)
    print('[chat astream] OK')
else:
    print('[chat astream] WARN: pattern not found')

with io.open(p, 'w', encoding='utf-8', newline='') as f:
    f.write(text)
r = subprocess.run([sys.executable, '-m', 'py_compile', p], capture_output=True, text=True)
print('web_server compile:', 'OK' if r.returncode == 0 else 'FAIL\n' + r.stderr[:400])

# ============ 2) 4个 agent card streaming -> False ============
A2A = os.path.join(BASE, 'Agent', 'a2a_server')
for fn in ['house_server.py', 'poi_server.py', 'metro_server.py', 'recommend_server.py']:
    pp = os.path.join(A2A, fn)
    with io.open(pp, 'r', encoding='utf-8') as f:
        t = f.read()
    old_cap = 'capabilities={"streaming": True, "memory": True},  # 设置能力：支持流式和内存'
    new_cap = 'capabilities={"streaming": False, "memory": True},  # 服务端为同步处理，前端分块推送，不声明未实现的流式能力'
    if old_cap in t:
        t = t.replace(old_cap, new_cap, 1)
        with io.open(pp, 'w', encoding='utf-8', newline='') as f:
            f.write(t)
        print(fn, 'OK: streaming=False')
    else:
        print(fn, 'WARN: capability pattern not found')
