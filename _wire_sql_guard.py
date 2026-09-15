# -*- coding: utf-8 -*-
"""一次性脚本：4个MCP server 接入 SQL 只读白名单校验"""
import io
import os

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Agent', 'mcp_server')
FILES = ['mcp_house_server.py', 'mcp_poi_server.py', 'mcp_metro_server.py', 'mcp_recommend_server.py']

for fn in FILES:
    p = os.path.join(BASE, fn)
    with io.open(p, 'r', encoding='utf-8') as f:
        text = f.read()

    # 1) import 增加 validate_readonly_sql
    old_imp = "from Agent.utils.format import DateEncoder, default_encoder, ensure_limit"
    new_imp = "from Agent.utils.format import DateEncoder, default_encoder, ensure_limit, validate_readonly_sql"
    if old_imp in text:
        text = text.replace(old_imp, new_imp, 1)
    else:
        print(fn, 'WARN: import not found')

    # 2) execute_query 里先用白名单校验
    old_exec = """    def execute_query(self, sql: str) -> str:
        try:
            cursor = self.conn.cursor(dictionary=True)
            cursor.execute(ensure_limit(sql))
            results = cursor.fetchall()"""
    new_exec = """    def execute_query(self, sql: str) -> str:
        try:
            # 只读白名单校验：仅允许 SELECT/WITH，拒绝写操作与危险语句
            ok, safe_sql = validate_readonly_sql(sql)
            if not ok:
                logger.warning(f"SQL白名单校验拒绝: {safe_sql}")
                return json.dumps({"status": "error", "message": safe_sql}, ensure_ascii=False)
            cursor = self.conn.cursor(dictionary=True)
            cursor.execute(safe_sql)
            results = cursor.fetchall()"""
    if old_exec in text:
        text = text.replace(old_exec, new_exec, 1)
        print(fn, 'OK: validate_readonly_sql wired')
    else:
        print(fn, 'WARN: execute_query pattern not found')

    with io.open(p, 'w', encoding='utf-8', newline='') as f:
        f.write(text)

# 编译检查
import subprocess, sys
for fn in FILES:
    p = os.path.join(BASE, fn)
    r = subprocess.run([sys.executable, '-m', 'py_compile', p], capture_output=True, text=True)
    print(fn, 'compile:', 'OK' if r.returncode == 0 else 'FAIL ' + r.stderr[:200])
