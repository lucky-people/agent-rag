# -*- coding: utf-8 -*-
"""生成种子数据 seed_data.sql（示例数据，标注用途，供 clone 后快速跑通演示）"""
import io
import os
import random
from datetime import datetime, timedelta

random.seed(2026)

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Agent', 'sql', 'seed_data.sql')

districts = ['金水', '中原', '二七', '管城', '惠济', '高新', '郑东', '经开']
communities_by_district = {
    '金水': ['正弘数码公寓', '鑫苑名家', '曼哈顿广场', '绿地老街', '金城时代广场', '银基王朝', '升龙凤凰城', '锦艺国际华都'],
    '中原': ['中原万达广场', '锦艺城', '金锣湾', '盛润锦绣城', '宏江瀚苑', '梧桐新语', '风和日丽家园'],
    '二七': ['升龙城', '鑫苑都市领地', '亚星盛世家园', '康桥金域上郡', '绿地滨湖国际城', '正商城'],
    '管城': ['绿都澜湾', '永威城', '万科美景龙堂', '正商华钻', '鑫苑国际新城', '未来城'],
    '惠济': ['正弘澜庭叙', '万科天伦紫台', '锦艺四季城', '民安北郡', '思念果岭国际社区'],
    '高新': ['万科城', '谦祥万和城', '正弘高新数码港', '升龙又一城', '翰林国际城'],
    '郑东': ['海马公园', '建业天筑', '绿地原盛国际', '正商东方港湾', '郑东新区CBD住宅', '龙湖花园'],
    '经开': ['恒大绿洲', '绿地海珀兰轩', '金沙湖高尔夫观邸', '远大理想城', '万锦城'],
}
layouts = ['1室1厅1卫', '1室1厅', '2室1厅1卫', '2室2厅1卫', '3室2厅1卫', '3室2厅2卫', '4室2厅2卫', '1室0厅1卫', '2室0厅1卫']
orientations = ['南', '南北', '东', '西', '东南', '西南']
floors = ['低楼层', '中楼层', '高楼层']
metro_lines = ['1号线', '2号线', '3号线', '4号线', '5号线', '城郊线', None]

lines = []
lines.append("-- ============================================================")
lines.append("-- 智租顾问 示例种子数据（Demo Data）")
lines.append("-- 用途：仓库 clone 后快速导入，让系统开箱即可演示。")
lines.append("-- 说明：本文件为【演示用示例数据】，非真实房源采集数据；")
lines.append("--       如需真实数据，请运行 Agent/数据库操作/ 下的爬虫脚本自行采集，")
lines.append("--       或参照表结构导入自己的数据。")
lines.append("-- 导入：mysql -uroot -p rental < seed_data.sql")
lines.append("-- ============================================================")
lines.append("")
lines.append("USE rental;")
lines.append("")
lines.append("SET NAMES utf8mb4;")
lines.append("")

# ---------- 房源数据：约 60 条（整租 48 + 合租 12），覆盖多区域/多价格段 ----------
lines.append("-- ------------------------------------------------------------")
lines.append("-- 1. 房源表 house_listing 示例数据")
lines.append("-- ------------------------------------------------------------")
lines.append("INSERT INTO house_listing")
lines.append("    (house_id, city, district, community, layout, area, rent, orientation, floor,")
lines.append("     metro_line, walk_minutes, status, detail_url, update_time) VALUES")

n_house = 0
base_time = datetime(2026, 8, 1, 10, 0, 0)
rows = []
for d_idx, district in enumerate(districts):
    # 每区 7-8 条
    n = random.randint(6, 8)
    coms = communities_by_district[district]
    for i in range(n):
        com = random.choice(coms)
        layout = random.choice(layouts)
        area = random.choice([38, 42, 55, 68, 78, 89, 96, 108, 120, 135])
        # 整租为主，少量合租
        if random.random() < 0.2:
            status = '合租'
            rent = random.choice([600, 750, 850, 950, 1100])
            area = random.choice([18, 22, 28, 32, 38])
            layout = random.choice(['1室0厅1卫', '2室0厅1卫', '1室1厅1卫'])
        else:
            status = '整租'
            rent = random.choice([1200, 1500, 1800, 2200, 2600, 3200, 3800, 4500])
        metro = random.choice(metro_lines)
        walk = random.choice([150, 300, 500, 700, 900, 1200]) if metro else None
        hid = f"zz{d_idx}{i}{random.randint(100, 999)}"
        t = (base_time + timedelta(hours=d_idx * 3 + i)).strftime('%Y-%m-%d %H:%M:%S')
        rows.append(
            f"    ('{hid}', '郑州', '{district}区', '{com}', '{layout}', {area}, {rent}, "
            f"'{random.choice(orientations)}', '{random.choice(floors)}', "
            f"{repr(metro) if metro else 'NULL'}, {walk if walk else 'NULL'}, "
            f"'{status}', 'https://zu.fang.com/zz/chuzu/1_{hid}_1.htm', '{t}')"
        )
        n_house += 1

