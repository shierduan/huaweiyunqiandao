#!/usr/bin/env bash
## 华为云签到 · 一键交互部署（在青龙所在宿主机执行）
## 用法：bash deploy.sh
## 作用：检查环境 → 准备镜像 → 交互式对接青龙（上传脚本/写环境变量/建任务）
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
IMAGE="huawei-checkin:latest"
GHCR="ghcr.io/shierduan/huaweiyunqiandao:latest"

say()  { printf '\033[1;36m%s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m✓ %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m! %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m✗ %s\033[0m\n' "$*"; exit 1; }

say "=============================================="
say " 华为云成长中心签到 · 一键交互部署"
say "=============================================="

command -v docker  >/dev/null 2>&1 || die "未找到 docker，请先安装"
command -v python3 >/dev/null 2>&1 || die "未找到 python3，请先安装"

QL_URL="${QL_URL:-}"
QL_USER="${QL_USER:-}"
QL_PASS="${QL_PASS:-}"
HW_USER="${HW_USERNAME:-}"
HW_PASS="${HW_PASSWORD:-}"

if [ -z "$QL_URL" ]; then
  read -rp "青龙地址 [http://127.0.0.1:5700]: " QL_URL
  QL_URL="${QL_URL:-http://127.0.0.1:5700}"
fi
if [ -z "$QL_USER" ]; then
  read -rp "青龙用户名 [admin]: " QL_USER
  QL_USER="${QL_USER:-admin}"
fi
if [ -z "$QL_PASS" ]; then
  read -rsp "青龙密码: " QL_PASS; echo
fi
if [ -z "$HW_USER" ]; then
  if [ -f "${REPO_DIR}/data/config.json" ]; then
    read -rp "华为云账号（回车复用 data/config.json）: " HW_USER
  else
    read -rp "华为云账号: " HW_USER
  fi
fi
if [ -z "$HW_PASS" ]; then
  if [ -n "${HW_USER:-}" ]; then
    read -rsp "华为云密码（回车复用 data/config.json）: " HW_PASS; echo
  else
    read -rsp "华为云密码: " HW_PASS; echo
  fi
fi

[ -n "$QL_PASS" ] || die "青龙密码不能为空"

say ""
say "[1/3] 检查镜像 ${IMAGE}"
if docker image inspect "$IMAGE" >/dev/null 2>&1; then
  ok "本地已有镜像"
else
  warn "本地无镜像，尝试从 ghcr.io 拉取"
  if docker pull "$GHCR"; then
    docker tag "$GHCR" "$IMAGE"
    ok "已拉取并标记为 ${IMAGE}"
  else
    warn "拉取失败（外网受限或包未公开）"
    read -rp "是否现在本地构建？[y/N]: " ans
    if [ "${ans:-N}" = "y" ] || [ "${ans:-N}" = "Y" ]; then
      ( cd "$REPO_DIR" && docker build -t "$IMAGE" . ) || die "镜像构建失败"
      ok "镜像构建完成"
    else
      die "没有可用镜像，后续任务无法执行"
    fi
  fi
fi

say ""
say "[2/3] 对接青龙面板"
QL_PASSWORD="$QL_PASS" \
HW_USERNAME="${HW_USER:-}" \
HW_PASSWORD="${HW_PASS:-}" \
python3 "${REPO_DIR}/tools/attach_qinglong.py" \
  --url "$QL_URL" --user "$QL_USER" \
  --scripts-dir "${REPO_DIR}/qinglong" \
  || die "青龙对接失败，请检查地址/账号/密码"

say ""
say "[3/3] 完成"
ok "定时任务已就绪：华为云签到（每天 08:00）、华为云积分检测（每天 16:00）"
say ""
say "后续操作："
say "  1. 青龙面板 → 定时任务 → 运行「华为云签到」做首次联调"
say "  2. 青龙面板 → 通知设置 → 添加渠道（成功/失败/登录态异常才会推送）"
say "  3. 若提示缺少登录态，新建手动任务：bash /ql/data/scripts/huawei_qrlogin.sh"
say "  4. 需要重建镜像时：新建手动任务 bash /ql/data/scripts/huawei_init.sh"