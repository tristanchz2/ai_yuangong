#!/usr/bin/env python3
"""
爬虫生成服务 - 接收 URL，调用 Hermes 自动生成爬虫

启动：
  uvicorn server:app --reload --port 8000

路由：
  /                    - 前端页面
  /api/categories      - 数据分类列表
  /api/data/{category} - 分类数据
  /api/admin/login     - 管理员登录
  /api/admin/sites     - 网站管理（需认证）
  /generate            - 生成爬虫
  /status              - 任务状态
  /logs/{task_id}      - 任务日志
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# 加载 .env（必须在其他 import 之前）
PROJECT_ROOT = Path(__file__).parent

def _load_env():
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, val = line.split('=', 1)
                    os.environ.setdefault(key.strip(), val.strip())

_load_env()

# 导入路由
from routers.data import router as data_router
from routers.scraper import router as scraper_router
from routers.admin import router as admin_router
from db import init_db, ensure_tables, close_db

# 创建 FastAPI 应用
@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await ensure_tables()
    yield
    await close_db()


app = FastAPI(title="爬虫生成服务", version="2.0", lifespan=lifespan)

# 项目目录
STATIC_DIR = PROJECT_ROOT / "static"
SCRAPERS_DIR = PROJECT_ROOT / "scrapers"

# 注册路由
app.include_router(data_router)
app.include_router(scraper_router)
app.include_router(admin_router)


# ============ 前端页面 ============

@app.get("/")
async def root():
    """前端页面"""
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="前端页面不存在")
    return FileResponse(index_path, media_type="text/html")


@app.get("/admin")
async def admin_page():
    """管理员页面"""
    admin_path = STATIC_DIR / "admin.html"
    if not admin_path.exists():
        raise HTTPException(status_code=404, detail="管理员页面不存在")
    return FileResponse(admin_path, media_type="text/html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
