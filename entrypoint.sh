#!/bin/bash
# 容器入口: 根据第一个参数分发子命令
#   cli      交互式菜单（需 -it）
#   checkin  执行一次签到
#   detect   检测积分与代金券可兑换状态
#   status   查看登录状态与日志
#   probe    探测页面结构（调试）
#   qrlogin  扫码登录（可接等待分钟数）
#   shell    进入容器 shell

set -e
mkdir -p /app/data/screenshots

CMD="${1:-cli}"

case "$CMD" in
    cli)
        exec python3 /app/cli.py
        ;;
    checkin)
        exec python3 /app/checkin.py --checkin
        ;;
    detect)
        exec python3 /app/checkin.py --detect
        ;;
    status)
        exec python3 /app/checkin.py --status
        ;;
    probe)
        exec python3 /app/checkin.py --probe
        ;;
    qrlogin)
        exec python3 /app/qr_login.py "${2:-8}"
        ;;
    shell)
        exec /bin/bash
        ;;
    *)
        echo "用法: $0 {cli|checkin|detect|status|probe|qrlogin [分钟]|shell}"
        echo "  cli      交互式菜单（docker run 需加 -it）"
        echo "  checkin  执行一次每日签到"
        echo "  detect   检测积分与代金券可兑换状态"
        echo "  status   查看登录状态与最近日志"
        echo "  probe    探测页面结构"
        echo "  qrlogin  扫码登录，默认等待 8 分钟"
        echo "  shell    进入容器 shell"
        exit 1
        ;;
esac
