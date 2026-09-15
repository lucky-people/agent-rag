# -*- coding: utf-8 -*-
"""一次性脚本：web_server 智能体调用加超时+降级（子Agent挂时LLM兜底，不直接报错）"""
import io
import os
import subprocess
import sys

p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Agent', 'web_server.py')
with io.open(p, 'r', encoding='utf-8') as f:
    text = f.read()

old = '''                agent = sess["network"].get_agent(agent_name)
                chat_history = '\\n'.join(sess["history"].split("\\n")[-7:-1]) + f'\\nUser: {query_str}'
                msg = Message(content=TextContent(text=chat_history), role=MessageRole.USER)
                task = Task(id="task-" + str(uuid.uuid4()), message=msg.to_dict())
                raw_response = asyncio.run(agent.send_task_async(task))
                logger.info(f"{agent_name} 原始响应: {raw_response}")
                agent_result = extract_agent_result(raw_response)'''

new = '''                agent = sess["network"].get_agent(agent_name)
                chat_history = '\\n'.join(sess["history"].split("\\n")[-7:-1]) + f'\\nUser: {query_str}'
                msg = Message(content=TextContent(text=chat_history), role=MessageRole.USER)
                task = Task(id="task-" + str(uuid.uuid4()), message=msg.to_dict())
                try:
                    # 子Agent调用带15s超时，防止挂起无限阻塞
                    raw_response = asyncio.run(asyncio.wait_for(agent.send_task_async(task), timeout=15))
                    logger.info(f"{agent_name} 原始响应: {raw_response}")
                    agent_result = extract_agent_result(raw_response)
                except asyncio.TimeoutError:
                    logger.warning(f"{agent_name} 调用超时（15s），启用降级回复")
                    agent_result = None
                except Exception as e:
                    logger.warning(f"{agent_name} 调用失败，启用降级回复: {str(e)}")
                    agent_result = None
                if agent_result is None or not agent_result.strip():
                    # === 降级：子Agent不可用时，用LLM生成友好兜底回复 ===
                    _degrade_prompt = (
                        "你是智租顾问的兜底助手。用户询问了关于租房的问题，但后台数据服务暂时不可用。\\n"
                        f"用户问题：{query_str}\\n"
                        "请用1-2句话友好说明服务正在恢复中，并给出一个通用的租房建议或引导用户稍后重试。"
                    )
                    try:
                        final_response = sess["llm"].invoke(_degrade_prompt).content.strip()
                    except Exception as e2:
                        logger.error(f"降级回复也失败: {str(e2)}")
                        final_response = "抱歉，后台数据服务暂时不可用，请稍后重试。"
                    add_trace_step(trace, agent_name, agent_name,
                                    input_data=query_str, output_data=final_response,
                                    start_time=agent_start, status="degraded")
                    all_responses.append(final_response)
                    for i in range(0, len(final_response), 8):
                        chunk = final_response[i:i+8]
                        safe = chunk.replace('\\\\', '\\\\\\\\').replace('"', '\\\\"').replace('\\n', '\\\\n')
                        yield f'data: {{"type":"token","content":"{safe}"}}\\n\\n'
                    continue'''

if old in text:
    text = text.replace(old, new, 1)
    print('[degrade] OK')
else:
    print('[degrade] WARN: pattern not found')

with io.open(p, 'w', encoding='utf-8', newline='') as f:
    f.write(text)
r = subprocess.run([sys.executable, '-m', 'py_compile', p], capture_output=True, text=True)
print('compile:', 'OK' if r.returncode == 0 else 'FAIL\\n' + r.stderr[:400])
