#!/usr/bin/env bash
# 华为云成长中心自动签到 —— 首次部署一键脚本
# 用法:  bash setup.sh
# 前置:  已安装 Docker 与 Docker Compose(v2)，且当前用户可执行 docker
set -euo pipefail
cd "$(dirname "$0")"

echo "==> [1/4] 准备 data 目录与配置"
mkdir -p data
chmod +x hw.sh entrypoint.sh 2>/dev/null || true

if [ ! -f data/config.json ]; then
  if [ -n "${HW_USERNAME:-}" ] && [ -n "${HW_PASSWORD:-}" ]; then
    printf '{\n  "username": "%s",\n  "password": "%s"\n}\n' "$HW_USERNAME" "$HW_PASSWORD" > data/config.json
    echo "    已从环境变量 HW_USERNAME / HW_PASSWORD 写入 data/config.json"
  else
    cp config.example.json data/config.json
    echo "    ⚠ 已生成示例 data/config.json，请编辑填入真实账号密码"
  fi
  chmod 600 data/config.json
else
  echo "    ℹ data/config.json 已存在，跳过"
fi

echo "==> [2/4] 构建 Docker 镜像（约 1-2 分钟，基础镜像已内置浏览器）"
bash ./hw.sh build

echo "==> [3/4] 安装定时任务（每天 08:00 / 08:20）"
INSTALL_DIR="$(pwd)"
CRON_CMD="cd $INSTALL_DIR && ./hw.sh checkin >> data/cron.log 2>&1"
if crontab -l 2>/dev/null | grep -Fq "hw.sh checkin"; then
  echo "    已存在 hw.sh checkin 定时任务，跳过"
else
  ( crontab -l 2>/dev/null; echo "0 8 * * * $CRON_CMD"; echo "20 8 * * * $CRON_CMD" ) | crontab -
  echo "    已添加两条 cron 记录（日志写入 data/cron.log）"
fi

echo "==> [4/4] 完成"
echo
echo "下一步（首次必须人工介入一次，完成『可信设备』绑定）："
echo "  1. 确认 data/config.json 账号密码正确（权限已设为 600）"
echo "  2. 运行:  ./hw.sh checkin"
echo "  3. 若弹出短信验证码: 把短信里的 6 位码写入 data/otp.txt，进程 2 秒内自动接上"
echo "  4. 首次成功后，该服务器即被华为记为『可信设备』，之后每天定时任务自动登录免验证码"
echo "  5. 查看状态: ./hw.sh status    查看日志: tail -f data/checkin.log"
echo
echo "迁移文档见 README.md。"
