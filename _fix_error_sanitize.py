# -*- coding: utf-8 -*-
"""一次性脚本：web_server.py 错误信息脱敏（不向用户暴露内部细节）"""
import io
import os
import subprocess
import sys

p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Agent', 'web_server.py')
with io.open(p, 'r', encoding='utf-8') as f:
    text = f.read()

# 1) agent 调用失败：只给通用提示，详细错误进日志
old1 = '''            except Exception as e:
                add_trace_step(trace, agent_name, agent_name,
                                input_data=query_str, output_data=str(e),
                                status="error", error_msg=str(e),
                                start_time=agent_start)
                responses.append(f"{agent_name}调用失败：{str(e)}")'''
new1 = '''            except Exception as e:
                logger.error(f"{agent_name} 调用异常: {str(e)}")
                add_trace_step(trace, agent_name, agent_name,
                                input_data=query_str, output_data="调用异常（详见日志）",
                                status="error", error_msg=str(e),
                                start_time=agent_start)
                # 脱敏：不向用户暴露内部异常细节（路径/地址/堆栈），只给通用提示
                responses.append(f"{agent_name}暂时不可用，请稍后重试或换个说法。")'''
if old1 in text:
    text = text.replace(old1, new1, 1)
    print('[agent-fail] OK')
else:
    print('[agent-fail] WARN: not found')

# 2) 顶层处理失败：日志保留完整异常，回复脱敏
old2 = '''    except Exception as e:
        logger.error(f"处理异常: {str(e)}")
        reply = f"处理失败：{str(e)}。请重试。"
        intents = []
        route = "error"
        trace = None'''
new2 = '''    except Exception as e:
        logger.error(f"处理异常: {str(e)}")
        reply = "处理失败，请稍后重试或换个说法。"
        intents = []
        route = "error"
        trace = None'''
if old2 in text:
    text = text.replace(old2, new2, 1)
    print('[top-fail] OK')
else:
    print('[top-fail] WARN: not found')

with io.open(p, 'w', encoding='utf-8', newline='') as f:
    f.write(text)

r = subprocess.run([sys.executable, '-m', 'py_compile', p], capture_output=True, text=True)
print('compile:', 'OK' if r.returncode == 0 else 'FAIL\n' + r.stderr[:300])
