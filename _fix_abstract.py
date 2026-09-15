# -*- coding: utf-8 -*-
"""一次性脚本：4个 a2a server 改为继承 Text2SqlAgentServer 基类（消除 generate_sql_query/regenerate_sql/handle_task 重复）"""
import io
import os
import re
import subprocess
import sys

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Agent', 'a2a_server')

# 每个文件的差异配置：(文件名, 端口, 工具名, 追问文案, 服务器类名, 旧类父类)
SPECS = [
    ("house_server.py", 8004, "query_houses",
     "查询无效，请提供区域、租金或地铁等房源条件。",
     "HouseQueryServer", "A2AServer"),
    ("poi_server.py", 8005, "query_poi",
     "查询无效，请提供周边探索条件（如地点、类型、线路）。",
     "PoiQueryServer", "A2AServer"),
    ("metro_server.py", 8006, "query_metro",
     "查询无效，请提供地铁站名或附近地标。",
     "MetroQueryServer", "A2AServer"),
    ("recommend_server.py", 8007, "query_recommend",
     "查询无效，请提供综合推荐条件。",
     "RecommendQueryServer", "A2AServer"),
]

def rewrite(fn, port, tool, msg, cls_name, _old_parent):
    p = os.path.join(BASE, fn)
    with io.open(p, 'r', encoding='utf-8') as f:
        text = f.read()

    # 1) import 增加基类
    old_imp = "from python_a2a import "
    # 统一在 recommend_server 的复杂 import 与 house/poi/metro 简单 import 前插入基类导入
    base_imp = "from Agent.a2a_server.base_text2sql_server import Text2SqlAgentServer\n"
    if "base_text2sql_server" in text:
        print(fn, "skip import (already)")
    else:
        # 插到 from python_a2a 行之前
        anchor = "from python_a2a import"
        idx = text.find(anchor)
        if idx == -1:
            print(fn, "WARN: python_a2a import not found")
        else:
            text = text[:idx] + base_imp + text[idx:]
            print(fn, "import OK")

    # 2) 类定义改为继承基类 + __init__ 注入差异
    old_cls = f"class {cls_name}(A2AServer):"
    new_cls = f"class {cls_name}(Text2SqlAgentServer):"
    if old_cls in text:
        text = text.replace(old_cls, new_cls, 1)
        print(fn, "class OK")
    else:
        print(fn, "WARN: class def not found")

    # 3) __init__ 追加基类字段（getter/formatter/input_required_msg）
    #    在 self.schema = table_schema_string 之后插入
    key = fn.split("_")[0]
    old_init = "        self.schema = table_schema_string"
    new_init = old_init + "\n        self.getter = get_%s\n        self.formatter = format_%s_rows\n        self.input_required_msg = \"%s\"" % (key, key, msg)
    if old_init in text:
        text = text.replace(old_init, new_init, 1)
        print(fn, "init OK")
    else:
        print(fn, "WARN: init anchor not found")

    # 4) 删除 generate_sql_query / regenerate_sql / handle_task 三个方法（从"    # 定义生成SQL查询方法"到类结束前的最后一段）
    #    用正则：从 generate_sql_query 注释行 到 handle_task 方法结束（类内最后一个 return task）
    #    策略：找到 "    # 定义生成SQL查询方法" 起点，到 handle_task 的结尾（"            return task" 后跟两个空行 + if __name__ 或 class 结束）
    start_marker = "    # 定义生成SQL查询方法"
    start_idx = text.find(start_marker)
    if start_idx == -1:
        print(fn, "WARN: methods start not found")
        with io.open(p, 'w', encoding='utf-8', newline='') as f:
            f.write(text)
        return

    # 找方法块的结束：类内最后一个 "            return task" 之后，遇到 "\n\n\nif __name__" 或文件尾
    # handle_task 的 except 块后是 "            return task\n" 然后 "\n\n\nif __name__"
    end_marker = "\n\nif __name__"
    end_idx = text.find(end_marker, start_idx)
    if end_idx == -1:
        # recommend_server 后面有编排类，锚点改为编排类前的空行
        end_marker2 = "\n\n\n# ============================================================\n# 编排增强"
        end_idx = text.find(end_marker2, start_idx)
    if end_idx == -1:
        print(fn, "WARN: methods end not found")
        with io.open(p, 'w', encoding='utf-8', newline='') as f:
            f.write(text)
        return

    # 删除方法块，但保留 handle_task 结束后的两个空行
    text = text[:start_idx] + text[end_idx + 2:]  # 保留 "\n\nif __name__" 前面的一个空行
    with io.open(p, 'w', encoding='utf-8', newline='') as f:
        f.write(text)
    print(fn, "methods removed")

    r = subprocess.run([sys.executable, '-m', 'py_compile', p], capture_output=True, text=True)
    print(fn, 'compile:', 'OK' if r.returncode == 0 else 'FAIL\n' + r.stderr[:400])


for fn, port, tool, msg, cls, parent in SPECS:
    rewrite(fn, port, tool, msg, cls, parent)
