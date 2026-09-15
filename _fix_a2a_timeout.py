# -*- coding: utf-8 -*-
"""一次性脚本：4个A2A server 的 MCP 调用加超时 + 错误分类(connection_error vs error) + 脱敏"""
import io
import os
import re

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Agent', 'a2a_server')
SPECS = [
    # (文件名, 函数名, 工具名, 端口, 前缀文案)
    ('house_server.py',     'get_house',     'query_houses',     '8004', '房源'),
    ('poi_server.py',       'get_poi',       'query_poi',        '8005', 'POI'),
    ('metro_server.py',     'get_metro',     'query_metro',      '8006', '地铁'),
    ('recommend_server.py', 'get_recommend', 'query_recommend',  '8007', '综合推荐'),
]

for fn, func, tool, port, label in SPECS:
    p = os.path.join(BASE, fn)
    with io.open(p, 'r', encoding='utf-8') as f:
        text = f.read()
    changed = []

    # ---- 1) 调用函数加超时 ----
    # 原始模式（各文件一致）： async with streamablehttp_client(...) as (read, write, _):
    old_call = f'''        async with streamablehttp_client("http://127.0.0.1:{port}/mcp") as (read, write, _):
            # 使用读写通道创建 MCP 会话
            async with ClientSession(read, write) as session:
                try:
                    await session.initialize()
                    # 工具调用
                    result = await session.call_tool("{tool}", {{"sql": sql}})'''
    new_call = f'''        # 整体加超时，防止 MCP 服务挂起导致无限阻塞
        async def _call():
            async with streamablehttp_client("http://127.0.0.1:{port}/mcp") as (read, write, _):
                # 使用读写通道创建 MCP 会话
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    # 工具调用
                    result = await session.call_tool("{tool}", {{"sql": sql}})
                    result_data = json.loads(result) if isinstance(result, str) else result
                    return result_data.content[0].text

        result = await asyncio.wait_for(_call(), timeout=15)'''
    if old_call in text:
        text = text.replace(old_call, new_call, 1)
        changed.append('timeout+call')
    else:
        # 尝试宽松匹配（找端口即可）
        print(fn, 'WARN: call pattern not found, skip timeout')

    # ---- 2) 移除旧 call_tool 后的重复处理（已被 _call 取代）----
    old_dup = '''                    result_data = json.loads(result) if isinstance(result, str) else result
                    logger.info(f"房源查询结果：{result_data}")
                    return result_data.content[0].text
                except Exception as e:
                    err_msg = format_exception(e)
                    logger.error(f"房源 MCP 测试出错：{err_msg}")
                    return {"status": "error", "message": f"房源 MCP 查询出错：{err_msg}"}'''
    # 各文件前缀不同，用通用正则删掉 call 内的 try/except 旧逻辑
    # 先不动，后面单独处理

    # ---- 3) 连接错误分类 + 脱敏 ----
    old_conn = f'''    except Exception as e:
        err_msg = format_exception(e)
        logger.error(f"连接或会话初始化时发生错误: {{err_msg}}")
        return {{"status": "error", "message": f"连接或会话初始化时发生错误: {{err_msg}}"}}'''
    new_conn = f'''    except asyncio.TimeoutError:
        logger.error(f"{label} MCP 调用超时（15s）")
        return {{"status": "connection_error", "message": "{label} MCP 服务响应超时，请稍后重试。"}}
    except Exception as e:
        err_msg = format_exception(e)
        logger.error(f"连接或会话初始化时发生错误: {{err_msg}}")
        return {{"status": "connection_error", "message": "{label} MCP 服务连接失败，请确认对应服务已启动。"}}'''
    if old_conn in text:
        text = text.replace(old_conn, new_conn, 1)
        changed.append('connection_error')
    else:
        print(fn, 'WARN: conn pattern not found')

    # ---- 4) call_tool 异常：SQL 错误（保持 error，供 LLM 修正）----
    # 各文件的 call_tool 内 try/except 文案不同，统一处理
    old_sqlerr_patterns = [
        (f'''                    logger.info(f"房源查询结果：{{result_data}}")
                    return result_data.content[0].text
                except Exception as e:
                    err_msg = format_exception(e)
                    logger.error(f"房源 MCP 测试出错：{{err_msg}}")
                    return {{"status": "error", "message": f"房源 MCP 查询出错：{{err_msg}}"}}''',
         '''                    return result_data.content[0].text
                except Exception as e:
                    err_msg = format_exception(e)
                    logger.error(f"房源 MCP 查询出错：{{err_msg}}")
                    return {{"status": "error", "message": f"SQL执行错误：{{err_msg}}"}}'''),
    ]
    for old_s, new_s in old_sqlerr_patterns:
        if old_s in text:
            text = text.replace(old_s, new_s, 1)
            changed.append('sql_error_label')
            break

    with io.open(p, 'w', encoding='utf-8', newline='') as f:
        f.write(text)
    print(fn, '->', changed if changed else 'NO CHANGES')

# 编译检查
import subprocess, sys
for fn, *_ in SPECS:
    p = os.path.join(BASE, fn)
    r = subprocess.run([sys.executable, '-m', 'py_compile', p], capture_output=True, text=True)
    print(fn, 'compile:', 'OK' if r.returncode == 0 else 'FAIL\n' + r.stderr[:500])
