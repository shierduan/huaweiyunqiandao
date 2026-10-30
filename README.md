# 华为云成长中心自动签到 · 部署与迁移指南

Docker 化的华为云开发者成长中心每日自动签到工具。**登录态（cookies）不打包进镜像**，由宿主机 `data/` 目录挂载注入。本仓库即「部署包」，可直接拉取到任意 Linux 服务器完成无人值守部署。

本指南面向**把这套工具迁移 / 部署到新服务器**的场景。

---

## 1. 部署包内容（本仓库）

| 文件 | 作用 |
|---|---|
| `Dockerfile` | 基于官方 Playwright 镜像 `mcr.microsoft.com/playwright/python`，补装 `playwright` / `qrcode` / `opencv`，版本与内置浏览器对齐 |
| `docker-compose.yml` | 定义 `hw-checkin` 服务，把宿主机 `./data` 挂载到容器 `/app/data`，登录态与日志全落宿主机 |
| `.dockerignore` | 构建镜像时排除 `data/`、凭据、本地脚本 |
| `entrypoint.sh` | 容器入口，按子命令分发（`cli`/`checkin`/`status`/`probe`/`qrlogin`/`shell`） |
| `hw.sh` | **宿主机一键入口**：`build` / `cli` / `checkin` / `status` / `qrlogin` / `shell` |
| `checkin.py` | 签到主逻辑 + 自动登录兜底（读 `config.json` 账号密码）+ 短信验证码(OTP)自动处理 |
| `qr_login.py` | 扫码登录（终端渲染二维码） |
| `cli.py` | 交互式菜单（查看积分 / 签到 / 扫码 / 日志） |
| `config.example.json` | 账号配置模板 |
| `setup.sh` | **首次部署一键脚本**（建目录、写配置、构建镜像、装定时任务） |
| `README.md` | 本指南 |

> ⚠️ `data/` 目录**不在仓库内**（含登录态、密码、日志），由 `.gitignore` 排除。新服务器需自行生成。

---

## 2. 环境要求

- Linux 服务器，可访问外网（华为云 + pip 源）
- 已安装 **Docker** 与 **Docker Compose v2**（`docker compose` 命令可用）
- 系统 `crontab` 可用（如用 1Panel 计划任务亦可，见第 7 节）
- 约 **4 GB** 磁盘（镜像含浏览器）
- **不需要**宿主机安装 Python（运行全在容器内）

---

## 3. 拉取到新服务器（三种方式）

### 方式 A：git clone（推荐，便于后续更新）
```bash
git clone root@<你的服务器IP>:/root/huawei_checkin /opt/huawei-checkin
cd /opt/huawei-checkin
```

### 方式 B：tarball（无 git / 跨网络环境，最稳妥）
```bash
# 在目标服务器执行：
scp root@<你的服务器IP>:/opt/huawei-checkin-latest.tar.gz .
mkdir -p /opt/huawei-checkin && tar xzf huawei-checkin-latest.tar.gz -C /opt/huawei-checkin
cd /opt/huawei-checkin
```

### 方式 C：rsync 整目录（排除 data）
```bash
rsync -avz --exclude=data root@<你的服务器IP>:/root/huawei_checkin/ /opt/huawei-checkin/
cd /opt/huawei-checkin
```

> 拉取后请先 `chmod +x hw.sh entrypoint.sh setup.sh`（Windows 上生成的包可能丢失执行位）。

---

## 4. 一键部署

```bash
bash setup.sh
```

`setup.sh` 会依次完成：
1. 创建 `data/` 目录，生成 `data/config.json`（权限 `600`）；
2. 若设置了环境变量 `HW_USERNAME` / `HW_PASSWORD` 则直接写入，否则写入示例模板待你编辑；
3. 构建 Docker 镜像（`./hw.sh build`）；
4. 安装定时任务（每天 `08:00` 与 `08:20` 各一次，日志写入 `data/cron.log`）。

---

## 5. 配置账号

