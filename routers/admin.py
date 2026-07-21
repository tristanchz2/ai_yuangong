"""管理员路由 - 登录、网站管理、批量爬取、订阅词管理"""

import asyncio
import os
import secrets
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel

from db import get_pool, ensure_subscription_table, drop_subscription_table
from routers.scraper import run_hermes_generate, tasks as generate_tasks

router = APIRouter(prefix="/api/admin", tags=["管理员"])

PROJECT_ROOT = Path(__file__).parent.parent

# 管理员 token 存储
admin_tokens: dict = {}


def is_debug_mode() -> bool:
    return os.environ.get("APP_MODE", "release").lower() == "debug"


def get_admin_password() -> str:
    return os.environ.get("ADMIN_PASSWORD", "admin123")


async def verify_admin_token(x_admin_token: str = Header(...)):
    if x_admin_token not in admin_tokens:
        raise HTTPException(status_code=401, detail="未授权，请先登录")
    return admin_tokens[x_admin_token]


# ============ 模型 ============

class LoginRequest(BaseModel):
    password: str


class LoginResponse(BaseModel):
    token: str
    message: str


class SiteCreate(BaseModel):
    name: str
    url: str
    scraper_name: Optional[str] = None
    description: Optional[str] = None
    reference_urls: Optional[list[str]] = None


class SiteUpdate(BaseModel):
    name: str
    description: Optional[str] = None


class KeywordCreate(BaseModel):
    word: str


# ============ 登录 ============

@router.post("/login", response_model=LoginResponse)
async def admin_login(req: LoginRequest):
    if not is_debug_mode():
        correct_password = get_admin_password()
        if req.password != correct_password:
            raise HTTPException(status_code=401, detail="密码错误")
    token = secrets.token_urlsafe(32)
    admin_tokens[token] = {"role": "admin"}
    return LoginResponse(token=token, message="登录成功")


# ============ 网站管理 ============

@router.get("/sites")
async def list_sites(_=Depends(verify_admin_token)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT id, name, url, scraper_name, description, status, hidden FROM sites ORDER BY id"
            )
            rows = await cur.fetchall()
    sites = []
    for row in rows:
        sites.append({
            "id": row[0],
            "name": row[1],
            "url": row[2],
            "scraper_name": row[3],
            "description": row[4] or "",
            "status": row[5],
            "hidden": bool(row[6]),
        })
    return sites


@router.post("/sites")
async def add_site(site: SiteCreate, _=Depends(verify_admin_token)):
    pool = await get_pool()
    scraper_name = site.scraper_name
    if not scraper_name:
        from routers.scraper import derive_scraper_name
        scraper_name = derive_scraper_name(site.url)

    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id FROM sites WHERE url = %s", (site.url,))
            if await cur.fetchone():
                raise HTTPException(status_code=400, detail=f"网站已存在: {site.url}")

            await cur.execute(
                """INSERT INTO sites (name, url, scraper_name, description, status, hidden)
                   VALUES (%s, %s, %s, %s, 'active', 0)""",
                (site.name, site.url, scraper_name, site.description or "")
            )
            new_id = cur.lastrowid

    new_site = {
        "id": new_id, "name": site.name, "url": site.url,
        "scraper_name": scraper_name, "description": site.description or "",
        "status": "active", "hidden": False
    }

    # 触发爬虫生成
    task_id = f"task_{int(time.time() * 1000)}"
    generate_tasks[task_id] = {
        'task_id': task_id,
        'task_type': 'generate',
        'status': 'pending',
        'url': site.url,
        'scraper_name': scraper_name,
        'reference_urls': site.reference_urls or [],
        'created_at': time.time(),
    }

    async def generate_with_rollback():
        try:
            await run_hermes_generate(task_id, site.url, scraper_name, site.reference_urls)
            task = generate_tasks.get(task_id)
            if task and task.get('status') != 'success':
                p = await get_pool()
                async with p.acquire() as c:
                    async with c.cursor() as cur2:
                        await cur2.execute("DELETE FROM sites WHERE id = %s", (new_id,))
        except Exception:
            p = await get_pool()
            async with p.acquire() as c:
                async with c.cursor() as cur2:
                    await cur2.execute("DELETE FROM sites WHERE id = %s", (new_id,))

    asyncio.create_task(generate_with_rollback())

    return {**new_site, "task_id": task_id, "message": "网站已添加，爬虫正在生成"}


