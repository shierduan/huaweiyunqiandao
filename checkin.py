#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
华为开发者中心（成长中心）自动签到程序  v2

用法:
  python3 checkin.py --login          # 自动登录（读取 config.json 中的账号密码）
  python3 checkin.py --login-manual   # 人工登录（配合 VNC，浏览器保持打开等你操作）
  python3 checkin.py --checkin        # 执行每日签到
  python3 checkin.py --status         # 查看登录状态与最近日志
  python3 checkin.py --probe          # 探测页面结构（调试用，输出页面可见元素）
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

from playwright.sync_api import sync_playwright

# ==================== 配置 ====================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 数据目录: 容器内由 HW_DATA_DIR=/app/data 指定并挂载宿主机 ./data，
# 宿主机直跑时默认用脚本下的 ./data —— 容器内外路径语义完全一致。
DATA_DIR = os.environ.get("HW_DATA_DIR") or os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

GROW_URL = "https://developer.huaweicloud.com/grow?ggw_kfz"
LOGIN_URL = ("https://auth.huaweicloud.com/authui/login.html"
             "?service=https%3A%2F%2Fdeveloper.huaweicloud.com%2Fgrow%3Fggw_kfz"
             "&locale=zh-cn#/login")
ISLOGIN_API = "https://devdata.huaweicloud.com/index/islogin?callback=checklogin"

STATE_FILE = os.path.join(DATA_DIR, "state.json")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
SCREENSHOT_DIR = os.path.join(DATA_DIR, "screenshots")
LOG_FILE = os.path.join(DATA_DIR, "checkin.log")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# ==================== 日志（北京时间） ====================
def _bj_now():
    return datetime.now(timezone(timedelta(hours=8)))

class _BJFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        # 本机 time.strftime 对 %m/%d 损坏（输出如 2026-68-07 的非法月份），
        # 改用 datetime 运算手工拼接时间戳，彻底绕开 strftime。
        dt = datetime(1970, 1, 1) + timedelta(seconds=record.created) + timedelta(hours=8)
        return "%04d-%02d-%02d %02d:%02d:%02d" % (
            dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second)
logger = logging.getLogger("hwcheckin")
logger.setLevel(logging.INFO)
_fmt = _BJFormatter("%(asctime)s [%(levelname)s] %(message)s")
_fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
_fh.setFormatter(_fmt)
_sh = logging.StreamHandler(sys.stdout)
_sh.setFormatter(_fmt)
logger.handlers = [_fh, _sh]


def ensure_dirs():
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)


def shot(page, name):
    ensure_dirs()
    ts = _bj_now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(SCREENSHOT_DIR, f"{ts}_{name}.png")
    try:
        page.screenshot(path=path, full_page=True)
        logger.info(f"截图: {path}")
    except Exception as e:
        logger.warning(f"截图失败: {e}")
    return path


def load_config():
    """账号密码优先取环境变量，其次读 config.json。

    环境变量 HW_USERNAME / HW_PASSWORD（兼容 HW_USER / HW_PASS）优先，
    适用于青龙面板「环境变量」托管凭据、不在磁盘留明文。
    两者都不存在时才回退到 data/config.json。
    """
    user = os.environ.get("HW_USERNAME") or os.environ.get("HW_USER")
    pwd = os.environ.get("HW_PASSWORD") or os.environ.get("HW_PASS")
    if user and pwd:
        return {"username": user, "password": pwd}
    if not os.path.exists(CONFIG_FILE):
        return None
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"读取 config.json 失败: {e}")
        return None


# ==================== 浏览器 ====================
def launch(pw, headless=True, state=None, slow_mo=0):
    kwargs = dict(
        viewport={"width": 1440, "height": 900},
        user_agent=UA,
        locale="zh-CN",
        timezone_id="Asia/Shanghai",
    )
    if state and os.path.exists(state):
        kwargs["storage_state"] = state
    browser = pw.chromium.launch(
        headless=headless,
        args=["--no-sandbox", "--disable-dev-shm-usage",
              "--disable-blink-features=AutomationControlled"],
        slow_mo=slow_mo,
    )
    ctx = browser.new_context(**kwargs)
    # 去除 webdriver 特征，降低风控概率
    ctx.add_init_script(
        "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
    )
    return browser, ctx


