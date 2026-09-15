# -*- coding: utf-8 -*-
"""一次性脚本：把 web_server.py 中坏版本的闲聊流式替换为线程+队列真流式"""
import io
import os
import subprocess
import sys

p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Agent', 'web_server.py')
with io.open(p, 'r', encoding='utf-8') as f:
    text = f.read()

old = '''                # === 通用对话路线：LLM 真流式（astream 逐 token 推送） ===
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

new = '''                # === 通用对话路线：LLM 真流式（astream 逐 token 推送） ===
                if agent_name == "ChatLLM":
                    route = "chat"
                    chat_start = time.time()
                    yield 'data: {"type":"start","route":"chat"}\\n\\n'
                    chat_prompt = f"你是一个友好的智能助手，请用简洁自然的中文回答用户问题。\\n用户问题：{query_str}"
                    # 后台线程消费 LLM token 流 → 队列逐条投递给 SSE 生成器，实现首字低延迟的真流式
                    import queue as _queue
                    _evt_q = _queue.Queue()
                    _chat_collected = []

                    def _chat_worker():
                        async def _run():
                            async for chunk in sess["llm"].astream(chat_prompt):
                                token_text = getattr(chunk, "content", "")
                                if token_text:
                                    _chat_collected.append(token_text)
                                    safe = token_text.replace('\\\\', '\\\\\\\\').replace('"', '\\\\"').replace('\\n', '\\\\n')
                                    _evt_q.put(f'data: {{"type":"token","content":"{safe}"}}\\n\\n')
                        try:
                            asyncio.run(_run())
                        except Exception as e:
                            logger.error(f"闲聊流式输出异常: {str(e)}")
                            _evt_q.put(f'data: {{"type":"token","content":"（回答中断，请重试）"}}\\n\\n')
                        finally:
                            _evt_q.put(None)   # 结束哨兵

                    threading.Thread(target=_chat_worker, daemon=True).start()
                    while True:
                        evt = _evt_q.get()
                        if evt is None:
                            break
                        yield evt
                    chat_response = "".join(_chat_collected).strip()
                    add_trace_step(trace, "ChatLLM", "通用对话LLM",
                                    input_data=query_str, output_data=chat_response,
                                    start_time=chat_start)
                    all_responses.append(chat_response or "抱歉，暂时没有生成回答。")
                    continue'''

if old in text:
    text = text.replace(old, new, 1)
    print('[chat true-streaming] OK')
else:
    print('[chat true-streaming] WARN: pattern not found')

with io.open(p, 'w', encoding='utf-8', newline='') as f:
    f.write(text)
r = subprocess.run([sys.executable, '-m', 'py_compile', p], capture_output=True, text=True)
print('compile:', 'OK' if r.returncode == 0 else 'FAIL\n' + r.stderr[:400])
