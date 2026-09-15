# -*- coding: utf-8 -*-
"""一次性脚本：keys.py 追加私有端点与模型配置（本机使用，不上传）"""
import io
import os

p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config_local', 'keys.py')

with io.open(p, 'r', encoding='utf-8', errors='replace') as f:
    t = f.read()

anchor = 'DASHSCOPE_API_KEY = '
i = t.find(anchor)
if i < 0:
    print('anchor not found')
    raise SystemExit(1)
line_end = t.find('\n', i)

add = (
    "\n"
    "# 大模型私有网关地址（可选）：留空则使用 DashScope 公共端点\n"
    'DASHSCOPE_BASE_URL = "https://llm-zaievvsekl2smdkd.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"\n'
    "# 大模型名称（可选）：留空则默认 qwen-plus\n"
    'DASHSCOPE_MODEL = "qwen3.8-max"\n'
)

t = t[:line_end + 1] + add + t[line_end + 1:]
with io.open(p, 'w', encoding='utf-8', newline='') as f:
    f.write(t)
print('keys.py updated OK')
