#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""华为云扫码登录：生成二维码 -> 等待扫码 -> 保存 state.json

独立运行:  python3 qr_login.py [等待分钟数]       默认 8 分钟
被 CLI 调用: from qr_login import run_qr_login
"""
import os
import sys
import time

from playwright.sync_api import sync_playwright

from checkin import (LOGIN_URL, GROW_URL, STATE_FILE, DATA_DIR,
                     SCREENSHOT_DIR, is_logged_in, logger)

QR_FILE = os.path.join(DATA_DIR, "qrcode.png")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

QR_SELECTORS = [
    "canvas",
    "img[src*='qr']", "img[src*='QR']", "img[src*='qrcode']",
    "[class*='qr-code']", "[class*='qrcode']", "[class*='qrCode']",
    "[class*='qr-img']", "[id*='qr']", "[id*='QR']",
    ".hwid-qrcode", ".qr-code", "#qrCode",
]


def decode_qr(path):
    """解码二维码图片内容，失败返回 None"""
    try:
        import cv2
        img = cv2.imread(path)
        if img is None:
            return None
        data, _, _ = cv2.QRCodeDetector().detectAndDecode(img)
        return data or None
    except Exception:
        return None


def print_qr_ascii(path):
    """把二维码打印到终端（便于直接拿手机扫屏幕）"""
    data = decode_qr(path)
    if not data:
        return False
    try:
        import qrcode
        q = qrcode.QRCode(border=1)
        q.add_data(data)
        q.make()
        print()
        q.print_ascii(out=sys.stdout, invert=True)
        print()
        return True
    except Exception:
        return False


def save_qr(page):
    """定位并保存二维码，返回 (选择器, 宽)"""
    for sel in QR_SELECTORS:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                box = el.bounding_box()
                if box and box["width"] >= 60 and box["height"] >= 60:
                    el.screenshot(path=QR_FILE)
                    return sel, int(box["width"])
        except Exception:
            continue
    return None, 0


def run_qr_login(wait_min=8, show_ascii=True):
    """执行扫码登录，成功返回 True"""
    logger.info("=" * 56)
    logger.info(f"扫码登录启动，最长等待 {wait_min} 分钟")
    logger.info("=" * 56)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent=UA, locale="zh-CN", timezone_id="Asia/Shanghai")
        ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
        page = ctx.new_page()

        page.goto(LOGIN_URL, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(6000)
        page.screenshot(path=os.path.join(SCREENSHOT_DIR, "qr_login_page.png"),
                        full_page=True)

        sel, w = save_qr(page)
        if sel:
            logger.info(f"二维码已生成: {QR_FILE}")
        else:
            logger.warning("未定位到二维码元素，已保存整页截图")

        if show_ascii:
            if print_qr_ascii(QR_FILE):
                print(">>> 请用【华为云 APP】扫描上方二维码，并在手机上确认登录")
            else:
                print(f">>> 终端无法渲染二维码，请打开图片扫码: {QR_FILE}")
        else:
            print(f">>> 二维码已保存: {QR_FILE}")

        deadline = time.time() + wait_min * 60
        last_qr = 0
        last_data = None
        logged = False

        while time.time() < deadline:
            # 每 25 秒刷新一次二维码（应对过期自动更新）
            if time.time() - last_qr > 25:
                save_qr(page)
                last_qr = time.time()
                cur = decode_qr(QR_FILE)
                if show_ascii and cur and cur != last_data:
                    last_data = cur
                    print("\n>>> 二维码已刷新，请扫描下方最新二维码：")
                    print_qr_ascii(QR_FILE)

            if is_logged_in(page):
                logger.info("接口确认已登录")
                logged = True
                break

            if "auth.huaweicloud.com" not in page.url:
                logger.info(f"已跳转到 {page.url[:80]}")
                logged = True
                break

            print(f"\r  等待扫码中... 剩余 {int(deadline - time.time())}s   ",
                  end="", flush=True)
            page.wait_for_timeout(5000)

        print()
        if not logged:
            logger.error("扫码等待超时")
            page.screenshot(path=os.path.join(SCREENSHOT_DIR, "qr_timeout.png"),
                            full_page=True)
            browser.close()
            return False

        page.wait_for_timeout(3000)
        page.goto(GROW_URL, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(5000)
        page.screenshot(path=os.path.join(SCREENSHOT_DIR, "qr_logged_grow.png"),
                        full_page=True)

        ok = is_logged_in(page)
        ctx.storage_state(path=STATE_FILE)
        try:
            os.chmod(STATE_FILE, 0o600)
        except Exception:
            pass
        logger.info(f"登录状态已保存: {STATE_FILE}")
        browser.close()
        return ok


if __name__ == "__main__":
    wm = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    sys.exit(0 if run_qr_login(wm) else 1)