def is_logged_in(page):
    """判断登录态。

    devdata 的 islogin 接口返回 JSONP 且**不含 isLogin 字段**，
    实际格式: checklogin({"userId":"xxx","username":"xxx", ...})
    因此判据为: userId / bbs_userID 非空。
    """
    try:
        resp = page.evaluate("""async () => {
            try {
                const r = await fetch('%s', {credentials:'include'});
                return await r.text();
            } catch(e) { return 'ERR:' + e.message; }
        }""" % ISLOGIN_API)
        m = re.search(r"\{.*\}", resp or "")
        if not m:
            logger.debug(f"islogin 未解析出 JSON: {(resp or '')[:120]}")
            return False
        data = json.loads(m.group(0))
        uid = data.get("userId") or data.get("bbs_userID") or ""
        if uid:
            logger.info(f"已登录, 账号={data.get('username') or '未知'}, userId={uid[:12]}...")
            return True
        logger.info("islogin 返回但 userId 为空 -> 未登录")
        return False
    except Exception as e:
        logger.warning(f"islogin 检查异常: {e}")
        return False


def check_captcha(page):
    """检测是否出现验证码/风控拦截，返回描述字符串或 None"""
    try:
        txt = page.inner_text("body")
    except Exception:
        return None
    marks = ["滑块", "拖动", "请完成安全验证", "验证码", "图形验证",
             "安全验证", "人机验证", "异常登录", "身份核实"]
    for m in marks:
        if m in txt:
            return m
    # 检查滑块 iframe / 元素
    for sel in ["#captcha", ".captcha", "[class*=slider]", "[class*=captcha]",
                "iframe[src*=captcha]"]:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                return f"元素命中 {sel}"
        except Exception:
            pass
    return None


# ==================== 登录 ====================

def check_sms_otp(page):
    """检测是否出现短信验证码（登录验证）弹窗，返回 True/False"""
    try:
        inp = page.query_selector("input[placeholder*='6位']")
        if inp is None:
            inp = page.query_selector("input[placeholder*='验证码']")
        if inp is None:
            return False
        txt = page.inner_text("body")
        if "登录验证" in txt or "身份验证" in txt or "获取验证码" in txt:
            return True
    except Exception:
        return False
    return False


def _handle_sms_otp(page, timeout=600):
    """点击获取验证码，读取 data/otp.txt 中的 6 位码补全登录。
    返回 True 表示已提交验证码（调用方继续等待登录结果），False 表示失败。"""
    OTP_FILE = os.path.join(DATA_DIR, "otp.txt")
    try:
        page.click("text=获取验证码", timeout=10000)
        logger.info("已点击『获取验证码』，等待短信（请把 6 位码写入 data/otp.txt）")
    except Exception as e:
        logger.warning(f"点击获取验证码失败: {e}")
    deadline = time.time() + timeout
    code = None
    while time.time() < deadline:
        try:
            if os.path.exists(OTP_FILE):
                with open(OTP_FILE, "r", encoding="utf-8") as f:
                    c = f.read().strip()
                m = re.search(r"\d{6}", c)
                if m:
                    code = m.group(0)
                    break
        except Exception:
            pass
        page.wait_for_timeout(2000)
    if not code:
        logger.error("等待 data/otp.txt 中的验证码超时（%ds）" % timeout)
        return False
    try:
        inp = page.wait_for_selector("input[placeholder*='6位']", timeout=10000)
        inp.click()
        inp.fill(code)
        logger.info("已填入短信验证码")
    except Exception as e:
        logger.warning(f"填写验证码失败: {e}")
        try:
            page.fill("input[placeholder*='验证码']", code)
        except Exception as e2:
            logger.error(f"填写验证码二次尝试也失败: {e2}")
            return False
    try:
        page.wait_for_timeout(1500)
        page.click("text=继续登录", timeout=10000)
        logger.info("已点击『继续登录』")
    except Exception as e:
        logger.error(f"点击继续登录失败: {e}")
        return False
    try:
        os.remove(OTP_FILE)
    except Exception:
        pass
    return True


