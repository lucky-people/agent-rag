# -*- coding: utf-8 -*-
"""一次性脚本：rental_schema.sql 清理旧项目名残留与双后缀错误"""
import io
import os

p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Agent', 'sql', 'rental_schema.sql')
with io.open(p, 'r', encoding='utf-8') as f:
    text = f.read()

old_head = '''-- ============================================================
-- SmartVoyage 融合数据表结构（rental 数据库）
-- 数据来源：数据库操作 目录下的抓取脚本
--   爬虫.py            -> house_listing    （贝壳租房-郑州）
--   weather_zz.py      -> weather_forecast （和风天气-郑州15天预报）
--   play.py            -> poi_data         （高德POI-郑州）
--   fetch_metro.py     -> metro_station    （高德地铁站-郑州）
--   update_poi_metro.py.py -> 为 poi_data 补充最近地铁站关联字段
-- ============================================================'''

new_head = '''-- ============================================================
-- 智租顾问（Zhizu Advisor）数据库表结构（rental 数据库）
-- 数据来源：Agent/数据库操作 目录下的抓取脚本
--   爬虫.py            -> house_listing    （房天下-郑州租房）
--   play.py            -> poi_data         （高德POI-郑州）
--   fetch_metro.py     -> metro_station    （高德地铁站-郑州）
--   update_poi_metro.py -> 为 poi_data 补充最近地铁站关联字段
-- 示例种子数据：Agent/sql/seed_data.sql
-- ============================================================'''

if old_head in text:
    text = text.replace(old_head, new_head, 1)
    print('[head] OK')
else:
    print('[head] WARN: not found')

with io.open(p, 'w', encoding='utf-8', newline='') as f:
    f.write(text)
print('DONE')