账号密码读取优先级：**环境变量 `HW_USERNAME` / `HW_PASSWORD` > `data/config.json`**。

**青龙托管（推荐）**：在青龙面板「环境变量」添加 `HW_USERNAME` / `HW_PASSWORD`。
调度脚本用 `docker run -e HW_USERNAME -e HW_PASSWORD`（只写变量名不写值）继承，
密码不会出现在宿主机 `ps` 中，`data/` 下也不留明文。

**本地 / 直连 Docker 模式**：编辑 `data/config.json`（权限 `600`，不进镜像、不写日志）：

```json
{
  "username": "你的华为云账号",
  "password": "你的华为云密码"
}
```

或部署时通过环境变量注入（setup.sh 会自动写入）：
```bash
HW_USERNAME=GT-xxx HW_PASSWORD='xxx' bash setup.sh
```

---

## 6. 首次运行与「可信设备」绑定（关键！）

华为云对**数据中心 IP** 的密码登录会强制**短信验证码**（发往账号绑定的手机）。这是平台风控，无法自动接收短信。因此首次运行需要人工介入**一次**：

1. 运行 `./hw.sh checkin`；
2. 脚本检测到短信验证后，会**自动点击「获取验证码」**，并轮询 `data/otp.txt`；
3. 把手机短信里的 **6 位码**写入 `data/otp.txt`（纯数字即可），进程 **2 秒内**读取、自动填入并「继续登录」；
4. 登录成功后，华为会**把该服务器记为「可信设备」**（设备指纹 cookie 有效期约 1 年）。

✅ **关键结论（已实测）**：完成这一次 OTP 绑定后，之后每天 cron 用环境变量或 `config.json` 里的密码重登**都不再需要短信验证码**，真正的无人值守成立。

> 若你不想配置密码，也可 `./hw.sh qrlogin` 用华为云 APP 扫码（终端直接渲染二维码）。但扫码登录态仅约 30 分钟有效，第二天定时任务仍会失败，**不推荐用于无人值守**。

---

## 7. 定时任务

`setup.sh` 已自动在系统 crontab 写入：
```cron
0  8 * * * cd /opt/huawei-checkin && ./hw.sh checkin >> data/cron.log 2>&1
20 8 * * * cd /opt/huawei-checkin && ./hw.sh checkin >> data/cron.log 2>&1
```
> 路径以实际部署目录为准（setup.sh 会自动替换为真实绝对路径）。

**方式 B：1Panel 计划任务**
- 任务类型：`Shell 脚本`
- 执行周期：每天 `08:00`（可再加 `08:20`）
- 脚本：`cd /opt/huawei-checkin && ./hw.sh checkin`

> cron 环境无 TTY，`checkin` 子命令不需要交互，可正常执行；其退出码在「今日已签到 / 无需重复」时会为 1，属正常，不影响定时效果。

---

## 8. 日常运维

| 操作 | 命令 |
|---|---|
| 查看登录状态 / 最近日志 | `./hw.sh status` |
| 实时跟踪日志 | `tail -f data/checkin.log` |
| 手动执行一次签到 | `./hw.sh checkin` |
| 重新扫码登录 | `./hw.sh qrlogin` |
| 进入容器排错 | `./hw.sh shell` |
| **检测积分与代金券可兑换状态** | `./hw.sh detect` |
| 探测页面结构（签到按钮变更时） | `docker compose run --rm hw-checkin probe` |

**⚠️ 务必保留 `data/state.json`**：它含可信设备 cookie（约 1 年有效）。一旦丢失，下次重登会重新触发短信验证码，需要再人工介入一次 OTP 绑定。迁移服务器时见第 11 节。

---

## 8.1 积分与代金券检测（`detect`）

用于**只读**查看当前积分与各类代金券的可兑换情况（不实际兑换、不点击「去兑换」按钮，无任何副作用）：

```bash
./hw.sh detect          # 检测并输出报告，同时写入 data/detect.json
```

