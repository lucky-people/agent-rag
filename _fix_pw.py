# -*- coding: utf-8 -*-
"""一次性修复脚本：把数据库操作目录下写死的密码改为密钥文件+环境变量读取"""
import io
import os

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))


def fix_update_poi_metro():
    p = os.path.join(PROJECT_ROOT, 'Agent', '数据库操作', 'update_poi_metro.py')
    with io.open(p, 'r', encoding='utf-8') as f:
        text = f.read()

    old = """import math
import mysql.connector
from mysql.connector import Error

DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': '123456',
    'database': 'rental',
    'charset': 'utf8mb4'
}"""

    new = """import math
import os
import importlib.util as _ilu
import mysql.connector
from mysql.connector import Error

# ========== 密钥加载（优先环境变量，其次 config_local/keys.py） ==========
# config_local/ 已被 .gitignore 排除，不会上传到仓库
_LOCAL_KEYS = None
_keys_path = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'config_local', 'keys.py'
)
if os.path.exists(_keys_path):
    _spec = _ilu.spec_from_file_location('local_keys', _keys_path)
    _LOCAL_KEYS = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_LOCAL_KEYS)

DB_PASSWORD = os.getenv("MYSQL_PASSWORD", "") or (
    getattr(_LOCAL_KEYS, 'MYSQL_PASSWORD', '') if _LOCAL_KEYS else ""
) or "YOUR_MYSQL_PASSWORD"
# ======================================================

DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': DB_PASSWORD,
    'database': 'rental',
    'charset': 'utf8mb4'
}"""

    if old not in text:
        print('[update_poi_metro] WARN: old text not found, skipped')
        return False
    text = text.replace(old, new, 1)
    with io.open(p, 'w', encoding='utf-8', newline='') as f:
        f.write(text)
    print('[update_poi_metro] OK: password moved to env/config_local')
    return True


if __name__ == '__main__':
    fix_update_poi_metro()
