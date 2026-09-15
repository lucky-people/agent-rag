# -*- coding: utf-8 -*-
"""一次性脚本：给 format.py 增加 SQL 只读白名单校验函数"""
import io
import os

p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Agent', 'utils', 'format.py')
with io.open(p, 'r', encoding='utf-8') as f:
    text = f.read()

old = '''def format_exception(e):'''
new = '''# 禁止出现在查询 SQL 中的高危关键字（写操作/危险语句，大小写不敏感匹配）
_FORBIDDEN_SQL_KEYWORDS = [
    'INSERT', 'UPDATE', 'DELETE', 'DROP', 'ALTER', 'CREATE', 'TRUNCATE',
    'REPLACE', 'GRANT', 'REVOKE', 'RENAME', 'MERGE', 'CALL', 'EXEC',
    'INTO OUTFILE', 'INTO DUMPFILE', 'LOAD_FILE', 'SLEEP', 'BENCHMARK',
    'INFORMATION_SCHEMA', 'MYSQL.USER', 'SYSTEM_USER', 'SET @',
]


def validate_readonly_sql(sql):
    """校验 SQL 是否为安全的只读查询（SELECT/WITH 白名单）。

    返回 (ok, message)：
    - ok=True 表示可安全执行，message 为补过 LIMIT 的 SQL
    - ok=False 时 message 为拒绝原因

    规则：
    1. 必须以 SELECT / WITH 开头（忽略前导空白与注释）
    2. 不含写操作、系统表、危险函数等黑名单关键字
    3. 自动追加 LIMIT 兜底（防全表扫描）
    """
    s = (sql or '').strip()
    if not s:
        return False, "SQL为空"
    # 去掉可能的前导注释（--、#、/* */）
    s_clean = re.sub(r'^(?:\\s*--[^\\n]*|\\s*#[^\\n]*|\\s*/\\*.*?\\*/)+', '', s, flags=re.S).strip()
    if not re.match(r'^(SELECT|WITH)\\b', s_clean, re.IGNORECASE):
        return False, "仅允许SELECT/WITH只读查询，拒绝执行: " + sql[:80]
    for kw in _FORBIDDEN_SQL_KEYWORDS:
        # 用词边界匹配关键字（避免把 community 误判成 DELETE 之类）
        if re.search(r'\\b' + re.escape(kw) + r'\\b', s_clean, re.IGNORECASE):
            return False, "SQL包含危险关键字[" + kw + "]，已拒绝: " + sql[:80]
    return True, ensure_limit(sql)


def format_exception(e):'''

if old in text:
    text = text.replace(old, new, 1)
    with io.open(p, 'w', encoding='utf-8', newline='') as f:
        f.write(text)
    print('format.py OK: validate_readonly_sql added')
else:
    print('WARN: anchor not found')
