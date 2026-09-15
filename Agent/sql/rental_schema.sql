-- ============================================================
-- 智租顾问（Zhizu Advisor）数据库表结构（rental 数据库）
-- 数据来源：Agent/数据库操作 目录下的抓取脚本
--   爬虫.py            -> house_listing    （房天下-郑州租房）
--   play.py            -> poi_data         （高德POI-郑州）
--   fetch_metro.py     -> metro_station    （高德地铁站-郑州）
--   update_poi_metro.py -> 为 poi_data 补充最近地铁站关联字段
-- 示例种子数据：Agent/sql/seed_data.sql
-- ============================================================

DROP DATABASE IF EXISTS rental;
CREATE DATABASE rental CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE rental;

-- ------------------------------------------------------------
-- 1. 房源表 house_listing
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS house_listing (
    id INT AUTO_INCREMENT PRIMARY KEY,
    house_id VARCHAR(50) NOT NULL COMMENT '房源ID',
    city VARCHAR(20) DEFAULT '郑州',
    district VARCHAR(50) COMMENT '区域（如 金水区/中原区/二七区）',
    community TEXT COMMENT '小区名称',
    layout TEXT COMMENT '户型（如 3室2厅2卫）',
    area DECIMAL(10,2) COMMENT '面积m²',
    rent INT COMMENT '月租金（元）',
    orientation VARCHAR(20) COMMENT '朝向',
    floor VARCHAR(50) COMMENT '楼层',
    metro_line VARCHAR(50) COMMENT '地铁线路（如 1号线）',
    walk_minutes INT COMMENT '距地铁步行分钟',
    status VARCHAR(20) DEFAULT '在租' COMMENT '在租/已租/下架',
    detail_url VARCHAR(255) COMMENT '详情页链接',
    update_time DATETIME,
    UNIQUE KEY unique_house (house_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='房源表';

-- ------------------------------------------------------------
-- 2. 天气预报表 weather_forecast
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS weather_forecast (
    id INT AUTO_INCREMENT PRIMARY KEY,
    city VARCHAR(20) NOT NULL COMMENT '城市名称',
    forecast_date DATE NOT NULL COMMENT '预报日期',
    temp_max INT COMMENT '最高温度（℃）',
    temp_min INT COMMENT '最低温度（℃）',
    humidity INT COMMENT '相对湿度（%）',
    wind_dir VARCHAR(20) COMMENT '风向',
    wind_level VARCHAR(10) COMMENT '风力等级',
    weather_text VARCHAR(50) COMMENT '天气状况（晴/多云/雨等）',
    uv_index VARCHAR(10) COMMENT '紫外线指数',
    update_time DATETIME COMMENT '数据更新时间',
    UNIQUE KEY unique_weather (city, forecast_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='天气预报表';

-- ------------------------------------------------------------
-- 3. POI数据表 poi_data
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS poi_data (
    id INT AUTO_INCREMENT PRIMARY KEY,
    poi_id VARCHAR(50) NOT NULL COMMENT '高德POI ID',
    name VARCHAR(255) NOT NULL COMMENT '名称',
    type VARCHAR(100) COMMENT '大类（旅游景点/公园广场/医疗保健/住宿服务/餐饮服务）',
    typecode VARCHAR(50) COMMENT 'POI类型编码',
    address VARCHAR(255) COMMENT '地址',
    location VARCHAR(50) COMMENT '经纬度(经度,纬度)',
    pname VARCHAR(50) COMMENT '省份',
    cityname VARCHAR(50) COMMENT '城市',
    adname VARCHAR(50) COMMENT '区县（如 金水区）',
    nearest_metro VARCHAR(100) COMMENT '最近地铁站',
    nearest_metro_line VARCHAR(50) COMMENT '最近地铁线路',
    distance_to_metro INT COMMENT '到最近地铁站距离(米)',
    update_time DATETIME,
    UNIQUE KEY unique_poi (poi_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='POI数据表';

-- ------------------------------------------------------------
-- 4. 地铁站表 metro_station
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS metro_station (
    id INT AUTO_INCREMENT PRIMARY KEY,
    poi_id VARCHAR(50) NOT NULL COMMENT '高德POI ID',
    name VARCHAR(100) NOT NULL COMMENT '地铁站名',
    line_name VARCHAR(50) COMMENT '所属线路（如 1号线）',
    address VARCHAR(255) COMMENT '地址',
    location VARCHAR(50) COMMENT '经纬度(经度,纬度)',
    lng DECIMAL(10,6) COMMENT '经度',
    lat DECIMAL(10,6) COMMENT '纬度',
    update_time DATETIME,
    UNIQUE KEY unique_poi (poi_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='地铁站表';
