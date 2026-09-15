#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件名: 爬虫.py
描述: 房天下郑州租房爬虫
修复说明:
  1.【关键】删除自定义 User-Agent。原来写死的 Chrome/120 UA 与真实 Chromium 版本
     不一致，WAF 做 UA 一致性检测后判定为爬虫，直接返回滑块验证页（页面无 dl.list）。
     改用 Playwright 默认 UA（与内置 Chromium 版本一致）后验证通过。
  2. 抓取改为"每次尝试新建独立浏览器上下文"，模拟新访客，避免风控持续拦截。
  3. goto 后先检测是否被弹验证码；被弹时自动拖动滑块通过验证（solve_slider）。
  4. 通过验证后把 cookie（otherid）缓存并带到后续页面，减少重复触发验证码。
  5. 连续失败时加入长时间冷却，等 IP 风控降级。
  6. 保留数据库与解析逻辑不变。
"""

import time
import random
import re
from datetime import datetime
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import mysql.connector
from mysql.connector import Error

# ==================== 数据库配置 ====================
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': '123456',      # 改成你的密码
    'database': 'rental',      # 改成你的数据库名
    'charset': 'utf8mb4'
}

# ==================== 浏览器配置 ====================
# 注意：这里不要设置 user_agent！默认 UA 与 Playwright 内置的 Chromium 版本一致，
# 网站风控做 UA 一致性校验时能通过。自定义 UA 会被识别成爬虫并返回滑块验证页。
LAUNCH_ARGS = [
    '--disable-blink-features=AutomationControlled',
    '--no-sandbox',
    '--disable-dev-shm-usage'
]

# 反自动化检测脚本（try/catch 包裹，即使某一行失败也不影响页面加载）
STEALTH_JS = """
try { Object.defineProperty(navigator, 'webdriver', {get: () => undefined}); } catch (e) {}
try { Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]}); } catch (e) {}
window.chrome = window.chrome || { runtime: {} };
"""

# ==================== 数据库操作 ====================
def get_db_connection():
    return mysql.connector.connect(**DB_CONFIG)

def create_table_if_not_exists():
    conn = get_db_connection()
    cursor = conn.cursor()
    create_sql = """
    CREATE TABLE IF NOT EXISTS house_listing (
        id INT AUTO_INCREMENT PRIMARY KEY,
        house_id VARCHAR(50) NOT NULL COMMENT '房源ID',
        city VARCHAR(20) DEFAULT '郑州',
        district VARCHAR(50) COMMENT '区域',
        community TEXT COMMENT '小区名称',
        layout TEXT COMMENT '户型',
        area DECIMAL(10,2) COMMENT '面积m²',
        rent INT COMMENT '月租金',
        orientation VARCHAR(20) COMMENT '朝向',
        floor VARCHAR(50) COMMENT '楼层',
        metro_line VARCHAR(50) COMMENT '地铁线路',
        walk_minutes INT COMMENT '距地铁步行米数',
        status VARCHAR(20) DEFAULT '在租' COMMENT '在租/已租/下架',
        detail_url VARCHAR(255) COMMENT '详情页链接',
        update_time DATETIME,
        UNIQUE KEY unique_house (house_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='房源表';
    """
    try:
        cursor.execute(create_sql)
        conn.commit()
        print("✅ 表 house_listing 已就绪")
    except Error as e:
        print(f"❌ 建表失败: {e}")
    finally:
        cursor.close()
        conn.close()

def save_house_to_db(house_data):
    conn = get_db_connection()
    cursor = conn.cursor()
    insert_sql = """
    INSERT INTO house_listing
    (house_id, city, district, community, layout, area, rent,
     orientation, floor, metro_line, walk_minutes, status, detail_url, update_time)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
    rent = VALUES(rent),
    status = VALUES(status),
    update_time = VALUES(update_time)
    """
    try:
        cursor.execute(insert_sql, (
            house_data.get('house_id'),
            house_data.get('city', '郑州'),
            house_data.get('district'),
            house_data.get('community'),
            house_data.get('layout'),
            house_data.get('area'),
            house_data.get('rent'),
            house_data.get('orientation'),
            house_data.get('floor'),
            house_data.get('metro_line'),
            house_data.get('walk_minutes'),
            house_data.get('status', '在租'),
            house_data.get('detail_url'),
            house_data.get('update_time', datetime.now())
        ))
        conn.commit()
        return True
    except Error as e:
        print(f"❌ 保存失败: {e}")
        return False
    finally:
        cursor.close()
        conn.close()

# ==================== 解析函数 ====================
def parse_page_html(html):
    """解析房源列表页，返回房源字典列表"""
    if not html:
        return []
    soup = BeautifulSoup(html, 'html.parser')
    items = soup.select('dl.list')
    if not items:
        print("⚠️ 未找到任何房源条目，请检查页面结构")
        return []
    print(f"🔎 通过 HTML 解析到 {len(items)} 个房源项")
    houses = []
    for item in items:
        house = parse_house_item(item)
        if house and house.get('community') and house.get('rent'):
            houses.append(house)
    print(f"✅ 成功解析 {len(houses)} 条有效房源")
    return houses

def parse_house_item(item):
    """解析单个 dl.list 元素"""
    house = {'city': '郑州'}
    try:
        # 标题、链接、小区名
        title_elem = item.select_one('dd.info p.title a')
        if title_elem:
            title_text = title_elem.text.strip()
            house['community'] = title_text.split()[0] if title_text else '未知小区'
            href = title_elem.get('href')
            if href:
                house['detail_url'] = href if href.startswith('http') else f"https://zu.fang.com{href}"
                # 房源ID正则，匹配 /zz/chuzu/1_58358599_1.htm 中的 58358599
                # URL 格式: /zz/chuzu/{房源类型}_{房源ID}_{页码}.htm
                # 注意: 必须跳过开头的房源类型，否则 house_id 会全变成 "1"/"3"，互相覆盖
                id_match = re.search(r'chuzu/\d+_(\d+)_', href)
                house['house_id'] = id_match.group(1) if id_match else f"zz_{int(time.time())}_{random.randint(1000,9999)}"
        else:
            house['community'] = '未知小区'
            house['house_id'] = f"zz_{int(time.time())}_{random.randint(1000,9999)}"
            house['detail_url'] = None

        # 租金
        price_elem = item.select_one('dd.info .moreInfo .price')
        if price_elem:
            price_text = price_elem.text.strip()
            price_match = re.search(r'(\d+)', price_text)
            house['rent'] = int(price_match.group(1)) if price_match else None
        else:
            house['rent'] = None

        # 户型、面积、朝向、整租/合租
        info_elem = item.select_one('dd.info p.font15.mt12.bold')
        if info_elem:
            info_text = info_elem.text.strip()
            layout_match = re.search(r'(\d+室\d+厅(?:\d+卫)?)', info_text)
            if layout_match:
                house['layout'] = layout_match.group(1)
            area_match = re.search(r'(\d+\.?\d*)\s*㎡', info_text)
            if area_match:
                house['area'] = float(area_match.group(1))
            ori_match = re.search(r'朝([南北东西]+)', info_text)
            if ori_match:
                house['orientation'] = ori_match.group(1)
            if '整租' in info_text:
                house['status'] = '整租'
            elif '合租' in info_text:
                house['status'] = '合租'
            floor_match = re.search(r'(低|中|高)楼层', info_text)
            if floor_match:
                house['floor'] = floor_match.group(1) + '楼层'

        # 区域
        region_elem = item.select_one('dd.info p.gray6.mt12 a:first-child')
        if region_elem:
            house['district'] = region_elem.text.strip()

        # 地铁信息
        metro_elem = item.select_one('dd.info .note.subInfor')
        if metro_elem:
            metro_text = metro_elem.text.strip()
            metro_match = re.search(r'距\s*(\d+号线.*?站)\s*约\s*(\d+)米', metro_text)
            if metro_match:
                house['metro_line'] = metro_match.group(1).strip()
                house['walk_minutes'] = int(metro_match.group(2))

        house['update_time'] = datetime.now()
        house.setdefault('status', '在租')
        return house

    except Exception as e:
        print(f"⚠️ 解析单个房源失败: {e}")
        return None

# ==================== 抓取函数 ====================
def is_captcha_page(page):
    """判断当前页面是否被风控拦截（滑块验证页）"""
    try:
        title = page.title()
        if any(k in title for k in ("验证", "安全", "verify", "captcha")):
            return True
        body = page.locator("body").inner_text(timeout=3000)[:300]
        if any(k in body for k in ("请完成下列验证", "滑动", "拖动滑块", "验证码")):
            return True
    except Exception:
        pass
    return False

# 通过滑块验证后，把当前会话 cookie（含 otherid）存下来，后续页面带上可减少重复验证码
TRUSTED_COOKIES = []

def solve_slider(page, max_wait=15):
    """自动拖动滑块完成人机验证。

    房天下的滑块是"拖到底"型（无缺口背景图），拖到最右端触发 complete，
    页面会带着 backurl 跳回目标页。成功后返回 True。
    """
    try:
        slider = page.locator("#slider")
        handler = page.locator(".handler")
        slider.wait_for(state="visible", timeout=8000)
        handler.wait_for(state="visible", timeout=8000)
    except Exception as e:
        print(f"   ❌ 滑块元素未出现: {e}")
        return False

    sb = slider.bounding_box()
    hb = handler.bounding_box()
    if not sb or not hb:
        print("   ❌ 拿不到滑块/手柄坐标")
        return False

    start_x = hb["x"] + hb["width"] / 2
    start_y = hb["y"] + hb["height"] / 2
    target_x = sb["x"] + sb["width"] - hb["width"] / 2
    print(f"   🎯 拖拽滑块 {start_x:.0f} -> {target_x:.0f}")

    page.mouse.move(start_x, start_y)
    page.mouse.down()
    # 分段移动模拟真人，最后一段必须落到最右端
    steps = 25
    for i in range(1, steps + 1):
        page.mouse.move(
            start_x + (target_x - start_x) * i / steps,
            start_y + random.uniform(-0.8, 0.8),
        )
        time.sleep(0.02 + random.uniform(0, 0.01))
    page.mouse.up()
    print("   👆 已松开，等待跳转回原页面...")

    # 跳转会销毁页面上下文，直接等目标页的 dl.list 出现即可
    try:
        page.wait_for_selector("dl.list", timeout=max_wait * 1000)
        return True
    except Exception:
        return False

def fetch_page_html(browser, page_num, max_retries=3):
    """抓取一页房源列表 HTML。

    每次尝试都新建一个干净的浏览器上下文（新指纹），相当于一个新访客，
    避免风控在同一个会话上持续拦截；也能把偶发的网络错误隔离开。
    """
    if page_num == 1:
        url = "https://zu.fang.com/zz/house1/"
    else:
        url = f"https://zu.fang.com/zz/house1/i{page_num}/"
    print(f"📥 正在抓取第 {page_num} 页: {url}")

    global TRUSTED_COOKIES
    for attempt in range(1, max_retries + 1):
        # 新建独立上下文 + 页面，模拟新访客
        context = browser.new_context(
            viewport={"width": 1366, "height": 768},
            locale="zh-CN",
        )
        # 带上之前验证通过的 cookie（含 otherid），减少重复触发验证码
        if TRUSTED_COOKIES:
            try:
                context.add_cookies(TRUSTED_COOKIES)
            except Exception:
                pass
        page = context.new_page()
        page.add_init_script(STEALTH_JS)
        try:
            page.goto(url, timeout=60000, wait_until="domcontentloaded")

            # 1) 先检测是否被弹验证码；若被弹，尝试自动拖动滑块通过
            if is_captcha_page(page):
                print("🛠 检测到滑块验证码，尝试自动拖动通过...")
                solved = solve_slider(page)
                if solved:
                    print("   ✅ 滑块验证通过，已回到目标页面")
                    # 记住本次验证后的 cookie，后续页面复用
                    TRUSTED_COOKIES = context.cookies()
                else:
                    shot = f"captcha_{page_num}_a{attempt}.png"
                    page.screenshot(path=shot)
                    raise RuntimeError(f"滑块自动验证失败，截图已保存 {shot}")

            # 2) 等房源列表渲染完成
            page.wait_for_selector("dl.list", timeout=20000)
            time.sleep(random.uniform(1.2, 2.5))
            # 模拟滚动加载懒数据
            page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.6)")
            time.sleep(random.uniform(1, 2))

            html = page.content()
            return html

        except Exception as e:
            print(f"⚠️ 第 {page_num} 页尝试 {attempt}/{max_retries} 失败: {str(e)[:120]}")
            if attempt < max_retries:
                wait_time = 6 * attempt + random.uniform(2, 5)
                print(f"⏳ 等待 {wait_time:.1f} 秒重试...")
                time.sleep(wait_time)
        finally:
            context.close()

    print(f"❌ 第 {page_num} 页在 {max_retries} 次尝试后失败")
    return None

# ==================== 主函数 ====================
def spider_house(total_pages=20):
    print(f"🚀 开始爬取房天下租房郑州站，共 {total_pages} 页")
    print("=" * 50)
    create_table_if_not_exists()
    all_count = 0
    success_count = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=LAUNCH_ARGS,
        )

        consecutive_fails = 0
        for page_num in range(1, total_pages + 1):
            html = fetch_page_html(browser, page_num)
            if not html:
                consecutive_fails += 1
                print(f"⚠️ 第 {page_num} 页抓取失败，跳过")
                if consecutive_fails >= 2:
                    cooldown = random.uniform(60, 120)
                    print(f"⏳ 连续失败 {consecutive_fails} 次，冷却 {cooldown:.0f} 秒（让IP风控降级）...")
                    time.sleep(cooldown)
                else:
                    time.sleep(random.uniform(12, 20))
                continue
            consecutive_fails = 0

            houses = parse_page_html(html)
            print(f"📊 第 {page_num} 页解析到 {len(houses)} 条房源")
            for house in houses:
                all_count += 1
                if save_house_to_db(house):
                    success_count += 1
                    if success_count <= 5 or all_count % 20 == 0:
                        print(
                            f"  ✅ 示例: {house.get('community')} | {house.get('layout')} | {house.get('area')}㎡ | {house.get('rent')}元/月 | {house.get('metro_line', '')}")

            sleep_time = random.uniform(20, 35)
            print(f"⏳ 等待 {sleep_time:.1f} 秒后继续...")
            time.sleep(sleep_time)
            print("-" * 30)

        browser.close()

    print("=" * 50)
    print(f"🎉 爬取完成！共抓取 {all_count} 条，成功入库 {success_count} 条")
    return success_count

if __name__ == "__main__":
    spider_house(total_pages=100)   # 先测试1页，确认能抓到数据再改多页