def _wait_login_result(page, timeout=60):
    """提交验证码后等待登录成功"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        page.wait_for_timeout(3000)
        if _handle_mfa_prompt(page):
            continue
        if "auth.huaweicloud.com" not in page.url:
            logger.info(f"已离开登录页 -> {page.url[:80]}")
            return True
        if is_logged_in(page):
            logger.info("接口确认已登录")
            return True
        logger.info("  验证码提交后等待登录结果...")
    logger.error("验证码提交后仍未登录")
    return False


def _all_frames(page):
    """返回主页面 + 全部 iframe 的 frame 列表（华为云登录弹窗常在 iframe 内）"""
    try:
        return list(page.frames) or [page]
    except Exception:
        return [page]


def _frames_text(page, limit=4000):
    """拼接所有 frame 的可见文本（用于跨 frame 判定）"""
    parts = []
    for f in _all_frames(page):
        try:
            parts.append(f.inner_text("body"))
        except Exception:
            continue
    return "\n".join(parts)[:limit]


def _handle_mfa_prompt(page):
    """处理登录后可能弹出的「登录验证 - MFA 设备绑定」提示页。

    页面特征：标题「登录验证」，提示账号未启用登录保护；
    需勾选「我已了解账号暂不开启登录保护的被盗风险，30 天内不再提示」
    （input#promptBindAndEnableCheckbox）后点「暂不绑定」
    （div#promptBindAndEnableCancelBtn）跳过，不绑定 MFA。
    注意：该弹窗常渲染在 iframe 中，必须跨 frame 查找。
    返回 True 表示检测到该页（无论是否成功跳过），调用方应继续轮询登录结果。
    """
    txt = _frames_text(page)
    if ("暂不绑定" not in txt) and not ("登录保护" in txt and "立即绑定" in txt):
        return False
    logger.info("检测到 MFA 设备绑定提示页，尝试跳过（勾选不再提示 + 暂不绑定）...")
    shot(page, "mfa_prompt")

    # 1) 勾选「30 天内不再提示」
    checked = False
    for f in _all_frames(page):
        for sel in ["#promptBindAndEnableCheckbox",
                    "div.notBindCheckboxDiv input[type='checkbox']",
                    "input[type='checkbox']"]:
            try:
                cb = f.query_selector(sel)
                if cb is None:
                    continue
                if cb.is_checked():
                    checked = True
                    break
                cb.check(force=True)
                checked = True
                logger.info(f"已勾选『30 天内不再提示』({sel})")
                break
            except Exception:
                continue
        if checked:
            break
    if not checked:
        logger.warning("未能勾选复选框，仍尝试点击『暂不绑定』")
    page.wait_for_timeout(1200)

    # 2) 点击「暂不绑定」
    clicked = False
    for f in _all_frames(page):
        for sel in ["#promptBindAndEnableCancelBtn",
                    "div.cancelBtn:has-text('暂不绑定')",
                    "text=暂不绑定"]:
            try:
                el = f.query_selector(sel)
                if el and el.is_visible():
                    el.click()
                    clicked = True
                    logger.info(f"已点击『暂不绑定』({sel})")
                    break
            except Exception:
                continue
        if clicked:
            break
    if not clicked:
        logger.error("未找到『暂不绑定』按钮")
        shot(page, "mfa_btn_not_found")
    page.wait_for_timeout(4000)
    return True


def login_in_page(page, username, password):
    """在当前 page 中完成账号密码登录，成功返回 True。

    抽成独立函数的原因：华为云网页登录态只有约 30 分钟，
    签到时若发现失效，可在**同一个浏览器会话**里直接补一次登录，
    无需另起浏览器，也让定时任务无需人工介入。
    """
    logger.info("打开登录页，执行账号密码登录")
    page.goto(LOGIN_URL, wait_until="networkidle", timeout=60000)
    page.wait_for_timeout(5000)

    # 切换到「密码登录」
    try:
        page.click("text=密码登录", timeout=10000)
        logger.info("已切换到【密码登录】")
        page.wait_for_timeout(3000)
    except Exception as e:
        logger.warning(f"切换密码登录失败（可能已在该模式）: {e}")

    # 填写账号
    acc = page.wait_for_selector("input.hwid-input.userAccount", timeout=20000)
    acc.click()
    page.wait_for_timeout(500)
    acc.type(username, delay=80)
    logger.info("账号已填写")
    page.wait_for_timeout(1000)

    # 填写密码
    pwd = page.wait_for_selector("input.hwid-input-pwd", timeout=20000)
    pwd.click()
    page.wait_for_timeout(500)
    pwd.type(password, delay=80)
    logger.info("密码已填写")
    page.wait_for_timeout(1000)
    shot(page, "login_filled")

    # 点击登录
    clicked = False
    for sel in ["span.hwid-vertical-align:has-text('登录')",
                "button:has-text('登录')",
                ".hwid-login-btn",
                "text=登录"]:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.click()
                clicked = True
                logger.info(f"已点击登录按钮 ({sel})")
                break
        except Exception:
            continue
    if not clicked:
        logger.error("未找到登录按钮")
        shot(page, "login_btn_not_found")
        return False

    # 等待登录结果
    logger.info("等待登录结果（最多 90 秒）...")
    for i in range(30):
        page.wait_for_timeout(3000)
        # MFA 绑定提示页：先跳过再继续等待
        if _handle_mfa_prompt(page):
            if "auth.huaweicloud.com" not in page.url or is_logged_in(page):
                logger.info(f"MFA 提示已跳过，登录继续 -> {page.url[:80]}")
                return True
            continue
        cap = check_captcha(page)
        if cap:
            if check_sms_otp(page):
                logger.warning("⚠ 检测到短信验证码，尝试自动处理（需 data/otp.txt 中的 6 位码）")
                if _handle_sms_otp(page):
                    logger.info("短信验证码已提交，转入登录结果等待")
                    return _wait_login_result(page)
                logger.error("短信验证码处理失败")
                shot(page, "login_captcha")
                return False
            logger.warning(f"⚠ 检测到风控/验证码: {cap}（非短信验证，无法自动处理）")
            logger.warning("自动登录被拦截，请改用扫码登录或 VNC 手动登录")
            shot(page, "login_captcha")
            return False
        if "auth.huaweicloud.com" not in page.url:
            logger.info(f"已离开登录页 -> {page.url[:80]}")
            return True
        if is_logged_in(page):
            logger.info("接口确认已登录")
            return True
        logger.info(f"  等待中... {i*3+3}s 当前: {page.url[:80]}")

    logger.error("登录未成功，仍在登录页")
    for f in _all_frames(page):
        try:
            logger.info(f"  frame[{f.url[:60]}] 文本: "
                        + f.inner_text("body")[:200].replace("\n", " "))
        except Exception:
            continue
    shot(page, "login_stuck")
    return False


def do_auto_login():
    """使用环境变量或 config.json 中的账号密码自动登录并保存状态"""
    conf = load_config()
    if not conf or not conf.get("username") or not conf.get("password"):
        logger.error("缺少账号密码：环境变量 HW_USERNAME/HW_PASSWORD 未设置，"
                     "config.json 中也没有 username/password")
        logger.error(f"青龙模式请在面板「环境变量」添加 HW_USERNAME / HW_PASSWORD；"
                     f"本地模式可在 {CONFIG_FILE} 填写 "
                     '{"username":"你的账号","password":"你的密码"}')
        return False

    username = conf["username"]
    password = conf["password"]
    logger.info("=" * 56)
    logger.info("自动登录模式启动")
    logger.info("=" * 56)

    with sync_playwright() as pw:
        browser, ctx = launch(pw, headless=True)
        page = ctx.new_page()
        try:
            if not login_in_page(page, username, password):
                browser.close()
                return False

            page.wait_for_timeout(3000)
            page.goto(GROW_URL, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(5000)
            shot(page, "login_done_grow")

            if is_logged_in(page):
                ctx.storage_state(path=STATE_FILE)
                logger.info(f"✅ 登录成功，状态已保存: {STATE_FILE}")
                browser.close()
                return True

            logger.warning("登录后仍未检测到登录态")
            shot(page, "login_maybe_failed")
            browser.close()
            return False
        except Exception as e:
            logger.exception(f"登录过程异常: {e}")
            try:
                shot(page, "login_exception")
            except Exception:
                pass
            browser.close()
            return False


def do_manual_login(wait_minutes=10):
    """人工登录：打开有头浏览器（需 Xvfb/VNC），等待用户操作"""
    logger.info("=" * 56)
    logger.info("人工登录模式（请在 VNC 中操作浏览器）")
    logger.info(f"最长等待 {wait_minutes} 分钟，登录成功后自动保存状态")
    logger.info("=" * 56)

    with sync_playwright() as pw:
        browser, ctx = launch(pw, headless=False, slow_mo=200)
        page = ctx.new_page()
        try:
            page.goto(GROW_URL, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(4000)
            logger.info("已打开成长中心，请在浏览器中完成登录")

            deadline = time.time() + wait_minutes * 60
            while time.time() < deadline:
                page.wait_for_timeout(10000)
                if is_logged_in(page):
                    logger.info("✅ 检测到登录成功")
                    page.wait_for_timeout(3000)
                    shot(page, "manual_login_success")
                    ctx.storage_state(path=STATE_FILE)
                    logger.info(f"状态已保存: {STATE_FILE}")
                    browser.close()
                    return True
                left = int(deadline - time.time())
                logger.info(f"  等待登录中... 剩余 {left}s")

            logger.error("等待登录超时")
            shot(page, "manual_login_timeout")
            browser.close()
            return False
        except Exception as e:
            logger.exception(f"人工登录异常: {e}")
            browser.close()
            return False


# ==================== 签到 ====================
def get_streak(page):
    """读取「已连续签到（天）」的数值"""
    try:
        txt = page.inner_text("body")
        m = re.search(r"(\d+)\s*已连续签到", txt)
        if m:
            return int(m.group(1))
    except Exception as e:
        logger.warning(f"读取连续签到天数失败: {e}")
    return None


def find_and_click_checkin(page):
    """查找并点击签到按钮"""
    page.wait_for_load_state("networkidle", timeout=30000)
    page.wait_for_timeout(3000)
    shot(page, "before_checkin")

    # 先判断是否已经签到过：已签到时按钮文案会变为「已签到」并消失
    btn = page.query_selector("button:has-text('立即签到')")
    if not btn or not btn.is_visible():
        logger.info("未发现「立即签到」按钮 -> 今日已签到，跳过点击")
        return False

    # 成长中心实际使用 tiny-ui 组件库，签到按钮为
    # <button class="tiny-button tiny-button--default">立即签到</button>
    candidate_selectors = [
        "button:has-text('立即签到')",
        "button.tiny-button:has-text('签到')",
        "button:has-text('签到')",
        "button:has-text('打卡')",
        "a:has-text('签到')",
        "div:has-text('签到')",
        "span:has-text('签到')",
        "text=每日签到",
        "text=立即签到",
        "text=签到",
        "text=打卡",
        "[class*='sign-in']", "[class*='signin']", "[class*='check-in']",
    ]

    for sel in candidate_selectors:
        try:
            els = page.query_selector_all(sel)
            for el in els:
                if not el.is_visible():
                    continue
                t = (el.inner_text() or "").strip()
                if "已签到" in t or "已连续签到" in t:
                    continue
                if "签" in t or "打卡" in t:
                    box = el.bounding_box()
                    # 过滤掉面积过大（整块容器）的元素
                    if box and box["width"] > 400:
                        continue
                    logger.info(f"命中签到元素: {sel} text='{t[:20]}'")
                    el.scroll_into_view_if_needed()
                    page.wait_for_timeout(1000)
                    el.click()
                    page.wait_for_timeout(3000)
                    shot(page, "after_checkin_click")
                    return True
        except Exception:
            continue

    logger.warning("标准选择器未命中，改用 JS 扫描")
    try:
        res = page.evaluate("""() => {
            const out = [];
            document.querySelectorAll('*').forEach(el => {
                if (el.children.length !== 0) return;
                const t = (el.textContent || '').trim();
                if (!t) return;
                if (t.indexOf('已签到') >= 0 || t.indexOf('已连续签到') >= 0) return;
                if ((t.indexOf('签') >= 0 || t.indexOf('打卡') >= 0) && t.length <= 15) {
                    const r = el.getBoundingClientRect();
                    if (r.width > 0 && r.height > 0 && r.width < 400) {
                        out.push({tag: el.tagName, txt: t,
                                  cls: String(el.className||'').slice(0,60),
                                  id: el.id, x: Math.round(r.x+r.width/2),
                                  y: Math.round(r.y+r.height/2)});
                    }
                }
            });
            return out;
        }""")
        if res:
            logger.info(f"JS 扫描结果: {json.dumps(res, ensure_ascii=False)[:400]}")
            for item in res:
                try:
                    sel = item["tag"].lower()
                    if item.get("id"):
                        sel += "#" + item["id"]
                    elif item.get("cls"):
                        sel += "." + item["cls"].split()[0]
                    el = page.query_selector(sel)
                    if el and el.is_visible():
                        el.scroll_into_view_if_needed()
                        page.wait_for_timeout(800)
                        el.click()
                        page.wait_for_timeout(3000)
                        shot(page, "after_checkin_js_click")
                        return True
                except Exception:
                    continue
    except Exception as e:
        logger.error(f"JS 扫描失败: {e}")
    return False


def do_checkin():
    logger.info("=" * 56)
    logger.info("每日签到任务启动")
    logger.info("=" * 56)

    if not os.path.exists(STATE_FILE):
        logger.error(f"状态文件不存在: {STATE_FILE}，请先执行 --login")
        return False

    with sync_playwright() as pw:
        browser, ctx = launch(pw, headless=True, state=STATE_FILE)
        page = ctx.new_page()
        try:
            page.goto(GROW_URL, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(5000)

            if not is_logged_in(page):
                # 华为云登录态约 30 分钟即失效，定时任务必然遇到。
                # 若配置了账号密码，就在当前会话里直接补登录。
                conf = load_config()
                if conf and conf.get("username") and conf.get("password"):
                    logger.warning("登录态已失效，尝试用环境变量/config.json 自动登录...")
                    if not login_in_page(page, conf["username"],
                                         conf["password"]):
                        logger.error("自动登录失败")
                        shot(page, "auto_login_failed")
                        browser.close()
                        return False
                    page.goto(GROW_URL, wait_until="networkidle", timeout=60000)
                    page.wait_for_timeout(5000)
                    if not is_logged_in(page):
                        logger.error("自动登录后仍未生效")
                        browser.close()
                        return False
                    logger.info("✅ 自动登录成功，继续执行签到")
                    ctx.storage_state(path=STATE_FILE)
                else:
                    logger.error("登录态已失效，且未配置账号密码")
                    logger.error("请在青龙面板「环境变量」添加 HW_USERNAME / "
                                 "HW_PASSWORD（或 data/config.json）以实现全自动")
                    shot(page, "not_logged_in")
                    browser.close()
                    return False
            else:
                logger.info("登录态有效")

            page.wait_for_timeout(3000)
            shot(page, "grow_page")

            streak_before = get_streak(page)
            logger.info(f"签到前连续天数: {streak_before}")

            logger.info("查找签到按钮...")
            clicked = find_and_click_checkin(page)

            page.wait_for_timeout(4000)
            shot(page, "checkin_result")

            # 重新加载页面读取最新连续天数（最可靠的成功判据）
            page.goto(GROW_URL, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(5000)
            streak_after = get_streak(page)
            logger.info(f"签到后连续天数: {streak_after}")

            body_after = page.inner_text("body")
            btn_now = page.query_selector("button:has-text('立即签到')")
            still_has_btn = bool(btn_now and btn_now.is_visible())

            if streak_before is not None and streak_after is not None \
                    and streak_after > streak_before:
                logger.info(f"✅ 签到成功: 连续天数 {streak_before} -> {streak_after}")
                result = True
            elif clicked and not still_has_btn:
                logger.info("✅ 签到按钮已消失，判定签到完成")
                result = True
            elif streak_after is not None and streak_after == streak_before \
                    and not clicked:
                logger.warning(f"未找到签到按钮且连续天数未变({streak_after})，"
                               "今日可能已签到")
                result = True
            else:
                logger.warning("签到结果不明确，请查看截图确认")
                logger.info("页面片段: " + body_after[:300].replace("\n", " "))
                result = False

            ctx.storage_state(path=STATE_FILE)
            logger.info("已刷新并保存登录状态")
            browser.close()
            return result
        except Exception as e:
            logger.exception(f"签到过程异常: {e}")
            try:
                shot(page, "checkin_exception")
            except Exception:
                pass
            browser.close()
            return False


# ==================== 状态 / 探测 ====================
def do_status():
    logger.info("=" * 56)
    logger.info("状态检查")
    logger.info("=" * 56)
    if not os.path.exists(STATE_FILE):
        logger.error(f"状态文件不存在: {STATE_FILE}，请先 --login")
        return
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)
    cookies = state.get("cookies", [])
    logger.info(f"状态文件: {STATE_FILE}")
    logger.info(f"Cookie 数量: {len(cookies)}")
    for c in cookies:
        n = (c.get("name") or "").lower()
        if any(k in n for k in ["session", "token", "auth", "login", "hwscs", "uid"]):
            exp = c.get("expires", -1)
            exp_s = "会话级" if exp == -1 else _bj_now().fromtimestamp(exp).strftime("%Y-%m-%d %H:%M")
            logger.info(f"  - {c['name']}  domain={c.get('domain')}  过期={exp_s}")
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
        logger.info("最近日志:")
        for line in lines[-15:]:
            print("  " + line.rstrip())


def do_probe():
    """探测页面结构（调试）"""
    with sync_playwright() as pw:
        state = STATE_FILE if os.path.exists(STATE_FILE) else None
        browser, ctx = launch(pw, headless=True, state=state)
        page = ctx.new_page()
        page.goto(GROW_URL, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(6000)
        logger.info(f"URL: {page.url}")
        logger.info(f"TITLE: {page.title()}")
        logger.info(f"已登录: {is_logged_in(page)}")
        print("=== 页面文本（前1200字） ===")
        print(page.inner_text("body")[:1200])
        print("=== 可见叶子元素 ===")
        res = page.evaluate("""() => {
            const out=[];
            document.querySelectorAll('*').forEach(el=>{
                if(el.children.length!==0) return;
                const t=(el.textContent||'').trim();
                if(!t || t.length>18) return;
                const r=el.getBoundingClientRect();
                if(r.width===0||r.height===0) return;
                out.push({tag:el.tagName, txt:t,
                          cls:String(el.className||'').slice(0,60), id:el.id,
                          x:Math.round(r.x), y:Math.round(r.y)});
            });
            return out.slice(0,60);
        }""")
        print(json.dumps(res, ensure_ascii=False, indent=1))
        shot(page, "probe")
        browser.close()




# ==================== 积分与代金券检测 ====================
def extract_points(page):
    """读取「我的积分」数值"""
    try:
        txt = page.inner_text("body")
        m = re.search(r"([\d,]+)\s*我的积分", txt)
        if m:
            return int(m.group(1).replace(",", ""))
    except Exception as e:
        logger.warning(f"读取积分失败: {e}")
    return None


def extract_vouchers(page):
    """解析积分兑换区的代金券卡片，返回结构化列表（只读，不点击兑换）"""
    vouchers = []
    try:
        page.wait_for_selector("div.cardItem", timeout=15000)
    except Exception:
        pass
    cards = page.query_selector_all("div.cardItem")
    for card in cards:
        try:
            title_el = card.query_selector(".titleBox .title") or card.query_selector(".title")
            name = title_el.inner_text().strip() if title_el else ""
            core_el = card.query_selector(".core")
            core_txt = core_el.inner_text().strip() if core_el else ""
            cost_m = re.search(r"([\d,]+)\s*积分", core_txt)
            cost = int(cost_m.group(1).replace(",", "")) if cost_m else None
            card_txt = card.inner_text()
            stock_m = re.search(r"([\d,]+)\s*库存", card_txt)
            stock = int(stock_m.group(1).replace(",", "")) if stock_m else None
            btn = card.query_selector("button")
            btn_disabled = bool(btn and btn.is_disabled()) if btn else None
            vouchers.append({"name": name, "cost": cost, "stock": stock,
                             "btn_text": (btn.inner_text().strip() if btn else None),
                             "btn_disabled": btn_disabled})
        except Exception as e:
            logger.warning(f"解析代金券卡片失败: {e}")
    return vouchers


def voucher_status(points, v):
    """返回单张代金券的兑换判定（不触发实际兑换）"""
    stock = v.get("stock")
    cost = v.get("cost")
    if stock is None or stock <= 0:
        return "无库存"
    if points is not None and cost is not None and points < cost:
        return "积分不足"
    return "可兑换"


def do_detect():
    """检测当前积分 + 各类代金券是否可兑换（只读，不实际兑换）"""
    logger.info("=" * 56)
    logger.info("积分 / 代金券兑换检测")
    logger.info("=" * 56)
    if not os.path.exists(STATE_FILE):
        logger.error(f"状态文件不存在: {STATE_FILE}，请先执行 --login 或扫码登录")
        return False

    with sync_playwright() as pw:
        browser, ctx = launch(pw, headless=True, state=STATE_FILE)
        page = ctx.new_page()
        try:
            page.goto(GROW_URL, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(6000)

            if not is_logged_in(page):
                conf = load_config()
                if conf and conf.get("username") and conf.get("password"):
                    logger.warning("登录态已失效，尝试用环境变量/config.json 自动登录...")
                    if not login_in_page(page, conf["username"], conf["password"]):
                        logger.error("自动登录失败")
                        browser.close()
                        return False
                    page.goto(GROW_URL, wait_until="networkidle", timeout=60000)
                    page.wait_for_timeout(6000)
                    if not is_logged_in(page):
                        logger.error("自动登录后仍无效")
                        browser.close()
                        return False
                    logger.info("自动登录成功")
                    ctx.storage_state(path=STATE_FILE)
                else:
                    logger.error("登录态已失效，且未配置账号密码")
                    browser.close()
                    return False
            else:
                logger.info("登录态有效")

            points = extract_points(page)
            logger.info(f"当前积分: {points if points is not None else '未知'}")

            vouchers = extract_vouchers(page)
            cash = [v for v in vouchers if "代金券" in (v.get("name") or "")]
            others = [v for v in vouchers if "代金券" not in (v.get("name") or "")]
            logger.info(f"兑换区卡片共 {len(vouchers)} 个，其中代金券 {len(cash)} 个")

            report = {"generated_at": _bj_now().strftime("%Y-%m-%d %H:%M:%S"),
                      "points": points, "vouchers": []}
            redeemable = []
            for v in cash:
                status = voucher_status(points, v)
                v["status"] = status
                v["redeemable"] = (status == "可兑换")
                if v["redeemable"]:
                    redeemable.append(v["name"])
                extra = ""
                if status == "积分不足":
                    extra = f"（当前积分 {points}）"
                elif status == "无库存":
                    extra = "（已兑完/无库存）"
                logger.info(f"  - {v['name']}: 需{v['cost']}积分, 库存{v['stock']}, 状态={status}{extra}")
                report["vouchers"].append(v)

            if others:
                logger.info("其他卡片(非代金券，如任务/活动卡): " + ", ".join((o.get('name') or '?') for o in others))

            if redeemable:
                logger.info(f"可兑换代金券: {', '.join(redeemable)}")
            else:
                logger.info("当前积分不足以兑换任何代金券（或均无库存）")

            try:
                out = os.path.join(DATA_DIR, "detect.json")
                with open(out, "w", encoding="utf-8") as f:
                    json.dump(report, f, ensure_ascii=False, indent=2)
                logger.info(f"检测报告已保存: {out}")
            except Exception as e:
                logger.warning(f"保存检测报告失败: {e}")

            browser.close()
            return True
        except Exception as e:
            logger.exception(f"检测过程异常: {e}")
            browser.close()
            return False

def main():
    ap = argparse.ArgumentParser(description="华为云开发者成长中心自动签到")
    ap.add_argument("--login", action="store_true", help="自动登录（config.json）")
    ap.add_argument("--login-manual", action="store_true", help="人工登录（VNC）")
    ap.add_argument("--checkin", action="store_true", help="执行签到")
    ap.add_argument("--status", action="store_true", help="查看状态")
    ap.add_argument("--probe", action="store_true", help="探测页面结构")
    ap.add_argument("--detect", action="store_true", help="检测积分与代金券可兑换状态")
    ap.add_argument("--wait", type=int, default=10, help="人工登录等待分钟数")
    args = ap.parse_args()

    ensure_dirs()

    if args.login:
        sys.exit(0 if do_auto_login() else 1)
    elif args.login_manual:
        sys.exit(0 if do_manual_login(args.wait) else 1)
    elif args.checkin:
        sys.exit(0 if do_checkin() else 1)
    elif args.status:
        do_status()
    elif args.probe:
        do_probe()
    elif args.detect:
        sys.exit(0 if do_detect() else 1)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