@router.delete("/sites/{site_id}")
async def delete_site(site_id: int, _=Depends(verify_admin_token)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT id, name, scraper_name FROM sites WHERE id = %s", (site_id,)
            )
            row = await cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail=f"网站不存在: id={site_id}")

            scraper_name = row[2]
            await cur.execute("DELETE FROM sites WHERE id = %s", (site_id,))

    deleted_files = []
    if scraper_name:
        scraper_file = PROJECT_ROOT / "scrapers" / f"scrape_{scraper_name}.js"
        if scraper_file.exists():
            scraper_file.unlink()
            deleted_files.append(str(scraper_file))
        data_file = PROJECT_ROOT / "raw_data" / f"{scraper_name}_data.json"
        if data_file.exists():
            data_file.unlink()
            deleted_files.append(str(data_file))

    return {"message": f"网站已删除: id={site_id}", "deleted_files": deleted_files}


@router.put("/sites/{site_id}")
async def update_site(site_id: int, site: SiteUpdate, _=Depends(verify_admin_token)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id FROM sites WHERE id = %s", (site_id,))
            if not await cur.fetchone():
                raise HTTPException(status_code=404, detail=f"网站不存在: id={site_id}")

            await cur.execute(
                "UPDATE sites SET name = %s, description = %s WHERE id = %s",
                (site.name, site.description or "", site_id)
            )

    return {"message": "网站已更新", "id": site_id}


# ============ 隐藏/显示 ============

@router.post("/sites/{site_id}/hide")
async def hide_site(site_id: int, _=Depends(verify_admin_token)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT name FROM sites WHERE id = %s", (site_id,))
            row = await cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail=f"网站不存在: id={site_id}")
            await cur.execute("UPDATE sites SET hidden = 1 WHERE id = %s", (site_id,))
    return {"message": f"网站已隐藏: {row[0]}", "hidden": True}


@router.post("/sites/{site_id}/unhide")
async def unhide_site(site_id: int, _=Depends(verify_admin_token)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT name FROM sites WHERE id = %s", (site_id,))
            row = await cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail=f"网站不存在: id={site_id}")
            await cur.execute("UPDATE sites SET hidden = 0 WHERE id = %s", (site_id,))
    return {"message": f"网站已显示: {row[0]}", "hidden": False}


# ============ 订阅词管理 ============

@router.get("/keywords")
async def list_keywords(_=Depends(verify_admin_token)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id, word, created_at FROM keywords ORDER BY id")
            rows = await cur.fetchall()
    result = []
    for row in rows:
        result.append({
            "id": row[0],
            "word": row[1],
            "created_at": row[2].isoformat() if row[2] else None,
        })
    return result


@router.post("/keywords")
async def add_keyword(req: KeywordCreate, _=Depends(verify_admin_token)):
    word = req.word.strip()
    if not word:
        raise HTTPException(status_code=400, detail="订阅词不能为空")

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id FROM keywords WHERE word = %s", (word,))
            if await cur.fetchone():
                raise HTTPException(status_code=400, detail=f"订阅词已存在: {word}")
            await cur.execute("INSERT INTO keywords (word) VALUES (%s)", (word,))
            new_id = cur.lastrowid

    # 同步创建对应的订阅词子表
    await ensure_subscription_table(new_id)

    return {"id": new_id, "word": word, "message": f"订阅词已添加: {word}"}


@router.delete("/keywords/{keyword_id}")
async def delete_keyword(keyword_id: int, _=Depends(verify_admin_token)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT word FROM keywords WHERE id = %s", (keyword_id,))
            row = await cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail=f"订阅词不存在: id={keyword_id}")
            await cur.execute("DELETE FROM keywords WHERE id = %s", (keyword_id,))

    # 同步删除对应的订阅词子表
    await drop_subscription_table(keyword_id)

    return {"message": f"订阅词已删除: {row[0]}"}


# ============ 批量爬取 ============

@router.post("/batch-scrape")
async def start_batch_scrape(mode: str = "yesterday", _=Depends(verify_admin_token)):
    from routers.batch_scraper import create_batch_task, run_batch_scrape, get_latest_batch_task
    existing = get_latest_batch_task()
    if existing and existing.status == "running":
        raise HTTPException(status_code=400, detail="已有批量任务正在运行")

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT id, name, url, scraper_name, description, status, hidden FROM sites WHERE hidden = 0 ORDER BY id"
            )
            rows = await cur.fetchall()

    active_sites = []
    for row in rows:
        active_sites.append({
            "id": row[0],
            "name": row[1],
            "url": row[2],
            "scraper_name": row[3],
            "description": row[4] or "",
            "status": row[5],
            "hidden": bool(row[6]),
        })

    if not active_sites:
        raise HTTPException(status_code=400, detail="没有可爬取的网站（所有网站已隐藏）")
    task = create_batch_task(mode)
    asyncio.create_task(run_batch_scrape(task, active_sites))
    return {"task_id": task.task_id, "message": f"批量爬取任务已启动，共 {len(active_sites)} 个站点", "total_sites": len(active_sites)}


@router.get("/batch-scrape/latest")
async def get_latest_batch_status(_=Depends(verify_admin_token)):
    from routers.batch_scraper import get_latest_batch_task
    task = get_latest_batch_task()
    if not task:
        return {"status": "none", "message": "暂无批量任务"}
    return task.to_dict()


@router.get("/batch-scrape/{task_id}")
async def get_batch_status(task_id: str, _=Depends(verify_admin_token)):
    from routers.batch_scraper import get_batch_task
    task = get_batch_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task.to_dict()


@router.get("/batch-scrape/{task_id}/sites/{site_id}/logs")
async def get_site_logs(task_id: str, site_id: int, _=Depends(verify_admin_token)):
    from routers.batch_scraper import get_batch_task
    task = get_batch_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    for st in task.site_tasks:
        if st.site["id"] == site_id:
            return {
                "site_id": site_id,
                "site_name": st.site["name"],
                "status": st.status,
                "logs": st.logs,
            }
    raise HTTPException(status_code=404, detail=f"站点不存在: id={site_id}")


@router.post("/batch-scrape/{task_id}/cancel")
async def cancel_batch_scrape(task_id: str, _=Depends(verify_admin_token)):
    from routers.batch_scraper import get_batch_task
    task = get_batch_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status != "running":
        raise HTTPException(status_code=400, detail=f"任务不在运行中 (当前状态: {task.status})")
    task.request_cancel()
    return {"message": "任务已终止", "task_id": task_id}


@router.get("/tasks")
async def get_all_tasks(_=Depends(verify_admin_token)):
    from routers.batch_scraper import batch_tasks

    all_tasks = []

    for task_id, task in batch_tasks.items():
        task_dict = task.to_dict()
        duration = (task.finished_at - task.started_at) if task.started_at and task.finished_at else None
        all_tasks.append({
            'task_id': task_id,
            'type': 'batch_scrape',
            'status': task_dict['status'],
            'description': f"批量爬取 {task_dict['total_sites']} 个站点",
            'created_at': task.created_at,
            'duration': duration,
            'details': task_dict
        })

    for task_id, task in generate_tasks.items():
        duration = None
        if task.get('started_at') and task.get('finished_at'):
            duration = task['finished_at'] - task['started_at']

        all_tasks.append({
            'task_id': task_id,
            'type': 'generate_scraper',
            'status': task['status'],
            'description': f"生成爬虫: {task.get('scraper_name', 'unknown')}",
            'created_at': task['created_at'],
            'duration': duration,
            'details': task
        })

    all_tasks.sort(key=lambda x: x['created_at'], reverse=True)

    return {'tasks': all_tasks[:5]}

