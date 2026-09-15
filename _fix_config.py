# -*- coding: utf-8 -*-
"""一次性修复脚本：config.py 私有端点改为公共端点 + model_name 修正"""
import io
import os

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
p = os.path.join(PROJECT_ROOT, 'Agent', 'config.py')

with io.open(p, 'r', encoding='utf-8') as f:
    text = f.read()

old = '''        # 大模型配置（密钥从 config_local/keys.py 或环境变量读取）
        self.base_url = os.getenv(
            "DASHSCOPE_BASE_URL",
            "https://llm-zaievvsekl2smdkd.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
        )
        self.api_key = os.getenv("DASHSCOPE_API_KEY", "") or (
            getattr(_local_keys, 'DASHSCOPE_API_KEY', '') if _local_keys else ""
        )
        self.model_name = "qwen3.8-max"'''

new = '''        # 大模型配置（密钥从 config_local/keys.py 或环境变量读取）
        # 默认指向 DashScope 公共兼容端点；私有网关地址由 config_local/keys.py 或环境变量覆盖
        self.base_url = os.getenv(
            "DASHSCOPE_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
        self.api_key = os.getenv("DASHSCOPE_API_KEY", "") or (
            getattr(_local_keys, 'DASHSCOPE_API_KEY', '') if _local_keys else ""
        )
        self.model_name = os.getenv("DASHSCOPE_MODEL", "qwen-plus")'''

if old in text:
    text = text.replace(old, new, 1)
    print('[config.py] OK: public endpoint + model_name fixed')
else:
    print('[config.py] WARN: pattern not found')
    # 打印实际内容帮助定位
    i = text.find('self.base_url')
    print(repr(text[i-80:i+200]))

with io.open(p, 'w', encoding='utf-8', newline='') as f:
    f.write(text)
print('DONE')
