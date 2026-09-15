# -*- coding: utf-8 -*-
"""一次性脚本：recommend_server 补 class 继承与 init 注入"""
import io
import os
import subprocess
import sys

p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Agent', 'a2a_server', 'recommend_server.py')
with io.open(p, 'r', encoding='utf-8') as f:
    text = f.read()

# 1) class 继承
old = "class RecommendQueryServer(A2AServer):"
new = "class RecommendQueryServer(Text2SqlAgentServer):"
if old in text:
    text = text.replace(old, new, 1)
    print('[class] OK')
else:
    print('[class] WARN')

# 2) init 注入 getter/formatter/input_required_msg
old_init = "        self.schema = table_schema_string"
new_init = (
    old_init
    + "\n        self.getter = get_recommend"
    + "\n        self.formatter = format_recommend_rows"
    + '\n        self.input_required_msg = "查询无效，请提供综合推荐条件。"'
)
if old_init in text:
    text = text.replace(old_init, new_init, 1)
    print('[init] OK')
else:
    print('[init] WARN')

with io.open(p, 'w', encoding='utf-8', newline='') as f:
    f.write(text)
r = subprocess.run([sys.executable, '-m', 'py_compile', p], capture_output=True, text=True)
print('compile:', 'OK' if r.returncode == 0 else 'FAIL\n' + r.stderr[:400])
