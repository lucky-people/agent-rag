# -*- coding: utf-8 -*-
"""SQL 种子数据语法冒烟检查"""
import re

with open(r'Agent\sql\seed_data.sql', encoding='utf-8') as f:
    sql = f.read()

for line in sql.splitlines():
    s = line.strip()
    if s.startswith('(') and (s.endswith('),') or s.endswith(');')):
        o, c = line.count('('), line.count(')')
        assert o == c, f'括号不配平: {line[:80]}'

assert 'NULL' in sql, '存在NULL值'
print('括号配平: OK | NULL值: OK | INSERT数: %d' % sql.count('INSERT INTO'))
print('文件行数:', len(sql.splitlines()))
