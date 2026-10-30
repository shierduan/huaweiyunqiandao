#!/usr/bin/env bash
## 华为云成长中心自动签到（青龙调度）+ 成功/失败/登录态异常告警
## 告警走青龙面板「通知设置」已配置的渠道，经 /ql/data/scripts/sendNotify.js 发送
## 退出码：0=签到成功（含今日已签到）  2=登录态异常需人工  1=其他失败

DOCKER_BIN="/ql/data/bin/docker"
[ -x "$DOCKER_BIN" ] || DOCKER_BIN="$(command -v docker)"
NOTIFY_JS="/ql/data/scripts/sendNotify.js"
QL_DB="/ql/data/db/database.sqlite"
DATA_DIR="/ql/data/huawei_checkin/data"
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

## 青龙「通知设置」里是否至少配置了一个渠道（info 非空）
channel_configured() {
  [ -f "$QL_DB" ] && command -v python3 >/dev/null 2>&1 || { echo -1; return; }
  python3 - "$QL_DB" <<'PY'
import sqlite3, sys
try:
    conn = sqlite3.connect('file:%s?mode=ro' % sys.argv[1], uri=True)
    row = conn.execute("select info from Auths where type='notification'").fetchone()
    val = row[0] if row else None
    print(1 if (val and val.strip() not in ('', 'null', '{}')) else 0)
except Exception:
    print(-1)
PY
}

notify() {
  local title="$1" body="$2" rc
  if [ "$(channel_configured)" = "0" ]; then
    echo "[$(ts)] 告警未发出：青龙「通知设置」尚未配置任何渠道（本次已记录日志，配好渠道后自动生效）"
    return 2
  fi
  if [ ! -f "$NOTIFY_JS" ]; then
    echo "[$(ts)] 告警未推送：缺少 $NOTIFY_JS"
    return 1
  fi
  if ! command -v node >/dev/null 2>&1; then
    echo "[$(ts)] 告警未推送：容器内无 node"
    return 1
  fi
  timeout 45 node -e '
    const m = require(process.argv[1]);
    const f = m.sendNotify || m;
    Promise.resolve(f(process.argv[2], process.argv[3]))
      .then(() => process.exit(0))
      .catch(() => process.exit(1));
  ' "$NOTIFY_JS" "$title" "$body" >/dev/null 2>&1
  rc=$?
  if [ "$rc" -eq 0 ]; then
    echo "[$(ts)] 告警已推送：$title"
  else
    echo "[$(ts)] 告警推送失败(rc=$rc)：渠道已配置但请求失败，检查容器网络或渠道配置"
  fi
  return "$rc"
}

if [ -z "$DOCKER_BIN" ]; then
  echo "[$(ts)] 未找到 docker CLI（请先执行容器内: apk add --no-cache docker-cli && cp /usr/bin/docker /ql/data/bin/docker）"
  notify "华为云签到异常" "$(ts) 青龙容器内找不到 docker CLI，任务未执行"
  exit 1
fi

HOST_DATA="$(host_data_dir)"
if [ -z "$HOST_DATA" ]; then
  echo "[$(ts)] 无法解析宿主机数据目录：docker.sock 不可用，或本脚本不在青龙容器内运行"
  exit 1
fi

echo "[$(ts)] 开始华为云签到（镜像 ${IMAGE}）..."
OUT="$("$DOCKER_BIN" run --rm -e HW_USERNAME -e HW_PASSWORD \
  -v "${HOST_DATA}:/app/data" "$IMAGE" checkin 2>&1)"
RC=$?
printf '%s\n' "$OUT"

if [ "$RC" -eq 0 ] && printf '%s' "$OUT" | grep -qE "签到成功|已签到"; then
  SUMMARY="$(printf '%s\n' "$OUT" | grep -E "签到成功|已签到|连续天数" | tail -1)"
  echo "[$(ts)] 结果=成功 rc=0"
  notify "华为云签到成功" "$(ts) ${SUMMARY:-今日签到完成}"
  exit 0
fi

if printf '%s' "$OUT" | grep -qE "验证码|otp\.txt|登录未成功|自动登录失败|登录态已失效|未登录"; then
  echo "[$(ts)] 结果=需人工 rc=${RC}"
  notify "华为云登录态异常（需人工介入）" "$(ts) 签到退出码 ${RC}，疑似触发短信验证码或登录态失效。
处理：echo -n \"6位码\" > ${DATA_DIR}/otp.txt，或在宿主机执行 cd /root/huawei_checkin && ./hw.sh qrlogin 扫码重登。"
  exit 2
fi

echo "[$(ts)] 结果=失败 rc=${RC}"
notify "华为云签到失败" "$(ts) 退出码 ${RC}。输出尾部：
$(printf '%s\n' "$OUT" | tail -8)"
exit 1