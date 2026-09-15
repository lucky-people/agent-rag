# -*- coding: utf-8 -*-
"""一次性脚本：recommend_server.py 的 house_listing schema 补齐 orientation/floor 字段"""
import io
import os
import subprocess
import sys

p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Agent', 'a2a_server', 'recommend_server.py')
with io.open(p, 'r', encoding='utf-8') as f:
    text = f.read()

old = '''    rent INT COMMENT '月租金（元）',
    metro_line VARCHAR(50) COMMENT '地铁线路（如 1号线）',
    walk_minutes INT COMMENT '距地铁步行分钟',
    status VARCHAR(20) DEFAULT '在租' COMMENT '在租/已租/下架',
    detail_url VARCHAR(255) COMMENT '详情页链接'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='房源表';'''

new = '''    rent INT COMMENT '月租金（元）',
    orientation VARCHAR(20) COMMENT '朝向（如 南/南北）',
    floor VARCHAR(50) COMMENT '楼层（如 低楼层/中楼层/高楼层）',
    metro_line VARCHAR(50) COMMENT '地铁线路（如 1号线）',
    walk_minutes INT COMMENT '距地铁步行分钟',
    status VARCHAR(20) DEFAULT '在租' COMMENT '在租/已租/下架',
    detail_url VARCHAR(255) COMMENT '详情页链接'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='房源表';'''

if old in text:
    text = text.replace(old, new, 1)
    with io.open(p, 'w', encoding='utf-8', newline='') as f:
        f.write(text)
    print('[schema] OK: orientation/floor added')
else:
    print('[schema] WARN: pattern not found')

r = subprocess.run([sys.executable, '-m', 'py_compile', p], capture_output=True, text=True)
print('compile:', 'OK' if r.returncode == 0 else 'FAIL\n' + r.stderr[:300])
