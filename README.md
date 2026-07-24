# AI 员工 (ai_yuangong)

## 项目目标

聚合国内主要金融机构（银行）的政府采购平台数据，为供应商和采购人员提供一站式采购信息检索服务。

## 实现方式

### 整体架构

```
爬虫层 (Node.js)  →  原始数据 (JSON)  →  LLM 提取 (Python)  →  MySQL  →  Web 前端
```

### 技术栈

- **后端**：Python 3.x + FastAPI + uvicorn
- **爬虫**：Node.js + Playwright（浏览器自动化）+ cycletls（TLS 指纹绕过）
- **AI 提取**：OpenAI 兼容 API（支持本地部署的 LLM）
- **数据库**：MySQL 8.0（aiomysql 异步连接池）
- **前端**：原生 HTML/JS 单页应用

### 数据流水线

1. **爬取**：各平台独立爬虫脚本（`scrapers/scrape_*.js`），通过 Playwright 模拟浏览器访问，输出原始 JSON 到 `raw_data/`
2. **提取**：`scripts/extract_fields.py` 调用 LLM 从原始公告中提取结构化字段（标题、预算、服务地点、公告类型等），写入 MySQL `bids` 表
3. **展示**：FastAPI 后端提供 RESTful API，前端页面支持分类浏览、关键词订阅、省市筛选、预算范围、时间范围等多维检索

### 核心功能

- **爬虫自动生成**：输入目标 URL，通过 Hermes Agent 自动生成 Playwright 爬虫脚本
- **批量爬取**：管理后台一键触发所有站点并行爬取
- **LLM 结构化提取**：利用大模型从非结构化公告文本中提取标准字段
- **关键词订阅**：自定义订阅词，匹配命中的公告高亮展示
- **省市索引**：按服务地点省份/城市快速筛选
- **管理后台**：站点管理、订阅词管理、批量任务监控

## 使用方式

### 方式一：Docker 部署（推荐）

#### 前置条件