输出示例：

```
当前积分: 50
  - 5元代金券:  需50积分,  库存608, 状态=可兑换
  - 10元代金券: 需100积分, 库存571, 状态=积分不足（当前积分 50）
  - 20元代金券: 需200积分, 库存388, 状态=积分不足（当前积分 50）
  ...
可兑换代金券: 5元代金券
```

判定规则（纯只读）：

| 状态 | 含义 |
|---|---|
| `可兑换` | 库存 > 0 且 当前积分 ≥ 该代金券所需积分 |
| `积分不足` | 当前积分 < 该代金券所需积分 |
| `无库存` | 卡片库存为 0 / 已兑完 |

结果同时保存为 `data/detect.json`，含每件代金券的 `name` / `cost` / `stock` / `status` / `redeemable`，便于脚本或定时任务消费。

> 说明：华为对代金券设有「每日兑换上限」（公告称每天 16:00 补货），该上限需在点击兑换弹窗内才可见。本检测不做实际兑换，因此无法预判是否被上限拦截；`可兑换` 仅代表「库存充足 + 积分足够」。

---

## 9. 故障排查

| 现象 | 原因 / 处理 |
|---|---|
| 弹出短信验证码、等不到 | 把 6 位码写入 `data/otp.txt`，进程 2 秒内自动接上 |
| 日志时间戳显示 `2026-68-07` | 旧版 bug；本包已修复（绕开损坏的 `time.strftime`），重建镜像即可 |
| 找不到签到按钮 | 页面结构可能变更，跑 `probe` 探测；或 `./hw.sh shell` 进容器看页面 |
| 构建失败（pip 超时） | 换源：`docker compose build --build-arg PIP_INDEX=https://pypi.org/simple` |
| cron 没触发 | `crontab -l` 确认记录存在；cron 的 PATH 可能无 `docker`，脚本已用绝对路径规避 |
| 提示未登录 | `./hw.sh qrlogin` 重新扫码，或确认 `data/config.json` 账号密码正确 |

---

## 10. 安全说明

- **密码**优先来自青龙「环境变量」`HW_USERNAME` / `HW_PASSWORD`，不落盘；回退文件 `data/config.json` 权限 `600`，不进镜像、不写日志、不进仓库。
- 青龙模式下调度脚本用 `docker run -e HW_USERNAME -e HW_PASSWORD`（不带值）传递，避免密码出现在宿主机 `ps`。
- **登录态** `data/state.json` 含会话 cookie，请勿提交 / 外泄。
- **`data/otp.txt`** 用完即自删。
- 部署包（git 仓库 / tarball）**不含任何 `data/` 内容**，可安全分发。

---

## 11. 迁移 / 复制到另一台服务器

- **全新服务器**：按第 3 → 4 → 5 → 6 节拉取、部署、配置、完成首次 OTP 绑定即可。
- **想直接带走已登录状态**：把源服务器的 `data/state.json` 拷到新服务器 `data/`。注意该 cookie 与服务器 IP / 设备指纹关联，跨服务器可能仍需一次 OTP 绑定；为稳妥，**新服务器仍建议走一次第 6 节的 OTP 绑定**。
- **生成最新离线包**（在源服务器执行，供方式 B 拉取）：
  ```bash
  cd /root/huawei_checkin
  git add -A && git commit -m "update" || true
  git archive --format=tar.gz -o /opt/huawei-checkin-latest.tar.gz HEAD
  ```

---

## 12. 常用命令速查

```bash
./hw.sh build      # 构建镜像（首次或改代码后）
./hw.sh checkin    # 执行一次签到（幂等，适合定时任务）
./hw.sh detect     # 检测积分与代金券可兑换状态
./hw.sh status     # 查看登录态与日志
./hw.sh qrlogin    # 扫码登录
./hw.sh shell      # 进入容器
./hw.sh cli        # 交互式菜单
```

---

## 13. 青龙面板调度（可选，与 crontab 二选一）

