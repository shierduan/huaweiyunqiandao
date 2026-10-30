FROM mcr.microsoft.com/playwright/python:v1.64.1-noble

# 注意: 该官方镜像**只内置了浏览器**，并未安装 playwright 包，需自行补装。
# 浏览器位于 /ms-playwright (由基础镜像的 PLAYWRIGHT_BROWSERS_PATH 指定)，无需再下载。

ARG PIP_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    HW_DATA_DIR=/app/data \
    TZ=Asia/Shanghai

# 补装 playwright（与镜像内置浏览器版本 1.64.1 对齐）
# qrcode + opencv 仅用于把登录二维码渲染到终端
RUN pip install --no-cache-dir --break-system-packages -i ${PIP_INDEX} \
        playwright==1.64.1 \
        qrcode==7.4.2 \
        opencv-python-headless==4.10.0.84

WORKDIR /app
COPY checkin.py qr_login.py cli.py entrypoint.sh /app/

RUN chmod +x /app/entrypoint.sh && mkdir -p /app/data/screenshots

# 登录态(cookies)一律保存在 /app/data，由宿主机挂载注入，镜像内不含任何凭据
VOLUME ["/app/data"]

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["cli"]
