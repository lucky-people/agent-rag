# -*- coding: utf-8 -*-
"""验证 4 个 a2a server 抽象后的结构一致性"""
import io, os, re

A2A = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Agent', 'a2a_server')
files = ['house_server.py', 'poi_server.py', 'metro_server.py', 'recommend_server.py']
ok = True
for fn in files:
    p = os.path.join(A2A, fn)
    t = io.open(p, encoding='utf-8').read()
    cls = re.search(r'class (\w+Server)\((\w+)\):', t)
    getter_n = t.count('self.getter = ')
    formatter_n = t.count('self.formatter = ')
    methods_n = len(re.findall(r'def (generate_sql_query|regenerate_sql|handle_task)', t))
    streaming = 'streaming": False' in t
    orch = 'Orchestrated' in t
    print(f'{fn}: 类={cls.group(1)}->{cls.group(2)} getter={getter_n} formatter={formatter_n} 残留方法={methods_n} streaming=False={streaming} 编排类={orch}')
    if cls.group(2) != 'Text2SqlAgentServer':
        ok = False
    if getter_n != 1 or formatter_n != 1:
        ok = False
    if methods_n != 0:
        ok = False
    if not streaming:
        ok = False
print('\n总验证:', 'PASS' if ok else 'FAIL')
