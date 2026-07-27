FROM hub-kdjr.kingdee.com/base_images/python:3.12.10-slim-bullseye

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
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        xvfb \
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
    && rm -rf /var/lib/apt/lists/*

# Node.js 20.x is required by Playwright scrapers.
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency manifests first to leverage Docker layer caching.
COPY pyproject.toml README.md package.json package-lock.json* ./

RUN python -m pip install --no-cache-dir .

RUN npm ci --only=production 2>/dev/null || npm install --only=production

# Playwright Chromium browser binary (downloaded from npmmirror via PLAYWRIGHT_DOWNLOAD_HOST).
RUN npx playwright install chromium \
    && npx playwright install-deps chromium

COPY . /app

RUN mkdir -p /app/raw_data /app/logs \
    && chmod -R 777 /app/raw_data /app/logs

EXPOSE 8080

# xvfb-run provides a virtual framebuffer for Chromium headed mode.
CMD ["xvfb-run", "--auto-servernum", "python", "server.py"]
