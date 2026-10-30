#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""华为云成长中心签到助手 - 交互式命令行

提供: 查看状态(签到/积分/连续天数) / 立即签到 / 扫码登录 / 查看日志 / 查看 cookies
"""
import json
import os
import re
import sys
import time
from datetime import datetime

from playwright.sync_api import sync_playwright

from checkin import (GROW_URL, STATE_FILE, LOG_FILE, DATA_DIR, ISLOGIN_API,
                     launch, get_streak, is_logged_in, do_checkin, do_detect, logger)
from qr_login import run_qr_login

LINE = "=" * 52


def get_account(page):
    """从 islogin 接口取用户名/ID"""
    try:
        resp = page.evaluate("""async () => {
            try {
                const r = await fetch('%s', {credentials:'include'});
                return await r.text();
            } catch(e) { return ''; }
        }""" % ISLOGIN_API)
        m = re.search(r"\{.*\}", resp or "")
        if m:
            d = json.loads(m.group(0))
            return d.get("username"), d.get("userId")
    except Exception:
        pass
    return None, None


def get_points(page):
    """读取「我的积分」数值"""
    try:
        txt = page.inner_text("body")
        m = re.search(r"([\d,]+)\s*我的积分", txt)
        if m:
            return int(m.group(1).replace(",", ""))
    except Exception:
        pass
    return None


def collect_info(page):
    """汇总页面关键信息"""
    txt = page.inner_text("body")
    username, uid = get_account(page)
    btn = page.query_selector("button:has-text('立即签到')")
    need = bool(btn and btn.is_visible())
    return {
        "logged": bool(uid),
        "username": username,
        "user_id": uid,
        "points": get_points(page),
        "streak": get_streak(page),
        "need_checkin": need,
        "checked_today": (not need) and ("已签到" in txt or "已连续签到" in txt),
    }


def show_info(info):
    print()
    print(LINE)
    print("  账号状态")
    print(LINE)
    if not info["logged"]:
        print("  登录态:  ❌ 未登录（请先选 3 扫码登录）")
        print(LINE)
        return
    print(f"  登录态:  ✅ 已登录   账号: {info['username'] or '-'}")
    pts = info["points"]
    print(f"  我的积分: {pts if pts is not None else '-'}")
    st = info["streak"]
    print(f"  连续签到: {st if st is not None else '-'} 天")
    if info["need_checkin"]:
        print("  今日签到: ⚪ 尚未签到（可领取）")
    else:
        print("  今日签到: ✅ 今日已签到")
    print(LINE)


def open_page():
    """打开成长中心页面，返回 (pw, browser, ctx, page)"""
    pw = sync_playwright().start()
    browser, ctx = launch(pw, headless=True, state=STATE_FILE)
    page = ctx.new_page()
    page.goto(GROW_URL, wait_until="networkidle", timeout=60000)
    page.wait_for_timeout(5000)
    return pw, browser, ctx, page


def cmd_status():
    if not os.path.exists(STATE_FILE):
        print("\n  未找到登录状态文件，请先选择【3】扫码登录")
        return
    logger.info("查询账号状态...")
    pw, browser, ctx, page = open_page()
    try:
        info = collect_info(page)
        show_info(info)
        ctx.storage_state(path=STATE_FILE)
    finally:
        browser.close()
        pw.stop()


def cmd_checkin():
    if not os.path.exists(STATE_FILE):
        print("\n  未找到登录状态文件，请先选择【3】扫码登录")
        return
    print("\n  开始执行签到...")
    ok = do_checkin()
    print()
    if ok:
        print("  ✅ 签到流程完成")
    else:
        print("  ⚠️ 签到未完成，请查看日志或截图确认")


def cmd_qrlogin():
    print("\n  准备生成登录二维码...")
    try:
        wm = input("  等待分钟数 [默认8]: ").strip()
        wm = int(wm) if wm else 8
    except (ValueError, EOFError):
        wm = 8
    ok = run_qr_login(wm, show_ascii=True)
    print()
    if ok:
        print("  ✅ 扫码登录成功，cookies 已保存")
    else:
        print("  ❌ 扫码登录失败或超时，请重试")


def cmd_logs():
    if not os.path.exists(LOG_FILE):
        print("\n  暂无日志")
        return
    print()
    print(LINE)
    print(f"  最近日志  ({LOG_FILE})")
    print(LINE)
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()
    for line in lines[-25:]:
        print("  " + line.rstrip())
    print(LINE)


def cmd_cookies():
    if not os.path.exists(STATE_FILE):
        print("\n  未找到 state.json，请先扫码登录")
        return
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        st = json.load(f)
    cookies = st.get("cookies", [])
    now = datetime.now()
    print()
    print(LINE)
    print(f"  Cookies 信息  ({STATE_FILE})")
    print(LINE)
    print(f"  数量: {len(cookies)}")
    rows = []
    for c in cookies:
        e = c.get("expires", -1)
        if e and e > 0:
            d = datetime.fromtimestamp(e)
            rows.append(((d - now).days, c["name"], c.get("domain", ""),
                         d.strftime("%Y-%m-%d")))
    rows.sort()
    print("  最早过期的几个:")
    for days, name, dom, ds in rows[:8]:
        print(f"    {name[:24]:<24} {dom[:28]:<28} 剩余{days:>4}天 ({ds})")
    if not rows:
        print("    (全部为会话级 cookie)")
    st_mtime = datetime.fromtimestamp(os.path.getmtime(STATE_FILE))
    print(f"  状态文件更新时间: {st_mtime.strftime('%Y-%m-%d %H:%M:%S')}")
    print(LINE)


def print_menu():
    print()
    print(LINE)
    print("   华为云成长中心 · 签到助手")
    print(LINE)
    print("   1) 查看状态（是否签到 / 积分 / 连续天数）")
    print("   2) 立即签到")
    print("   3) 扫码登录（获取或刷新 cookies）")
    print("   4) 查看最近日志")
    print("   5) 查看 cookies 信息")
    print("   6) 检测积分与代金券兑换状态")
    print("   0) 退出")
    print(LINE)


def main():
    print()
    print(LINE)
    print(f"   数据目录: {DATA_DIR}")
    print(f"   状态文件: {'✅ 存在' if os.path.exists(STATE_FILE) else '❌ 不存在（需扫码登录）'}")
    try:
        while True:
            print_menu()
            try:
                c = input("   请选择 [0-6]: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n  已退出")
                break
            if c == "1":
                cmd_status()
            elif c == "2":
                cmd_checkin()
            elif c == "3":
                cmd_qrlogin()
            elif c == "4":
                cmd_logs()
            elif c == "5":
                cmd_cookies()
            elif c == "6":
                cmd_detect()
            elif c == "0":
                print("  再见")
                break
            else:
                print("  无效选项，请重新输入")
    except KeyboardInterrupt:
        print("\n  已退出")




def cmd_detect():
    if not os.path.exists(STATE_FILE):
        print("\n  未找到登录状态文件，请先选择【3】扫码登录")
        return
    print("\n  开始检测积分与代金券兑换状态...")
    ok = do_detect()
    print()
    if ok:
        print("  ✅ 检测完成，详情见上方日志 / data/detect.json")
    else:
        print("  ⚠️ 检测未完成，请查看日志")

if __name__ == "__main__":
    main()
