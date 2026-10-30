#!/bin/bash
# 宿主机一键入口（Docker 模式）
#   ./hw.sh build            构建镜像
#   ./hw.sh cli              交互式菜单
#   ./hw.sh checkin          执行一次签到
#   ./hw.sh detect           检测积分与代金券可兑换状态
#   ./hw.sh status           查看状态
#   ./hw.sh qrlogin [分钟]    扫码登录
#   ./hw.sh shell            进入容器 shell

cd "$(dirname "$0")" || exit 1
CMD="${1:-cli}"

case "$CMD" in
    build)
        exec docker compose build
        ;;
    cli)
        exec docker compose run --rm -it hw-checkin cli
        ;;
    checkin)
        exec docker compose run --rm hw-checkin checkin
        ;;
    detect)
        exec docker compose run --rm hw-checkin detect
        ;;
    status)
        exec docker compose run --rm hw-checkin status
        ;;
    qrlogin)
        exec docker compose run --rm -it hw-checkin qrlogin "${2:-8}"
        ;;
    shell)
        exec docker compose run --rm -it hw-checkin shell
        ;;
    *)
        echo "用法: $0 {build|cli|checkin|detect|status|qrlogin [分钟]|shell}"
        echo "  build    构建镜像（首次或改代码后执行）"
        echo "  cli      交互式菜单（查看积分/签到/扫码登录）"
        echo "  checkin  执行一次每日签到（适合定时任务调用）"
        echo "  detect   检测当前积分与各类代金券是否可兑换"
        echo "  status   查看登录状态与最近日志"
        echo "  qrlogin  扫码登录，默认等待 8 分钟"
        echo "  shell    进入容器 shell"
        exit 1
        ;;
esac
