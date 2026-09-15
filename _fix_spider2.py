# -*- coding: utf-8 -*-
"""一次性修复脚本：重写爬虫.py 的 fetch_page_html 为合规版本"""
import io
import os

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
p = os.path.join(PROJECT_ROOT, 'Agent', '数据库操作', '爬虫.py')

with io.open(p, 'r', encoding='utf-8') as f:
    text = f.read()

old = '''def fetch_page_html(browser, page_num, max_retries=3):
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
    return None'''

new = '''def fetch_page_html(browser, page_num, max_retries=3):
    """抓取一页房源列表 HTML（合规版）。

    每次请求之间间隔随机等待，遵守网站访问频率限制；若页面被平台风控拦截
    （返回验证页或空列表），按失败处理并等待后重试，不绕过任何验证机制。
    """
    if page_num == 1:
        url = "https://zu.fang.com/zz/house1/"
    else:
        url = f"https://zu.fang.com/zz/house1/i{page_num}/"
    print(f"📥 正在抓取第 {page_num} 页: {url}")

    for attempt in range(1, max_retries + 1):
        context = browser.new_context(
            viewport={"width": 1366, "height": 768},
            locale="zh-CN",
        )
        page = context.new_page()
        try:
            page.goto(url, timeout=60000, wait_until="domcontentloaded")

            # 等房源列表渲染完成；若被风控拦截（页面无 dl.list），视为失败
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
    return None'''

if old in text:
    text = text.replace(old, new, 1)
    print('[fetch_page_html] OK rewritten')
else:
    print('[fetch_page_html] WARN: not found, skip')

# 冷却策略里的"让IP风控降级"表述弱化
old_cool = '''                if consecutive_fails >= 2:
                    cooldown = random.uniform(60, 120)
                    print(f"⏳ 连续失败 {consecutive_fails} 次，冷却 {cooldown:.0f} 秒（让IP风控降级）...")
                    time.sleep(cooldown)'''
new_cool = '''                if consecutive_fails >= 2:
                    cooldown = random.uniform(60, 120)
                    print(f"⏳ 连续失败 {consecutive_fails} 次，暂停 {cooldown:.0f} 秒后重试...")
                    time.sleep(cooldown)'''
if old_cool in text:
    text = text.replace(old_cool, new_cool, 1)
    print('[cooldown msg] OK')

with io.open(p, 'w', encoding='utf-8', newline='') as f:
    f.write(text)
print('DONE')
