# -*- coding: utf-8 -*-
"""一次性修复脚本：config.py base_url 增加 keys.py 回退，保持本机私有网关可用"""
import io
import os

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
p = os.path.join(PROJECT_ROOT, 'Agent', 'config.py')

with io.open(p, 'r', encoding='utf-8') as f:
    text = f.read()

old = '''        # 大模型配置（密钥从 config_local/keys.py 或环境变量读取）
        # 默认指向 DashScope 公共兼容端点；私有网关地址由 config_local/keys.py 或环境变量覆盖
        self.base_url = os.getenv(
            "DASHSCOPE_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
        self.api_key = os.getenv("DASHSCOPE_API_KEY", "") or (
            getattr(_local_keys, 'DASHSCOPE_API_KEY', '') if _local_keys else ""
        )
        self.model_name = os.getenv("DASHSCOPE_MODEL", "qwen-plus")'''

new = '''        # 大模型配置（密钥从 config_local/keys.py 或环境变量读取）
        # 优先级：环境变量 > config_local/keys.py > 公共默认端点（DashScope）
        # 私有网关地址写在 config_local/keys.py 中，不会上传到开源仓库
        self.base_url = os.getenv("DASHSCOPE_BASE_URL", "") or (
            getattr(_local_keys, 'DASHSCOPE_BASE_URL', '') if _local_keys else ""
        ) or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        self.api_key = os.getenv("DASHSCOPE_API_KEY", "") or (
            getattr(_local_keys, 'DASHSCOPE_API_KEY', '') if _local_keys else ""
        )
        self.model_name = os.getenv("DASHSCOPE_MODEL", "") or (
            getattr(_local_keys, 'DASHSCOPE_MODEL', '') if _local_keys else ""
        ) or "qwen-plus"'''

if old in text:
    text = text.replace(old, new, 1)
    print('[config.py] OK: base_url/model fallback to keys.py')
else:
    print('[config.py] WARN: pattern not found')

with io.open(p, 'w', encoding='utf-8', newline='') as f:
    f.write(text)
print('DONE')
