#!/usr/bin/env bash
## 华为云签到 · 青龙一键初始化
## 用途：检查凭据与登录态 → 准备数据目录 → 按需构建/更新镜像
## 青龙任务命令：bash /ql/data/scripts/huawei_init.sh
## 强制重建镜像：在青龙环境变量里设 FORCE_REBUILD=1 后再运行本任务

SRC_DIR="/ql/data/huawei_checkin"
DATA_DIR="${SRC_DIR}/data"
DOCKER_BIN="/ql/data/bin/docker"
[ -x "$DOCKER_BIN" ] || DOCKER_BIN="$(command -v docker)"
IMAGE="huawei-checkin:latest"

ts() { date '+%F %T'; }
fail() { echo "[$(ts)] 初始化失败：$1"; exit 1; }

echo "[$(ts)] 华为云签到 · 青龙初始化开始"

[ -n "$DOCKER_BIN" ] || fail "未找到 docker CLI，请先在容器内 apk add --no-cache docker-cli 并 cp /usr/bin/docker /ql/data/bin/docker"
[ -d "$SRC_DIR" ] || fail "缺少源码目录 ${SRC_DIR}（应包含 Dockerfile / checkin.py / qinglong）"
[ -f "${SRC_DIR}/Dockerfile" ] || fail "${SRC_DIR} 下没有 Dockerfile"

mkdir -p "${DATA_DIR}/screenshots" || fail "无法创建 ${DATA_DIR}"

if [ -n "$HW_USERNAME" ] && [ -n "$HW_PASSWORD" ]; then
  echo "[$(ts)] 账号密码来自青龙环境变量（HW_USERNAME 长度 ${#HW_USERNAME}，HW_PASSWORD 长度 ${#HW_PASSWORD}）"
elif [ -f "${DATA_DIR}/config.json" ]; then
  echo "[$(ts)] 未设置 HW_USERNAME / HW_PASSWORD，回退使用 ${DATA_DIR}/config.json"
else
  echo "[$(ts)] 警告：既没有 HW_USERNAME / HW_PASSWORD，也没有 config.json，登录态失效后将无法自动重登"
fi

if [ -f "${DATA_DIR}/state.json" ]; then
  echo "[$(ts)] 已有登录态 state.json，无需重新扫码"
else
  echo "[$(ts)] 警告：缺少 state.json，首次使用请运行「华为云扫码登录」任务完成扫码"
fi

NEED_BUILD=0
if [ -z "$("$DOCKER_BIN" images -q "$IMAGE" 2>/dev/null)" ]; then
  NEED_BUILD=1
elif [ "${FORCE_REBUILD:-0}" = "1" ]; then
  NEED_BUILD=1
fi

if [ "$NEED_BUILD" = "1" ]; then
  echo "[$(ts)] 开始构建镜像 ${IMAGE}（首次较慢，之后走构建缓存）..."
  cd "$SRC_DIR" || fail "无法进入 ${SRC_DIR}"
  "$DOCKER_BIN" build -t "$IMAGE" . || fail "镜像构建失败"
else
  echo "[$(ts)] 镜像已存在，跳过构建（设 FORCE_REBUILD=1 可强制重建）"
fi

echo "[$(ts)] 当前镜像：$("$DOCKER_BIN" images --format '{{.Repository}}:{{.Tag}} {{.CreatedSince}} {{.Size}}' "$IMAGE" 2>/dev/null | head -1)"
echo "[$(ts)] 初始化完成，可运行「华为云签到」任务做首次联调"
exit 0