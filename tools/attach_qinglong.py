#!/usr/bin/env python3
"""华为云签到 · 青龙一键对接（在青龙所在宿主机执行）

作用：登录青龙 API → 上传 4 个调度脚本 → 写入华为云凭据环境变量 → 创建/更新定时任务。
之后全部由青龙面板管理，宿主机无需再手工操作。

用法（全部参数可省略，省略则交互式提示）：

    python3 attach_qinglong.py \
        --url http://127.0.0.1:5700 --user shier --password '面板密码' \
        --hw-user 'GT-xxx' --hw-pass '华为云密码'

简化：青龙密码可用环境变量 QL_PASSWORD，华为云凭据可用环境变量 HW_USERNAME/HW_PASSWORD，
或 --config 指定一个 {"username":..., "password":...} 的 JSON 文件。

幂等：脚本、环境变量、任务都是「存在即更新」，重复执行安全。
"""

import argparse
import getpass
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

SCRIPTS = [
    "huawei_checkin.sh",
    "huawei_detect.sh",
    "huawei_init.sh",
    "huawei_qrlogin.sh",
]

# 只自动创建会按计划运行的两个任务；
# 初始化与扫码登录属于一次性人工操作，在面板按需手动创建（见下方提示）
TASKS = [
    ("华为云签到", "bash /ql/data/scripts/huawei_checkin.sh", "0 8 * * *"),
    ("华为云积分检测", "bash /ql/data/scripts/huawei_detect.sh", "0 16 * * *"),
]


class QL:
    def __init__(self, base, token=None):
        self.base = base.rstrip("/")
        self.token = token

    def call(self, path, payload=None, method=None):
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(
            self.base + path, data=data,
            method=method or ("POST" if data is not None else "GET"),
        )
        req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("Authorization", "Bearer " + self.token)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode() or "{}")
        except urllib.error.HTTPError as ex:
            body = ex.read().decode()
            raise RuntimeError(f"{method or 'GET'} {path} -> HTTP {ex.code}: {body[:200]}")
        except urllib.error.URLError as ex:
            raise RuntimeError(f"无法连接青龙 {self.base}：{ex.reason}")

    def login(self, username, password):
        r = self.call("/api/user/login", {"username": username, "password": password})
        token = (r.get("data") or {}).get("token")
        if not token:
            raise RuntimeError(f"登录失败：{r}")
        self.token = token
        return token

    def envs(self):
        return self.call("/api/envs?page=1&size=100").get("data") or []

    def upsert_env(self, name, value, remarks):
        exist = [e for e in self.envs() if e.get("name") == name]
        if exist:
            e = exist[0]
            self.call("/api/envs", {"id": e["id"], "name": name, "value": value, "remarks": remarks}, "PUT")
            return "更新"
        self.call("/api/envs", [{"name": name, "value": value, "remarks": remarks}])
        return "创建"

    def scripts(self):
        return self.call("/api/scripts").get("data") or []

    def upload_script(self, filename, content):
        self.call("/api/scripts", {"filename": filename, "path": "", "content": content})
        return "更新" if any(s.get("title") == filename for s in self.scripts()) else "创建"

    def crons(self):
        return (self.call("/api/crons?page=1&size=100").get("data") or {}).get("data") or []

    def upsert_cron(self, name, command, schedule):
        exist = [c for c in self.crons() if c.get("name") == name]
        body = {"name": name, "command": command, "schedule": schedule}
        if exist:
            body["id"] = exist[0]["id"]
            self.call("/api/crons", body, "PUT")
            return "更新"
        self.call("/api/crons", body)
        return "创建"


def ask(prompt, default=None, secret=False):
    tip = f"{prompt}" + (f" [{default}]" if default else "")
    if secret:
        val = getpass.getpass(tip + "：")
    else:
        val = input(tip + "：").strip()
    return val or default or ""


def main():
    ap = argparse.ArgumentParser(description="华为云签到 ↔ 青龙面板一键对接")
    ap.add_argument("--url", default="http://127.0.0.1:5700", help="青龙地址，默认 http://127.0.0.1:5700")
    ap.add_argument("--user", default="admin", help="青龙登录用户名")
    ap.add_argument("--password", default=os.environ.get("QL_PASSWORD"), help="青龙登录密码，或环境变量 QL_PASSWORD")
    ap.add_argument("--hw-user", default=os.environ.get("HW_USERNAME"), help="华为云账号，或环境变量 HW_USERNAME")
    ap.add_argument("--hw-pass", default=os.environ.get("HW_PASSWORD"), help="华为云密码，或环境变量 HW_PASSWORD")
    ap.add_argument("--config", default=str(REPO_ROOT / "data" / "config.json"), help="含 username/password 的 JSON")
    ap.add_argument("--scripts-dir", default=str(REPO_ROOT / "qinglong"), help="调度脚本所在目录")
    args = ap.parse_args()

    url = args.url or ask("青龙地址", "http://127.0.0.1:5700")
    user = args.user or ask("青龙用户名", "admin")
    password = args.password or ask("青龙密码", secret=True)

    hw_user, hw_pass = args.hw_user, args.hw_pass
    if not (hw_user and hw_pass):
        cfg = Path(args.config)
        if cfg.is_file():
            try:
                d = json.loads(cfg.read_text(encoding="utf-8"))
                hw_user = hw_user or d.get("username")
                hw_pass = hw_pass or d.get("password")
                if hw_user and hw_pass:
                    print(f"已从 {cfg} 读取华为云凭据（账号长度 {len(hw_user)}）")
            except Exception as e:
                print(f"读取 {cfg} 失败：{e}")
    if not hw_user:
        hw_user = ask("华为云账号")
    if not hw_pass:
        hw_pass = ask("华为云密码", secret=True)
    if not (hw_user and hw_pass):
        print("缺少华为云账号或密码，退出")
        return 1

    ql = QL(url)
    print(f"连接青龙 {url} ...")
    try:
        ql.login(user, password)
        print("✓ 登录成功")
    except Exception as e:
        print(f"✗ {e}")
        return 1

    sdir = Path(args.scripts_dir)
    if not sdir.is_dir():
        print(f"✗ 脚本目录不存在：{sdir}")
        return 1
    for name in SCRIPTS:
        f = sdir / name
        if not f.is_file():
            print(f"✗ 缺少脚本 {f}")
            return 1
    for name in SCRIPTS:
        action = ql.upload_script(name, (sdir / name).read_text(encoding="utf-8"))
        print(f"✓ 脚本 {name} 已{action}")

    for name, val, remark in (("HW_USERNAME", hw_user, "华为云账号"),
                              ("HW_PASSWORD", hw_pass, "华为云密码")):
        action = ql.upsert_env(name, val, remark)
        print(f"✓ 环境变量 {name} 已{action}")

    for name, command, schedule in TASKS:
        action = ql.upsert_cron(name, command, schedule)
        print(f"✓ 任务 {name}（{schedule}） 已{action}")

    print("")
    print("对接完成。后续全部在青龙面板操作：")
    print("  1. 定时任务 → 运行「华为云签到」做首次联调")
    print("  2. 通知设置 → 添加渠道后，签到成功/失败/登录态异常才会真正推送")
    print("")
    print("以下两个手动任务请按需在面板新建（不属于定时调度）：")
    print("  · 华为云初始化   → bash /ql/data/scripts/huawei_init.sh")
    print("  · 华为云扫码登录 → bash /ql/data/scripts/huawei_qrlogin.sh")
    return 0


if __name__ == "__main__":
    sys.exit(main())