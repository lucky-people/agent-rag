# -*- coding: utf-8 -*-
"""一次性修复脚本：legal_qa/base/config.py 的 eval() 改为安全解析、默认口令改为环境变量"""
import io
import os

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
p = os.path.join(PROJECT_ROOT, 'Agent', 'legal_qa', 'base', 'config.py')

with io.open(p, 'r', encoding='utf-8') as f:
    text = f.read()

# 1. eval() 改 json.loads 安全解析
old_eval = '''        # 有效来源列表
        self.VALID_SOURCES = eval(
            self.config.get('app', 'valid_sources', fallback='["ai", "java", "test", "ops", "bigdata"]'))'''
new_eval = '''        # 有效来源列表（安全解析，避免 eval 执行任意表达式）
        import json as _json
        _raw = self.config.get('app', 'valid_sources', fallback='["ai", "java", "test", "ops", "bigdata"]')
        try:
            self.VALID_SOURCES = _json.loads(_raw)
        except Exception:
            self.VALID_SOURCES = ["ai", "java", "test", "ops", "bigdata"]'''
if old_eval in text:
    text = text.replace(old_eval, new_eval, 1)
    print('[eval] OK -> json.loads')
else:
    print('[eval] WARN: not found')

# 2. MySQL/Redis 默认口令 fallback 移除（留空，需用户配置）
old_mysql = "self.MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD', self.config.get('mysql', 'password', fallback='123456'))"
new_mysql = "self.MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD', self.config.get('mysql', 'password', fallback=''))"
if old_mysql in text:
    text = text.replace(old_mysql, new_mysql, 1)
    print('[mysql pw] OK: fallback removed')
else:
    print('[mysql pw] WARN: not found')

old_redis = "self.REDIS_PASSWORD = os.getenv('REDIS_PASSWORD', self.config.get('redis', 'password', fallback='1234'))"
new_redis = "self.REDIS_PASSWORD = os.getenv('REDIS_PASSWORD', self.config.get('redis', 'password', fallback=''))"
if old_redis in text:
    text = text.replace(old_redis, new_redis, 1)
    print('[redis pw] OK: fallback removed')
else:
    print('[redis pw] WARN: not found')

# 3. 注释里的默认口令也清掉
text = text.replace("# self.MYSQL_PASSWORD = self.config.get('mysql', 'password', fallback='123456')",
                    "# self.MYSQL_PASSWORD = self.config.get('mysql', 'password', fallback='')")
text = text.replace("# self.REDIS_PASSWORD = self.config.get('redis', 'password', fallback='1234')",
                    "# self.REDIS_PASSWORD = self.config.get('redis', 'password', fallback='')")
print('[comments] OK')

with io.open(p, 'w', encoding='utf-8', newline='') as f:
    f.write(text)
print('DONE')
