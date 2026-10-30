#!/usr/bin/env bash
## 华为云积分与代金券可兑换状态检测（青龙调度，只读不兑换）+ 失败告警
## 告警走青龙面板「通知设置」已配置的渠道，经 /ql/data/scripts/sendNotify.js 发送
## 退出码：0=检测完成  1=检测失败

DOCKER_BIN="/ql/data/bin/docker"
[ -x "$DOCKER_BIN" ] || DOCKER_BIN="$(command -v docker)"
NOTIFY_JS="/ql/data/scripts/sendNotify.js"
QL_DB="/ql/data/db/database.sqlite"
DATA_DIR="/ql/data/huawei_checkin/data"
DETECT_JSON="${DATA_DIR}/detect.json"
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
  notify "华为云检测异常" "$(ts) 青龙容器内找不到 docker CLI，任务未执行"
  exit 1
fi

HOST_DATA="$(host_data_dir)"
if [ -z "$HOST_DATA" ]; then
  echo "[$(ts)] 无法解析宿主机数据目录：docker.sock 不可用，或本脚本不在青龙容器内运行"
  exit 1
fi

echo "[$(ts)] 开始检测积分与代金券（镜像 ${IMAGE}）..."
OUT="$("$DOCKER_BIN" run --rm -e HW_USERNAME -e HW_PASSWORD \
  -v "${HOST_DATA}:/app/data" "$IMAGE" detect 2>&1)"
RC=$?
printf '%s\n' "$OUT"

if [ "$RC" -ne 0 ]; then
  echo "[$(ts)] 结果=失败 rc=${RC}"
  notify "华为云积分检测失败" "$(ts) 退出码 ${RC}。输出尾部：
$(printf '%s\n' "$OUT" | tail -8)"
  exit 1
fi

echo "[$(ts)] 结果=成功 rc=0，报告见 ${DETECT_JSON}"
if [ -f "$DETECT_JSON" ]; then
  SUMMARY="$(python3 - "$DETECT_JSON" <<'PY'
import json, sys
try:
    d = json.load(open(sys.argv[1], encoding='utf-8'))
except Exception as e:
    print("detect.json 解析失败：%s" % e)
    sys.exit(0)
pts = d.get('points')
rows = d.get('vouchers') or []
ok = [v for v in rows if v.get('redeemable')]
print("当前积分：%s" % (pts if pts is not None else '未知'))
print("可兑换：%s" % ("、".join(v.get('name', '?') for v in ok) if ok else "无"))
PY
)"
  echo "${SUMMARY}"
fi

exit 0