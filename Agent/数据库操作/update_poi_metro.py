#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: update_poi_metro.py
描述: 将 poi_data 表关联到最近的地铁站和线路
"""

import math
import mysql.connector
from mysql.connector import Error

DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': '123456',
    'database': 'rental',
    'charset': 'utf8mb4'
}


def get_db_connection():
    return mysql.connector.connect(**DB_CONFIG)


def haversine_distance(lon1, lat1, lon2, lat2):
    R = 6371000
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)
    a = math.sin(delta_lat/2)**2 + math.cos(lat1_rad)*math.cos(lat2_rad)*math.sin(delta_lon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c


def add_metro_fields():
    """给 poi_data 表增加地铁关联字段"""
    conn = get_db_connection()
    cursor = conn.cursor()

    fields = [
        ("nearest_metro", "VARCHAR(100) COMMENT '最近地铁站'"),
        ("nearest_metro_line", "VARCHAR(50) COMMENT '最近地铁线路'"),
        ("distance_to_metro", "INT COMMENT '到最近地铁站距离(米)'"),
    ]

    for field_name, field_def in fields:
        cursor.execute(f"SHOW COLUMNS FROM poi_data LIKE '{field_name}'")
        if not cursor.fetchone():
            cursor.execute(f"ALTER TABLE poi_data ADD COLUMN {field_name} {field_def}")
            print(f"   ✅ 已添加字段: {field_name}")

    conn.commit()
    cursor.close()
    conn.close()


def update_poi_metro():
    """关联POI到最近地铁站"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. 获取所有有经纬度的POI
    cursor.execute("""
        SELECT id, name, lng, lat 
        FROM poi_data 
        WHERE lng IS NOT NULL AND lat IS NOT NULL
    """)
    pois = cursor.fetchall()
    print(f"📊 找到 {len(pois)} 条需要关联的POI数据")

    if not pois:
        return 0

    # 2. 获取所有地铁站
    cursor.execute("""
        SELECT poi_id, name, line_name, lng, lat 
        FROM metro_station 
        WHERE lng IS NOT NULL AND lat IS NOT NULL
    """)
    metros = cursor.fetchall()
    print(f"📊 找到 {len(metros)} 个地铁站")

    if not metros:
        print("⚠️ 没有地铁站数据，请先运行 fetch_metro.py")
        return 0

    # 3. 逐条计算关联
    updated_count = 0
    for idx, poi in enumerate(pois, 1):
        poi_id, poi_name, poi_lng, poi_lat = poi

        nearest_metro = None
        nearest_line = None
        nearest_dist = float('inf')

        for metro in metros:
            m_id, m_name, m_line, m_lng, m_lat = metro
            if m_lng is None or m_lat is None:
                continue
            dist = haversine_distance(poi_lng, poi_lat, m_lng, m_lat)
            if dist < nearest_dist:
                nearest_dist = dist
                nearest_metro = m_name
                nearest_line = m_line

        if nearest_metro:
            cursor.execute("""
                UPDATE poi_data 
                SET nearest_metro = %s, nearest_metro_line = %s, distance_to_metro = %s
                WHERE id = %s
            """, (nearest_metro, nearest_line, int(nearest_dist), poi_id))
            updated_count += 1

        if idx % 50 == 0:
            print(f"   📝 已处理 {idx}/{len(pois)} 条")

    conn.commit()
    cursor.close()
    conn.close()

    print(f"   ✅ 成功更新 {updated_count} 条POI")
    return updated_count


def show_results():
    """展示关联结果"""
    conn = get_db_connection()
    cursor = conn.cursor()

    print("\n" + "=" * 60)
    print("📋 关联结果示例（前10条，按距离排序）")
    print("=" * 60)

    cursor.execute("""
        SELECT name, type, nearest_metro, nearest_metro_line, distance_to_metro
        FROM poi_data 
        WHERE nearest_metro IS NOT NULL 
        ORDER BY distance_to_metro 
        LIMIT 10
    """)
    rows = cursor.fetchall()
    for row in rows:
        print(f"   {row[0]} | {row[1]} | 最近: {row[2]}({row[3]}) | {row[4]}米")

    print("\n" + "=" * 60)
    print("📊 各线路覆盖POI数量统计")
    print("=" * 60)

    cursor.execute("""
        SELECT nearest_metro_line, COUNT(*) as cnt
        FROM poi_data 
        WHERE nearest_metro_line IS NOT NULL 
        GROUP BY nearest_metro_line
        ORDER BY cnt DESC
    """)
    rows = cursor.fetchall()
    for row in rows:
        if row[0]:
            print(f"   {row[0]}: {row[1]} 个POI")

    cursor.close()
    conn.close()


def main():
    print("=" * 60)
    print("🚇 开始将POI关联到最近地铁站")
    print("=" * 60)

    print("\n📡 步骤1: 检查并添加字段...")
    add_metro_fields()

    print("\n📡 步骤2: 计算并更新最近地铁站...")
    updated = update_poi_metro()

    if updated > 0:
        show_results()
    else:
        print("⚠️ 没有更新任何数据")

    print("\n🎉 完成！")


if __name__ == "__main__":
    main()