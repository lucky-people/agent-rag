# -*- coding: utf-8 -*-
"""一次性修复脚本：爬虫.py 移除滑块破解/反自动化，密码改为密钥文件+环境变量读取"""
import io
import os

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
p = os.path.join(PROJECT_ROOT, 'Agent', '数据库操作', '爬虫.py')

with io.open(p, 'r', encoding='utf-8') as f:
    text = f.read()

# 1. 替换文档字符串（移除滑块破解描述）
old_doc = '''"""
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
"""'''
new_doc = '''"""
文件名: 爬虫.py
描述: 房天下郑州租房爬虫（合规开源版）
说明:
  1. 本脚本只做公开网页的常规抓取与解析，遵守 robots 协议与网站访问频率限制。
  2. 不含任何验证码破解、反自动化检测绕过逻辑；如遇平台风控拦截，
     请暂停抓取并等待一段时间后再运行，或改用平台官方数据接口。
  3. 数据仅用于学习研究，请勿用于商业用途。
"""'''
if old_doc in text:
    text = text.replace(old_doc, new_doc, 1)
    print('[docstring] OK')
else:
    print('[docstring] WARN: not found, skip')

# 2. 数据库密码
old_pw = """DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': '123456',      # 改成你的密码
    'database': 'rental',      # 改成你的数据库名
    'charset': 'utf8mb4'
}"""
new_pw = """# ========== 密钥加载（优先环境变量，其次 config_local/keys.py） ==========
# config_local/ 已被 .gitignore 排除，不会上传到仓库
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
if old_pw in text:
    text = text.replace(old_pw, new_pw, 1)
    print('[password] OK')
else:
    print('[password] WARN: not found, skip')

# 3. 移除 STEALTH_JS 反自动化脚本
old_stealth = '''# 反自动化检测脚本（try/catch 包裹，即使某一行失败也不影响页面加载）
STEALTH_JS = """
try { Object.defineProperty(navigator, 'webdriver', {get: () => undefined}); } catch (e) {}
try { Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]}); } catch (e) {}
window.chrome = window.chrome || { runtime: {} };
"""

'''
if old_stealth in text:
    text = text.replace(old_stealth, '', 1)
    print('[STEALTH_JS] OK removed')
else:
    print('[STEALTH_JS] WARN: not found, skip')

# 4. 移除滑块验证相关：TRUSTED_COOKIES、solve_slider、is_captcha_page 与调用
old_block = '''# 通过滑块验证后，把当前会话 cookie（含 otherid）存下来，后续页面带上可减少重复验证码
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

'''
if old_block in text:
    text = text.replace(old_block, '', 1)
    print('[solve_slider] OK removed')
else:
    print('[solve_slider] WARN: not found, skip')

# 5. 移除 is_captcha_page 函数（配合 fetch_page_html 修改）
old_captcha = '''# ==================== 抓取函数 ====================
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

'''
if old_captcha in text:
    text = text.replace(old_captcha, '', 1)
    print('[is_captcha_page] OK removed')
else:
    print('[is_captcha_page] WARN: not found, skip')

with io.open(p, 'w', encoding='utf-8', newline='') as f:
    f.write(text)
print('DONE')