本仓库 `qinglong/` 目录提供两个青龙调度脚本，可在青龙面板里可视化管理定时任务、查看日志。

### 13.1 原理

青龙容器内**不安装** Python / Playwright，而是复用宿主机已有的 `huawei-checkin:latest` 镜像：
通过挂载进容器的 `/var/run/docker.sock`，起一个临时容器执行任务，跑完即退（`--rm`）。

### 13.2 部署步骤

```bash
# ① 拷贝脚本到青龙脚本目录（容器内即 /ql/data/scripts）
cp qinglong/huawei_*.sh /opt/1panel/apps/qinglong/qinglong/data/scripts/
chmod +x /opt/1panel/apps/qinglong/qinglong/data/scripts/huawei_*.sh

# ② 在青龙容器内安装 docker-cli 并持久化（Alpine/musl 必须容器内装，
#    直接挂宿主机 glibc 版 docker 会 exec format error）
docker exec -it <青龙容器名> sh -c '
  rm -f /lib/apk/db/lock
  apk add --no-cache docker-cli
  mkdir -p /ql/data/bin
  cp /usr/bin/docker /ql/data/bin/docker
  chmod +x /ql/data/bin/docker'

# ③ 验证
docker exec <青龙容器名> /ql/data/bin/docker ps
```

> `/ql/data/bin` 位于持久化卷，青龙容器重建后 docker-cli 不会丢。

### 13.3 新建定时任务

| 名称 | 命令 | 定时规则 |
|---|---|---|
| 华为云签到 | `bash /ql/data/scripts/huawei_checkin.sh` | `0 8 * * *` |
| 华为云积分检测 | `bash /ql/data/scripts/huawei_detect.sh` | `0 16 * * *` |
| 华为云初始化（手动） | `bash /ql/data/scripts/huawei_init.sh` | 手动运行 |
| 华为云扫码登录（手动） | `bash /ql/data/scripts/huawei_qrlogin.sh` | 手动运行 |

建好后点「运行」做一次手动联调，日志出现「签到命令结束，退出码 0」即链路打通。
日志目录：容器 `/ql/data/log/bash/`。

### 13.4 与宿主机 crontab 去重

两套调度**不要同时开启**，否则一天会重复签到。二选一：

- 用青龙 → 注释掉宿主机 crontab 中的 `hw.sh checkin` 两行；
- 用 crontab → 在青龙面板把这两个任务设为禁用。

### 13.5 已知的登录拦截页面

登录后华为云可能弹出「登录验证 / MFA 设备绑定」提示页。`checkin.py` 已内置处理：
勾选「30 天内不再提示」并点「暂不绑定」跳过，随后自动继续签到。
若出现短信验证码（OTP），按第 5 节把 6 位码写入 `data/otp.txt`。

---

## 14. 失败告警（青龙通知）

`qinglong/huawei_checkin.sh` / `huawei_detect.sh` 已内置结果告警，判定规则与退出码：

| 场景 | 判定依据 | 告警标题 | 退出码 |
|---|---|---|---|
| 签到成功 / 今日已签到 | 输出含「签到成功」或「已签到」 | 华为云签到成功 | 0 |
| 登录态失效 / 短信验证码 | 输出含「验证码」「otp.txt」「登录未成功」「自动登录失败」等 | 华为云登录态异常（需人工介入） | 2 |
| 其他失败 | 退出码非 0 且不命中上述关键词 | 华为云签到失败 | 1 |
| 积分检测失败 | `detect` 退出码非 0 | 华为云积分检测失败 | 1 |

### 14.1 启用通知渠道

青龙面板 → **通知设置** → 添加任一渠道（企业微信机器人 / 钉钉 / 邮件 / Telegram 等）。

脚本每次执行都会先读 `/ql/data/db/database.sqlite` 中 `Auths(type='notification')` 的 `info` 字段：

- 未配置 → 日志输出「告警未发出：青龙「通知设置」尚未配置任何渠道」，**不会把未送达误报成已推送**；
- 已配置 → 调用 `/ql/data/scripts/sendNotify.js` 实际推送。