lines.append(",\n".join(rows))
lines.append(";")
lines.append("")

# ---------- 地铁站数据：郑州主要线路站点 ----------
metro_stations = [
    # (poi_id, name, line, address, lng, lat)
    ('B10000001', '郑州东站(地铁站)', '1号线/5号线', '郑东新区郑州东站', 113.7765, 34.7500),
    ('B10000002', '会展中心站(地铁站)', '1号线/4号线', '郑东新区CBD', 113.7270, 34.7720),
    ('B10000003', '二七广场站(地铁站)', '1号线/3号线', '二七区二七广场', 113.6630, 34.7500),
    ('B10000004', '紫荆山站(地铁站)', '1号线/2号线', '金水区紫荆山路', 113.6810, 34.7620),
    ('B10000005', '火车站(地铁站)', '1号线', '二七区郑州火车站', 113.6650, 34.7460),
    ('B10000006', '关虎屯站(地铁站)', '2号线', '金水区花园路', 113.6780, 34.7980),
    ('B10000007', '东风路站(地铁站)', '2号线', '金水区东风路', 113.6820, 34.7930),
    ('B10000008', '农业路站(地铁站)', '2号线', '金水区农业路', 113.6800, 34.7840),
    ('B10000009', '西三环站(地铁站)', '1号线', '中原区西三环', 113.5910, 34.7570),
    ('B10000010', '秦岭路站(地铁站)', '1号线', '中原区秦岭路', 113.6230, 34.7550),
    ('B10000011', '绿城广场站(地铁站)', '1号线', '中原区绿城广场', 113.6440, 34.7520),
    ('B10000012', '会展中心东站(地铁站)', '4号线', '郑东新区', 113.7450, 34.7700),
    ('B10000013', '郑州大学站(地铁站)', '1号线', '高新区科学大道', 113.5300, 34.8050),
    ('B10000014', '龙子湖站(地铁站)', '1号线', '郑东新区龙子湖', 113.7950, 34.7900),
    ('B10000015', '南三环站(地铁站)', '2号线', '管城区南三环', 113.6700, 34.6900),
]

lines.append("-- ------------------------------------------------------------")
lines.append("-- 2. 地铁站表 metro_station 示例数据")
lines.append("-- ------------------------------------------------------------")
lines.append("INSERT INTO metro_station (poi_id, name, line_name, address, location, lng, lat, update_time) VALUES")
t0 = base_time.strftime('%Y-%m-%d %H:%M:%S')
mrows = [
    f"    ('{pid}', '{name}', '{line}', '{addr}', '{lng},{lat}', {lng}, {lat}, '{t0}')"
    for pid, name, line, addr, lng, lat in metro_stations
]
lines.append(",\n".join(mrows))
lines.append(";")
lines.append("")

# ---------- POI 数据：郑州主要景点/商圈/医院 ----------
pois = [
    ('P10000001', '河南博物院', '旅游景点', '金水区农业路8号', 113.6800, 34.7950, '金水区'),
    ('P10000002', '二七纪念塔', '旅游景点', '二七区二七广场', 113.6630, 34.7500, '二七区'),
    ('P10000003', '郑州动物园', '旅游景点', '金水区花园路', 113.6780, 34.7990, '金水区'),
    ('P10000004', '绿博园', '旅游景点', '中牟县', 113.9300, 34.8200, '中牟县'),
    ('P10000005', '如意湖', '旅游景点', '郑东新区CBD', 113.7230, 34.7710, '郑东新区'),
    ('P10000006', '大卫城', '餐饮服务', '二七区二七路', 113.6640, 34.7510, '二七区'),
    ('P10000007', '正弘城', '餐饮服务', '金水区花园路', 113.6790, 34.7980, '金水区'),
    ('P10000008', '国贸360广场', '餐饮服务', '金水区花园路', 113.6770, 34.7940, '金水区'),
    ('P10000009', '中原万达广场', '餐饮服务', '中原区中原路', 113.6100, 34.7520, '中原区'),
    ('P10000010', '郑大一附院', '医疗保健', '二七区建设东路', 113.6500, 34.7550, '二七区'),
    ('P10000011', '河南省人民医院', '医疗保健', '金水区纬五路', 113.6900, 34.7750, '金水区'),
    ('P10000012', '郑州希尔顿酒店', '住宿服务', '郑东新区金水路', 113.7300, 34.7680, '郑东新区'),
    ('P10000013', '郑州绿地千玺广场', '旅游景点', '郑东新区CBD', 113.7250, 34.7720, '郑东新区'),
    ('P10000014', '人民公园', '公园广场', '二七区解放路', 113.6600, 34.7550, '二七区'),
    ('P10000015', '郑州海洋馆', '旅游景点', '金水区国基路', 113.6700, 34.8100, '金水区'),
]

