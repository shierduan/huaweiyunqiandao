#!/usr/bin/env bash
## 华为云扫码登录（青龙任务）：在任务日志里输出二维码，手机扫码完成登录
## 青龙任务命令：bash /ql/data/scripts/huawei_qrlogin.sh
## 可选环境变量 WAIT_MIN：等待扫码的分钟数，默认 8

SRC_DIR="/ql/data/huawei_checkin"
DATA_DIR="${SRC_DIR}/data"
DOCKER_BIN="/ql/data/bin/docker"
[ -x "$DOCKER_BIN" ] || DOCKER_BIN="$(command -v docker)"
IMAGE="huawei-checkin:latest"

## docker run -v 的源路径由宿主机 daemon 解析，必须把容器内 /ql/data 翻译成宿主机真实路径
host_data_dir() {
  local src
  src="$("$DOCKER_BIN" inspect \
        --format '{{range .Mounts}}{{if eq .Destination "/ql/data"}}{{.Source}}{{end}}{{end}}' \
        "$(hostname)" 2>/dev/null)"
  [ -n "$src" ] && printf '%s/huawei_checkin/data' "$src"
}

ts() { date '+%F %T'; }

if [ -z "$DOCKER_BIN" ]; then
  echo "[$(ts)] 未找到 docker CLI"
  exit 1
fi

HOST_DATA="$(host_data_dir)"
if [ -z "$HOST_DATA" ]; then
  echo "[$(ts)] 无法解析宿主机数据目录：docker.sock 不可用，或本脚本不在青龙容器内运行"
  exit 1
fi

echo "[$(ts)] 开始扫码登录（二维码见下方，等待 ${WAIT_MIN:-8} 分钟）..."
"$DOCKER_BIN" run --rm -e HW_USERNAME -e HW_PASSWORD \
  -v "${HOST_DATA}:/app/data" "$IMAGE" qrlogin "${WAIT_MIN:-8}" 2>&1
RC=$?
if [ "$RC" -eq 0 ]; then
  echo "[$(ts)] 扫码登录完成，登录态已保存到 ${DATA_DIR}/state.json"
else
  echo "[$(ts)] 扫码登录失败或超时（退出码 ${RC}）"
fi
exit "$RC"