### 14.2 实现注意点

- `sendNotify.js` 只有 `module.exports = { sendNotify }`，**没有命令行入口**，必须用
  `node -e 'require("/ql/data/scripts/sendNotify.js").sendNotify(标题, 正文)'` 调用。
- 本机访问 `registry-1.docker.io` 存在 DNS 污染（解析到 `162.125.6.1`），外网受限；
  通知渠道优先选国内直连可达的（企业微信机器人 / 钉钉 / SMTP）。
- 旧版脚本 `echo "... 退出码 $?"` 里的 `$(date ...)` 会先把 `$?` 覆盖成 0，
  导致失败永远显示退出码 0；新版改为先保存 `RC=$?` 再输出。

---

## 15. 青龙全托管（2026-10-30 迁移完成）

### 15.1 目录布局（全部在青龙持久卷）

```
/ql/data/huawei_checkin/            源码 + 构建上下文（Dockerfile / checkin.py / qinglong/）
/ql/data/huawei_checkin/data/       运行数据：state.json / detect.json / screenshots/
/ql/data/scripts/huawei_*.sh        青龙调用的调度脚本
```

宿主机 `/root/huawei_checkin` 不再被调度使用，可留作备份后删除。

### 15.2 凭据

青龙面板 → 环境变量 → `HW_USERNAME` / `HW_PASSWORD`（已写入）。
调度脚本 `docker run -e HW_USERNAME -e HW_PASSWORD` 继承，`data/config.json` 已删除。

### 15.3 必须知道的坑：`docker run -v` 的路径是宿主机视角

青龙容器里看到 `/ql/data/...`，但 `-v` 的源路径由**宿主机 docker daemon** 解析。
直接写 `-v /ql/data/...` 会让 daemon 在宿主机根目录**新建一个空目录**挂载进去，
现象是「状态文件不存在: /app/data/state.json」，而且看起来完全像登录态丢了。

脚本已自动翻译：读自身容器（`hostname`）的 Mounts，把 `/ql/data` 换成宿主机真实路径。

```bash
docker exec 1Panel-qinglong-3Emy sh -c \
  'docker inspect --format "{{range .Mounts}}{{if eq .Destination \"/ql/data\"}}{{.Source}}{{end}}{{end}}" $(hostname)'
```

### 15.4 青龙 2.24 API 备忘（本次实测）

| 用途 | 方法与路径 | 注意 |
|---|---|---|
| 登录 | `POST /api/user/login` | 取 `data.token`，后续用 `Authorization: Bearer` |
| 环境变量列表 | `GET /api/envs?page=1&size=50` | 返回 `data` 为数组 |
| 创建环境变量 | `POST /api/envs` | **body 必须是数组** `[{name,value,remarks}]` |
| 删除环境变量 | `DELETE /api/envs` | body 是 `[id]` 数组 |
| 任务列表 | `GET /api/crons?page=1&size=20` | **不是 `/api/crontabs`** |
| 手动运行任务 | `PUT /api/crons/run` | body 是 `[id]` 数组 |

### 15.5 迁移后的日常操作

- **看日志**：青龙面板 → 定时任务 → 对应任务 → 日志
- **改代码**：编辑 `/ql/data/huawei_checkin` 下文件 → 运行「华为云初始化」任务重建镜像
  （设环境变量 `FORCE_REBUILD=1` 强制重建，否则镜像已存在会跳过）
- **重新登录**：运行「华为云扫码登录」任务，二维码输出在该任务日志里
- **首次迁移**：运行「华为云初始化」任务即可（会校验凭据、登录态、镜像）

### 15.6 一键对接脚本（宿主机）

在仓库根目录执行，自动完成「上传脚本 + 写环境变量 + 建任务」：

```bash
python3 tools/attach_qinglong.py \
  --url http://127.0.0.1:5700 --user shier --password '青龙面板密码' \
  --hw-user 'GT-xxx' --hw-pass '华为云密码'
```

