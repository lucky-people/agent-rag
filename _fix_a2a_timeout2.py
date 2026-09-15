# -*- coding: utf-8 -*-
"""一次性脚本：4个A2A server 的 MCP 调用加超时 + 错误分类 + 脱敏（精确模式版）"""
import io
import os
import subprocess
import sys

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Agent', 'a2a_server')
SPECS = [
    ('house_server.py',     'get_house',     'query_houses',    '8004', '房源'),
    ('poi_server.py',       'get_poi',       'query_poi',       '8005', 'POI'),
    ('metro_server.py',     'get_metro',     'query_metro',     '8006', '地铁'),
    ('recommend_server.py', 'get_recommend', 'query_recommend', '8007', '综合推荐'),
]

for fn, func, tool, port, label in SPECS:
    p = os.path.join(BASE, fn)
    with io.open(p, 'r', encoding='utf-8') as f:
        text = f.read()

    # ---- 整个 get_xxx 函数体替换 ----
    old_body = f'''# 定义查询函数
async def {func}(sql):
    try:
        # 启动 MCP server，通过streamable建立连接
        async with streamablehttp_client("http://127.0.0.1:{port}/mcp") as (read, write, _):
            # 使用读写通道创建 MCP 会话
            async with ClientSession(read, write) as session:
                try:
                    await session.initialize()
                    # 工具调用
                    result = await session.call_tool("{tool}", {{"sql": sql}})
                    result_data = json.loads(result) if isinstance(result, str) else result
                    logger.info(f"{label}查询结果：{{result_data}}")
                    return result_data.content[0].text
                except Exception as e:
                    err_msg = format_exception(e)
                    logger.error(f"{label} MCP 测试出错：{{err_msg}}")
                    return {{"status": "error", "message": f"{label} MCP 查询出错：{{err_msg}}"}}
    except Exception as e:
        err_msg = format_exception(e)
        logger.error(f"连接或会话初始化时发生错误: {{err_msg}}")
        return {{"status": "error", "message": f"连接或会话初始化时发生错误: {{err_msg}}"}}'''

    new_body = f'''# 定义查询函数
async def {func}(sql):
    """调用 MCP 查询，带 15s 超时；区分连接错误(connection_error)与SQL错误(error)。

    - connection_error：MCP 服务未启动/超时，属基础设施故障，上层不应让 LLM 误以为是 SQL 写错
    - error：SQL 执行层面的错误，上层可交给 LLM 修正重试
    """
    async def _call():
        # 启动 MCP server，通过streamable建立连接
        async with streamablehttp_client("http://127.0.0.1:{port}/mcp") as (read, write, _):
            # 使用读写通道创建 MCP 会话
            async with ClientSession(read, write) as session:
                await session.initialize()
                # 工具调用
                result = await session.call_tool("{tool}", {{"sql": sql}})
                result_data = json.loads(result) if isinstance(result, str) else result
                return result_data.content[0].text

    try:
        return await asyncio.wait_for(_call(), timeout=15)
    except asyncio.TimeoutError:
        logger.error(f"{label} MCP 调用超时（15s）")
        return {{"status": "connection_error", "message": "{label} 服务响应超时，请稍后重试。"}}
    except Exception as e:
        err_msg = format_exception(e)
        logger.error(f"连接或会话初始化时发生错误: {{err_msg}}")
        return {{"status": "connection_error", "message": "{label} 服务连接失败，请确认对应服务已启动。"}}'''

    if old_body in text:
        text = text.replace(old_body, new_body, 1)
        print(fn, 'OK: timeout+error-classification wired')
    else:
        print(fn, 'WARN: body pattern not found — 打印实际片段供排查')
        i = text.find('async def ' + func)
        print(repr(text[i:i+600]))

    with io.open(p, 'w', encoding='utf-8', newline='') as f:
        f.write(text)

# 编译检查
for fn, *_ in SPECS:
    p = os.path.join(BASE, fn)
    r = subprocess.run([sys.executable, '-m', 'py_compile', p], capture_output=True, text=True)
    print(fn, 'compile:', 'OK' if r.returncode == 0 else 'FAIL\n' + r.stderr[:500])
