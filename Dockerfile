# 尝试从 DaoCloud 镜像拉取 bookworm（GLIBC 2.36，支持 cycletls）
FROM docker.m.daocloud.io/library/python:3.12-slim-bookworm

# Single-container deployment:
# FastAPI backend + Playwright scrapers (headless Chromium via Xvfb) + Hermes Agent
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    NODE_ENV=production \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright \
    HERMES_HOME=/hermes-data

WORKDIR /app

# ── 系统依赖 ─────────────────────────────────────────────────────────
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        xvfb \
        xauth \
        libnss3 \
        libnspr4 \
        libatk1.0-0 \
        libatk-bridge2.0-0 \
        libcups2 \
        libxkbcommon0 \
        libxcomposite1 \
        libxdamage1 \
        libxfixes3 \
        libxrandr2 \
        libgbm1 \
        libpango-1.0-0 \
        libcairo2 \
        libasound2 \
        libatspi2.0-0 \
        libwayland-client0 \
        fonts-liberation \
        libxss1 \
        libx11-xcb1 \
        libxcb-dri3-0 \
        libdrm2 \
    && rm -rf /var/lib/apt/lists/*

# Node.js 20.x
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# cycletls 依赖
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libssl3 \
        ca-certificates \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# ── Hermes Agent 安装（源代码在镜像内，数据在 volume 内）───────────
COPY hermes-src.tar.gz /tmp/hermes-src.tar.gz
RUN mkdir -p /opt/hermes-agent \
    && tar -xzf /tmp/hermes-src.tar.gz -C /opt/hermes-agent --strip-components=1 \
    && rm /tmp/hermes-src.tar.gz

# 安装 hermes 依赖（venv 在 /opt/hermes-agent/venv/，随镜像走）
RUN cd /opt/hermes-agent \
    && python -m venv /opt/hermes-agent/venv \
    && /opt/hermes-agent/venv/bin/pip install --no-cache-dir -e .

# hermes 命令加入 PATH
ENV PATH="/opt/hermes-agent/venv/bin:$PATH"

# 创建数据目录（volume 挂载点，首次运行需手动配置）
RUN mkdir -p /hermes-data

# ── 主项目依赖 ───────────────────────────────────────────────────────
COPY pyproject.toml README.md package.json package-lock.json* ./

RUN python -m pip install --no-cache-dir .

RUN npm ci --only=production 2>/dev/null || npm install --only=production

# Playwright Chromium
RUN npx playwright install chromium \
    && npx playwright install-deps chromium

RUN ln -sf /ms-playwright/chromium-1228/chrome-linux64/chrome /usr/bin/google-chrome

# ── 复制主项目代码 ──────────────────────────────────────────────────
COPY . /app

# 重新安装 npm 依赖（确保原生模块为 Linux 编译）
RUN npm install \
    && node -e "try { require('cycletls'); console.log('✓ cycletls 加载成功'); } catch(e) { console.error('✗ cycletls 加载失败:', e.message); process.exit(1); }" \
    && mkdir -p /app/raw_data /app/logs \
    && chmod -R 777 /app/raw_data /app/logs

# 启动：Xvfb 虚拟显示 + Playwright Chromium
CMD ["/bin/bash", "-c", "Xvfb :99 -screen 0 1024x768x24 -ac & export DISPLAY=:99 && python -u server.py"]
