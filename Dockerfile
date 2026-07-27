# 尝试从 DaoCloud 镜像拉取 bookworm（GLIBC 2.36，支持 cycletls）
FROM docker.m.daocloud.io/library/python:3.12-slim-bookworm

# Single-container deployment:
# FastAPI backend + Playwright scrapers (headless Chromium via Xvfb).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    NODE_ENV=production \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright

WORKDIR /app

# Xvfb provides a virtual display so Chromium headed mode works without GUI.
# Playwright runtime libs and fonts keep pages rendering correctly in container.
# 额外的 Chrome 依赖库用于 scrape_hfbank.js 和 scrape_cebbank.js
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

# Node.js 20.x is required by Playwright scrapers.
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# 安装 cycletls 需要的系统依赖 + 编译工具（用于 postinstall 脚本）
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libssl3 \
        ca-certificates \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency manifests first to leverage Docker layer caching.
COPY pyproject.toml README.md package.json package-lock.json* ./

RUN python -m pip install --no-cache-dir .

RUN npm ci --only=production 2>/dev/null || npm install --only=production

# Playwright Chromium browser binary (downloaded from npmmirror via PLAYWRIGHT_DOWNLOAD_HOST).
RUN npx playwright install chromium \
    && npx playwright install-deps chromium

# 创建符号链接，让爬虫代码能找到 Playwright 的 Chromium
RUN ln -sf /ms-playwright/chromium-1228/chrome-linux64/chrome /usr/bin/google-chrome

COPY . /app

# 重新安装 npm 依赖，确保原生模块为 Linux 平台编译
RUN npm install \
    && node -e "try { require('cycletls'); console.log('✓ cycletls 加载成功'); } catch(e) { console.error('✗ cycletls 加载失败:', e.message); process.exit(1); }" \
    && mkdir -p /app/raw_data /app/logs \
    && chmod -R 777 /app/raw_data /app/logs

EXPOSE 8080

# xvfb-run provides a virtual framebuffer for Chromium headed mode.
CMD ["xvfb-run", "--auto-servernum", "python", "server.py"]