- 参数可省略，省略则交互式输入；密码输入不回显
- 也支持环境变量 `QL_PASSWORD` / `HW_USERNAME` / `HW_PASSWORD`，或 `--config` 指定含 `username`/`password` 的 JSON
- **幂等**：脚本、环境变量、任务均为「存在即更新」，重复执行安全
- 「华为云初始化」「华为云扫码登录」属于一次性人工操作，脚本不自动建任务，只打印命令供你在面板按需新建

---

## 16. 镜像托管到 GitHub（ghcr.io）

仓库已内含 `.github/workflows/docker-publish.yml`，推送到 GitHub 后自动构建并推送镜像。

### 16.1 步骤

1. 在 GitHub 新建仓库，把本仓库推送上去（`main` 或 `master` 分支）；
2. Actions 自动触发，使用内置 `GITHUB_TOKEN` 推送，无需额外密钥；
3. 目标机器拉取：

```bash
docker pull ghcr.io/<owner>/<repo>:latest
```

4. 若包设为私有，需先登录：`docker login ghcr.io -u <用户名> -p <PAT>`（PAT 需 `read:packages`）。

### 16.2 体积与成本提醒

- 基础镜像 `mcr.microsoft.com/playwright/python` 约 3.5GB，最终镜像约 4GB；
- GitHub Actions 首次构建要拉这个基础镜像，耗时较长（约 10–20 分钟），后续走 `type=gha` 缓存会快很多；
- ghcr 的存储与流量按账号配额计费，大镜像注意额度；
- 仅在同一台机器使用时，`docker save` / `docker load` 比走 ghcr 更快：

```bash
docker save huawei-checkin:latest | gzip > huawei-checkin.tar.gz
docker load < huawei-checkin.tar.gz
```

---

## 17. 一键交互部署（推荐入口）

在青龙所在宿主机执行，全程交互式，无需记参数：

```bash
bash deploy.sh
```

### 17.1 执行流程

```
==============================================
 华为云成长中心签到 · 一键交互部署
==============================================
青龙地址 [http://127.0.0.1:5700]:
青龙用户名 [admin]:
青龙密码:
华为云账号:
华为云密码:

[1/3] 检查镜像 huawei-checkin:latest
[2/3] 对接青龙面板
[3/3] 完成
```

脚本做三件事：

1. **准备镜像**：本地有 `huawei-checkin:latest` 直接用；没有则尝试
   `docker pull ghcr.io/shierduan/huaweiyunqiandao:latest` 并打 tag；
   拉取失败会询问是否本地 `docker build`
2. **对接青龙**：调用 `tools/attach_qinglong.py`，依次完成
   登录 → 上传 4 个调度脚本 → 写入 `HW_USERNAME` / `HW_PASSWORD` → 创建/更新 2 个定时任务
3. **给出后续步骤**：首次联调、配通知渠道、扫码登录、重建镜像

### 17.2 非交互用法（适合脚本化）

所有参数都可用环境变量预置，此时不再弹交互提示：

```bash
QL_URL=http://127.0.0.1:5700 \
QL_USER=shier \
QL_PASS='青龙密码' \
HW_USERNAME='GT-xxx' \
HW_PASSWORD='华为云密码' \
bash deploy.sh
```

### 17.3 幂等性

- 镜像已存在则跳过拉取/构建
- 脚本、环境变量、任务均「存在即更新」，重复执行不会产生重复任务
- 部署失败后可放心重跑

### 17.4 前置条件

| 项 | 要求 |
|---|---|
| 宿主机 | 已装 Docker，且有 `docker.sock` |
| 青龙 | 与签到容器同机（青龙头通过 `docker.sock` 起签到容器） |
| Python | 宿主机需 `python3`（脚本用标准库，无三方依赖） |
| 网络 | 能访问青龙地址；拉镜像需能访问 `ghcr.io` |
