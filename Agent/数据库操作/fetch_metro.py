#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: fetch_metro.py
描述: 抓取郑州地铁站数据（含线路名），过滤噪音
"""

import requests
import json
import re
import time
import os
from datetime import datetime
import mysql.connector
from mysql.connector import Error

# ========== 密钥加载（无需手动设置环境变量） ==========
# 优先读取环境变量，其次读取项目根目录 config_local/keys.py 本地密钥文件
# （config_local/ 已被 .gitignore 排除，不会上传到仓库）
import importlib.util as _ilu

_LOCAL_KEYS = None
_keys_path = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'config_local', 'keys.py'
)
if os.path.exists(_keys_path):
    _spec = _ilu.spec_from_file_location('local_keys', _keys_path)
    _LOCAL_KEYS = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_LOCAL_KEYS)

API_KEY = os.getenv("AMAP_API_KEY", "") or (
    getattr(_LOCAL_KEYS, 'AMAP_API_KEY', '') if _LOCAL_KEYS else ""
) or "YOUR_AMAP_API_KEY"
DB_PASSWORD = os.getenv("MYSQL_PASSWORD", "") or (
    getattr(_LOCAL_KEYS, 'MYSQL_PASSWORD', '') if _LOCAL_KEYS else ""
) or "YOUR_MYSQL_PASSWORD"
# ======================================================

CITY = "郑州"

DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': DB_PASSWORD,
    'database': 'rental',
    'charset': 'utf8mb4'
}


def get_db_connection():
    return mysql.connector.connect(**DB_CONFIG)


def clean_value(value):
    if value is None:
        return None
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False) if value else None
    return str(value) if value else None


def is_valid_metro(name):
    """判断是否为有效的地铁站（过滤游船码头等噪音）"""
    if not name:
        return False
    # 排除词（黑名单）
    exclude = ['游船', '码头', '湿地', '公园', '景区', '游乐园', '山庄', '度假区']
    for ex in exclude:
        if ex in name:
            return False
    # 必须包含"地铁"或"站"
    if '地铁' in name:
        return True
    if name.endswith('站') and not name.endswith('车站'):
        return True
    return False


def create_metro_table():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS metro_station")
    sql = """
    CREATE TABLE metro_station (
        id INT AUTO_INCREMENT PRIMARY KEY,
        poi_id VARCHAR(50) NOT NULL COMMENT '高德POI ID',
        name VARCHAR(100) NOT NULL COMMENT '地铁站名',
        line_name VARCHAR(50) COMMENT '所属线路',
        address VARCHAR(255) COMMENT '地址',
        location VARCHAR(50) COMMENT '经纬度(经度,纬度)',
        lng DECIMAL(10,6) COMMENT '经度',
        lat DECIMAL(10,6) COMMENT '纬度',
        update_time DATETIME,
        UNIQUE KEY unique_poi (poi_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='地铁站表';
    """
    cursor.execute(sql)
    conn.commit()
    print("✅ 地铁站表已创建")
    cursor.close()
    conn.close()


def fetch_metro_stations():
    """通过关键词搜索抓取郑州地铁站"""
    url = "https://restapi.amap.com/v3/place/text"
    all_pois = []
    page = 1
    page_size = 20

    print("📡 开始抓取郑州地铁站...")

    while True:
        params = {
            'key': API_KEY,
            'keywords': '地铁',  # 用关键词搜索，比types更精确
            'city': CITY,
            'citylimit': True,
            'offset': page_size,
            'page': page,
            'extensions': 'all'
        }

        try:
            response = requests.get(url, params=params, timeout=10)
            data = response.json()

            if data['status'] == '1' and data['infocode'] == '10000':
                pois = data.get('pois', [])
                if not pois:
                    break

                # 过滤有效地铁站
                for poi in pois:
                    if is_valid_metro(poi.get('name', '')):
                        all_pois.append(poi)

                print(f"   📄 第 {page} 页，原始 {len(pois)} 条，有效 {len(all_pois)} 条")

                if len(pois) < page_size:
                    break
                page += 1
                time.sleep(0.3)
            else:
                print(f"   ❌ API错误: {data.get('info')}")
                break
        except Exception as e:
            print(f"   ❌ 请求异常: {e}")
            break

    return all_pois


def extract_line_name(poi):
    """从POI数据中提取线路名"""
    # 方法1: 从 name 中提取
    name = poi.get('name', '')
    line_match = re.search(r'(\d+号线)', name)
    if line_match:
        return line_match.group(1)
    # 方法2: 从 type 中提取
    type_text = poi.get('type', '')
    line_match = re.search(r'(\d+号线)', type_text)
    if line_match:
        return line_match.group(1)
    # 方法3: 从 address 中提取
    address = poi.get('address', '')
    line_match = re.search(r'(\d+号线)', address)
    if line_match:
        return line_match.group(1)
    return None


def save_metro_to_db(poi_list):
    if not poi_list:
        return 0

    conn = get_db_connection()
    cursor = conn.cursor()

    insert_sql = """
    INSERT INTO metro_station 
    (poi_id, name, line_name, address, location, lng, lat, update_time)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
    name = VALUES(name),
    line_name = VALUES(line_name),
    address = VALUES(address),
    location = VALUES(location),
    lng = VALUES(lng),
    lat = VALUES(lat),
    update_time = VALUES(update_time)
    """

    records = []
    for poi in poi_list:
        location = poi.get('location', '')
        lng, lat = None, None
        if location and ',' in location:
            parts = location.split(',')
            if len(parts) >= 2:
                try:
                    lng = float(parts[0])
                    lat = float(parts[1])
                except ValueError:
                    pass

        line_name = extract_line_name(poi)

        records.append((
            clean_value(poi.get('id')),
            clean_value(poi.get('name')),
            line_name,
            clean_value(poi.get('address')),
            clean_value(location),
            lng,
            lat,
            datetime.now()
        ))

    try:
        cursor.executemany(insert_sql, records)
        conn.commit()
        print(f"   ✅ 成功存储 {len(records)} 条地铁站数据")
        return len(records)
    except Error as e:
        print(f"   ❌ 保存失败: {e}")
        return 0
    finally:
        cursor.close()
        conn.close()


def main():
    print("=" * 50)
    print("🚇 开始抓取郑州地铁站数据")
    print("=" * 50)

    create_metro_table()
    pois = fetch_metro_stations()

    if not pois:
        print("⚠️ 未获取到任何地铁站数据")
        return

    print(f"\n📊 共抓取 {len(pois)} 条有效地铁站数据")
    saved = save_metro_to_db(pois)

    if saved > 0:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM metro_station")
        count = cursor.fetchone()[0]
        print(f"\n🎉 完成！数据库中现有 {count} 条地铁站数据")

        cursor.execute("SELECT name, line_name FROM metro_station LIMIT 10")
        rows = cursor.fetchall()
        print("\n📋 前10条示例数据：")
        for row in rows:
            print(f"   {row[0]} | {row[1]}")
        cursor.close()
        conn.close()


if __name__ == "__main__":
    main()