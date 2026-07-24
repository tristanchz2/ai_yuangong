FROM python:3.12-slim

# 设置环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    NODE_ENV=production \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# 安装运行时系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    # Xvfb 虚拟显示器（Chrome 有头模式在无 GUI 环境需要）
    xvfb \
    # Playwright 运行时依赖
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
    # Chromium 可能还需要
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# 安装 Node.js 20.x
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# 设置工作目录
WORKDIR /app

# 复制依赖文件（利用 Docker 缓存层）
COPY pyproject.toml package.json package-lock.json* ./

# 安装 Python 依赖
RUN pip install --no-cache-dir .

# 安装 Node.js 依赖
RUN npm ci --only=production 2>/dev/null || npm install --only=production

# 安装 Playwright Chromium 浏览器
RUN npx playwright install chromium \
    && npx playwright install-deps chromium

# 复制应用代码
COPY . .

# 暴露端口
EXPOSE 8000

# 启动命令：用 xvfb-run 包裹，让 Chrome 有头模式在无 GUI 环境也能运行
CMD ["xvfb-run", "--auto-servernum", "python", "server.py"]