lines.append("-- ------------------------------------------------------------")
lines.append("-- 3. POI 数据表 poi_data 示例数据")
lines.append("-- ------------------------------------------------------------")
lines.append("INSERT INTO poi_data")
lines.append("    (poi_id, name, type, typecode, address, location, pname, cityname, adname,")
lines.append("     nearest_metro, nearest_metro_line, distance_to_metro, update_time) VALUES")
prows = []
metro_by_district = {
    '金水区': ('紫荆山站(地铁站)', '1号线/2号线', 500),
    '二七区': ('二七广场站(地铁站)', '1号线/3号线', 400),
    '中原区': ('绿城广场站(地铁站)', '1号线', 600),
    '郑东新区': ('会展中心站(地铁站)', '1号线/4号线', 800),
    '管城区': ('南三环站(地铁站)', '2号线', 700),
    '高新区': ('郑州大学站(地铁站)', '1号线', 900),
    '中牟县': ('绿博园站(地铁站)', '1号线', 1500),
}
for poi_id, name, ptype, addr, lng, lat, adname in pois:
    nm, nl, nd = metro_by_district.get(adname, ('紫荆山站(地铁站)', '1号线/2号线', 800))
    typecode = {'旅游景点': '110200', '餐饮服务': '050000', '医疗保健': '090100', '住宿服务': '100000', '公园广场': '110101'}[ptype]
    prows.append(
        f"    ('{poi_id}', '{name}', '{ptype}', '{typecode}', '{addr}', '{lng},{lat}', '河南省', '郑州市', '{adname}', "
        f"'{nm}', '{nl}', {nd}, '{t0}')"
    )
lines.append(",\n".join(prows))
lines.append(";")
lines.append("")

# ---------- 天气预报表 ----------
lines.append("-- ------------------------------------------------------------")
lines.append("-- 4. 天气预报表 weather_forecast 示例数据（郑州7天）")
lines.append("-- ------------------------------------------------------------")
lines.append("INSERT INTO weather_forecast (city, forecast_date, temp_max, temp_min, humidity, wind_dir, wind_level, weather_text, uv_index, update_time) VALUES")
wrows = []
weathers = [('晴', 34, 24, 40, '南风', '3级', '强'), ('多云', 32, 23, 45, '东南风', '2级', '中等'),
            ('小雨', 28, 21, 70, '东北风', '3级', '弱'), ('晴', 33, 23, 42, '西南风', '2级', '强'),
            ('阴', 29, 22, 55, '东风', '2级', '中等'), ('雷阵雨', 27, 20, 75, '北风', '3级', '弱'),
            ('晴', 31, 22, 44, '南风', '2级', '强')]
for i, (wt, tmax, tmin, hum, wd, wl, uv) in enumerate(weathers):
    d = (datetime(2026, 9, 15) + timedelta(days=i)).strftime('%Y-%m-%d')
    wrows.append(f"    ('郑州', '{d}', {tmax}, {tmin}, {hum}, '{wd}', '{wl}', '{wt}', '{uv}', '{t0}')")
lines.append(",\n".join(wrows))
lines.append(";")

with io.open(OUT, 'w', encoding='utf-8', newline='') as f:
    f.write("\n".join(lines))

print(f"seed_data.sql 生成完成: {OUT}")
print(f"  房源 {n_house} 条 / 地铁站 {len(metro_stations)} 条 / POI {len(pois)} 条 / 天气 {len(weathers)} 条")