1. **安装 Docker**
   - macOS/Windows: 安装 [Docker Desktop](https://www.docker.com/products/docker-desktop/)
   - Linux: `sudo apt install docker.io`

2. **准备 MySQL 数据库**
   - 可以在宿主机安装 MySQL 8.0+
   - 或使用云数据库（阿里云 RDS、腾讯云 MySQL 等）
   - **只需建库，表会自动创建**

   ```sql
   -- 登录 MySQL 后执行
   CREATE DATABASE ai_yuangong CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
   CREATE USER 'app_user'@'%' IDENTIFIED BY 'your_password';
   GRANT ALL PRIVILEGES ON ai_yuangong.* TO 'app_user'@'%';
   FLUSH PRIVILEGES;
   ```

#### 快速启动

```bash
# 1. 克隆项目
git clone https://github.com/tristanchz2/ai_yuangong.git
cd ai_yuangong

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，填入：
#   - DB_HOST: MySQL 地址（容器内用 host.docker.internal 访问宿主机数据库）
#   - DB_PORT: 3306
#   - DB_USER: app_user
#   - DB_PASSWORD: 你的数据库密码
#   - DB_NAME: ai_yuangong
#   - OPENAI_API_KEY: LLM API 密钥
#   - OPENAI_BASE_URL: API 地址
#   - OPENAI_MODEL: 模型名称
#   - ADMIN_PASSWORD: 管理员密码
#   - APP_MODE: debug 或 release

# 3. 构建镜像（首次需要 5-10 分钟）
docker build -t ai-yuangong .

# 4. 运行容器
docker run -d \
  -p 8000:8000 \
  -v $(pwd)/.env:/app/.env:ro \
  --name ai-yuangong \
  ai-yuangong

# 5. 查看日志
docker logs -f ai-yuangong
```

启动后访问：
- 前端页面：http://localhost:8000/
- 管理后台：http://localhost:8000/admin

#### 常用命令

```bash
# 停止容器
docker stop ai-yuangong

# 启动容器
docker start ai-yuangong

# 重启容器
docker restart ai-yuangong

# 查看运行状态
docker ps

# 进入容器调试
docker exec -it ai-yuangong /bin/bash

# 运行爬虫（在容器内）
docker exec -it ai-yuangong python scripts/run_scrapers.py --all --yesterday

# 提取字段（在容器内）
docker exec -it ai-yuangong python scripts/extract_fields.py
```

#### 更新镜像

```bash
# 拉取最新代码
git pull

# 重新构建镜像（依赖层已缓存，通常很快）
docker build -t ai-yuangong .

# 删除旧容器
docker rm -f ai-yuangong

# 重新运行
docker run -d -p 8000:8000 -v $(pwd)/.env:/app/.env:ro --name ai-yuangong ai-yuangong
```

### 方式二：源码部署

#### 环境要求

- Python 3.12+
- Node.js 20+
- MySQL 8.0+

#### 安装

```bash
# 1. 克隆项目
git clone https://github.com/tristanchz2/ai_yuangong.git
cd ai_yuangong

# 2. 安装 Python 依赖
pip install .

# 3. 安装 Node.js 依赖
npm install

# 4. 安装 Playwright 浏览器
npx playwright install chromium
```

#### 配置

复制 `.env.example` 为 `.env`，编辑以下配置：

```env
# LLM 配置（用于字段提取）
OPENAI_API_KEY=your-api-key
OPENAI_BASE_URL=http://your-llm-server/v1
OPENAI_MODEL=your-model-name

# 应用模式: debug / release
APP_MODE=debug

# 管理员密码
ADMIN_PASSWORD=your-password

# MySQL 数据库（需要先手动建库，表会自动创建）
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=app_user
DB_PASSWORD=your-db-password
DB_NAME=ai_yuangong
```

#### 启动服务

```bash
# 方式 A：直接运行
python server.py

# 方式 B：开发模式（热重载）
uvicorn server:app --reload --port 8000
```

启动后访问：
- 前端页面：http://localhost:8000/
- 管理后台：http://localhost:8000/admin

### 运行爬虫

```bash
# 列出所有可用爬虫
python scripts/run_scrapers.py --list

# 运行指定爬虫（爬最新 5 条）
python scripts/run_scrapers.py --run ccb

# 运行所有爬虫（并行，爬昨天数据）
python scripts/run_scrapers.py --all --yesterday

# 运行所有爬虫（爬指定日期）
python scripts/run_scrapers.py --all --date 2026-07-01

# 交互式选择
python scripts/run_scrapers.py
```

### 提取字段（写入数据库）

```bash
# 处理所有 raw_data 文件
python scripts/extract_fields.py

# 只处理指定来源
python scripts/extract_fields.py --source ccb,icbc

# 设置并发数
python scripts/extract_fields.py --concurrency 3
```

## 项目结构

```
├── config/          # 全局配置（环境变量、常量）
├── core/            # 数据库连接、建表、工具函数
├── models/          # Pydantic 数据模型
├── routers/         # FastAPI 路由（数据展示、爬虫生成、管理后台）
├── scrapers/        # Node.js 爬虫脚本（每站一个 scrape_*.js）
├── scripts/         # Python 脚本入口（运行爬虫、LLM 提取）
├── services/        # 业务逻辑（爬虫生成、LLM 提取、订阅、索引）
├── static/          # 前端页面（index.html、admin.html）
├── raw_data/        # 爬虫输出的原始 JSON 数据
├── logs/            # 运行日志
├── server.py        # FastAPI 应用入口
├── pyproject.toml   # Python 依赖管理（替代 requirements.txt）
├── package.json     # Node.js 依赖管理
├── Dockerfile       # Docker 镜像构建文件
├── .dockerignore    # Docker 构建忽略规则
├── .env.example     # 环境变量模板
└── .env             # 环境变量配置（不提交到 Git）
```

