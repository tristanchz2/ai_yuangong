"""管理员路由 - 登录、网站管理、批量爬取、订阅词管理"""

import asyncio
import os
import secrets
import time
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Depends, Header

from config.settings import PROJECT_ROOT, SCRAPERS_DIR, RAW_DATA_DIR
from core.database import get_pool
from models.schemas import LoginRequest, LoginResponse, SiteCreate, SiteUpdate, KeywordCreate
from services.subscription import ensure_subscription_table, drop_subscription_table
from services.scraper_generator import run_hermes_generate, tasks as generate_tasks, derive_scraper_name, _cleanup_scraper_files
import services.site_repo as site_repo

router = APIRouter(prefix="/api/admin", tags=["管理员"])

# 管理员 token 存储
admin_tokens: dict = {}


def _check_no_running_task():
    """检查是否有运行中的批量爬取任务，有则抛出异常"""
    from services.batch_task import batch_tasks
    for task in batch_tasks.values():
        if task.status == "running":
            raise HTTPException(
                status_code=400,
                detail="有爬虫任务正在运行，请等待任务完成后再操作订阅词"
            )


def is_debug_mode() -> bool:
    return os.environ.get("APP_MODE", "release").lower() == "debug"


def get_admin_password() -> str:
    return os.environ.get("ADMIN_PASSWORD", "admin123")


async def verify_admin_token(x_admin_token: str = Header(...)):
    if x_admin_token not in admin_tokens:
        raise HTTPException(status_code=401, detail="未授权，请先登录")
    return admin_tokens[x_admin_token]


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
    return await site_repo.list_sites(include_hidden=True)


@router.post("/sites")
async def add_site(site: SiteCreate, _=Depends(verify_admin_token)):
    scraper_name = site.scraper_name
    if not scraper_name:
        scraper_name = derive_scraper_name(site.url)

    if await site_repo.site_url_exists(site.url):
        raise HTTPException(status_code=400, detail=f"网站已存在: {site.url}")

    # 触发爬虫生成（成功后才注册到数据库，避免定时任务爬到空站点）
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

    async def generate_then_register():
        try:
            await run_hermes_generate(task_id, site.url, scraper_name, site.reference_urls, site.has_attachment)
            task = generate_tasks.get(task_id)
            if task and task.get('status') == 'success':
                # 爬虫生成成功后才注册站点到数据库
                new_id = await site_repo.create_site(site.name, site.url, scraper_name, site.description or "", site.aliases or [])
                task['site_id'] = new_id
            else:
                await _cleanup_scraper_files(scraper_name)
        except Exception:
            await _cleanup_scraper_files(scraper_name)

    asyncio.create_task(generate_then_register())

    return {
        "name": site.name, "url": site.url,
        "scraper_name": scraper_name, "description": site.description or "",
        "task_id": task_id, "message": "爬虫正在生成，成功后自动注册站点"
    }


@router.delete("/sites/{site_id}")
async def delete_site(site_id: int, _=Depends(verify_admin_token)):
    site = await site_repo.get_site_by_id(site_id)
    if not site:
        raise HTTPException(status_code=404, detail=f"网站不存在: id={site_id}")

    scraper_name = site["scraper_name"]
    await site_repo.delete_site(site_id)

    deleted_files = []
    if scraper_name:
        scraper_file = SCRAPERS_DIR / f"scrape_{scraper_name}.js"
        if scraper_file.exists():
            scraper_file.unlink()
            deleted_files.append(str(scraper_file))
        data_file = RAW_DATA_DIR / f"{scraper_name}_data.json"
        if data_file.exists():
            data_file.unlink()
            deleted_files.append(str(data_file))

    return {"message": f"网站已删除: id={site_id}", "deleted_files": deleted_files}


@router.put("/sites/{site_id}")
async def update_site(site_id: int, site: SiteUpdate, _=Depends(verify_admin_token)):
    existing = await site_repo.get_site_by_id(site_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"网站不存在: id={site_id}")

    await site_repo.update_site(site_id, site.name, site.description or "", site.aliases or [])
    return {"message": "网站已更新", "id": site_id}


# ============ 隐藏/显示 ============

@router.post("/sites/{site_id}/hide")
async def hide_site(site_id: int, _=Depends(verify_admin_token)):
    site = await site_repo.get_site_by_id(site_id)
    if not site:
        raise HTTPException(status_code=404, detail=f"网站不存在: id={site_id}")
    await site_repo.set_site_hidden(site_id, True)
    return {"message": f"网站已隐藏: {site['name']}", "hidden": True}


@router.post("/sites/{site_id}/unhide")
async def unhide_site(site_id: int, _=Depends(verify_admin_token)):
    site = await site_repo.get_site_by_id(site_id)
    if not site:
        raise HTTPException(status_code=404, detail=f"网站不存在: id={site_id}")
    await site_repo.set_site_hidden(site_id, False)
    return {"message": f"网站已显示: {site['name']}", "hidden": False}


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
    _check_no_running_task()
    word = req.word.strip()
    if not word:
        raise HTTPException(status_code=400, detail="订阅词不能为空")

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id FROM keywords WHERE word = %s", (word,))
            if await cur.fetchone():
                raise HTTPException(status_code=400, detail=f"订阅词已存在: {word}")
            # 预生成下一个 ID（Doris AUTO_INCREMENT 不可靠）
            await cur.execute("SELECT IFNULL(MAX(id), 0) + 1 FROM keywords")
            row = await cur.fetchone()
            new_id = row[0] if row else 1
            await cur.execute(
                "INSERT INTO keywords (id, word) VALUES (%s, %s)",
                (new_id, word)
            )

    # 同步创建对应的订阅词子表
    await ensure_subscription_table(new_id)

    return {"id": new_id, "word": word, "message": f"订阅词已添加: {word}"}


@router.delete("/keywords/{keyword_id}")
async def delete_keyword(keyword_id: int, _=Depends(verify_admin_token)):
    _check_no_running_task()
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


# ============ 推送昨日订阅数据 ============


@router.post("/push-yesterday")
async def push_yesterday_data(_=Depends(verify_admin_token)):
    """推送昨天符合订阅词的数据到 webhook，一条一条推送"""
    from core.database import get_pool
    from datetime import date, timedelta
    from services.subscription import get_all_subscription_keywords

    webhook_url = os.getenv("YZJ_WEBHOOK_URL", "").strip()
    if not webhook_url:
        raise HTTPException(status_code=400, detail="未配置云之家 Webhook，请在 .env 中填写 YZJ_WEBHOOK_URL")

    yesterday = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")

    # 获取所有订阅词
    keywords = await get_all_subscription_keywords()  # [(id, word), ...]
    if not keywords:
        raise HTTPException(status_code=400, detail="当前没有订阅词，请先添加订阅词")

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # 查询昨天的采购公告（含推送所需字段）
            await cur.execute(
                "SELECT id, title, source, url, purchaser, budget, "
                "service_category, bid_time, publish_time, service_location "
                "FROM bids WHERE publish_date = %s AND notice_type = '采购公告'",
                (yesterday,)
            )
            rows = await cur.fetchall()

    if not rows:
        raise HTTPException(status_code=200, detail=f"昨天({yesterday})没有爬取数据，无需推送")

    # 构建 bid_id -> 订阅词匹配 的映射
    bid_matches = {}  # {bid_id: [matched_word, ...]}
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            for kw_id, kw_word in keywords:
                sub_table = f"sub_{kw_id}"
                try:
                    await cur.execute(
                        f"SELECT bid_id FROM `{sub_table}` WHERE bid_id IN ({','.join(['%s'] * len(rows))})",
                        tuple(r[0] for r in rows)
                    )
                    matched_rows = await cur.fetchall()
                    for mr in matched_rows:
                        bid_id = mr[0]
                        if bid_id not in bid_matches:
                            bid_matches[bid_id] = []
                        bid_matches[bid_id].append(kw_word)
                except Exception:
                    pass  # 子表不存在则跳过

    if not bid_matches:
        raise HTTPException(status_code=200, detail=f"昨天({yesterday})的数据没有匹配到任何订阅词")

    # 构建 bid_id -> row 的索引
    bid_row_map = {r[0]: r for r in rows}

    # 一条一条推送到 webhook
    pushed = 0
    failed = 0
    async with httpx.AsyncClient(timeout=10.0) as client:
        for bid_id, matched_words in bid_matches.items():
            bid_row = bid_row_map.get(bid_id)
            if not bid_row:
                continue
            (_, title, source, url, purchaser, budget,
             service_category, bid_time, publish_time, service_location) = bid_row

            budget_str = f"{budget:,.2f}元" if budget else "未公开"
            content = f"""【订阅词】{'、'.join(matched_words)}
【标题】{title or ''}
【采购人】{purchaser or ''}
【预算金额】{budget_str}
【服务类型】{service_category or ''}
【招标时间】{bid_time or ''}
【发布时间】{publish_time or ''}
【服务地址】{service_location or ''}
【来源】{source or ''}
【链接】{url or ''}"""
            payload = {"content": content}

            try:
                resp = await client.post(
                    webhook_url,
                    json=payload,
                    headers={"Content-Type": "application/json;charset=utf-8"}
                )
                if resp.status_code == 200:
                    pushed += 1
                else:
                    failed += 1
            except Exception:
                failed += 1

    return {
        "message": f"推送完成：成功 {pushed} 条，失败 {failed} 条（共 {len(bid_matches)} 条匹配数据）",
        "pushed": pushed,
        "failed": failed,
        "total": len(bid_matches),
    }


# ============ 批量爬取 ============

@router.post("/batch-scrape")
async def start_batch_scrape(mode: str = "yesterday", _=Depends(verify_admin_token)):
    from services.batch_task import create_batch_task, run_batch_scrape, get_latest_batch_task
    existing = get_latest_batch_task()
    if existing and existing.status == "running":
        raise HTTPException(status_code=400, detail="已有批量任务正在运行")

    active_sites = await site_repo.list_sites(include_hidden=False)

    if not active_sites:
        raise HTTPException(status_code=400, detail="没有可爬取的网站（所有网站已隐藏）")
    task = create_batch_task(mode)
    asyncio.create_task(run_batch_scrape(task, active_sites))
    return {"task_id": task.task_id, "message": f"批量爬取任务已启动，共 {len(active_sites)} 个站点", "total_sites": len(active_sites)}


@router.get("/batch-scrape/latest")
async def get_latest_batch_status(_=Depends(verify_admin_token)):
    from services.batch_task import get_latest_batch_task
    task = get_latest_batch_task()
    if not task:
        return {"status": "none", "message": "暂无批量任务"}
    return task.to_dict()


@router.get("/batch-scrape/{task_id}")
async def get_batch_status(task_id: str, _=Depends(verify_admin_token)):
    from services.batch_task import get_batch_task
    task = get_batch_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task.to_dict()


@router.get("/batch-scrape/{task_id}/sites/{site_id}/logs")
async def get_site_logs(task_id: str, site_id: int, _=Depends(verify_admin_token)):
    from services.batch_task import get_batch_task
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
    from services.batch_task import get_batch_task
    task = get_batch_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status != "running":
        raise HTTPException(status_code=400, detail=f"任务不在运行中 (当前状态: {task.status})")
    task.request_cancel()
    return {"message": "任务已终止", "task_id": task_id}


@router.get("/tasks")
async def get_all_tasks(_=Depends(verify_admin_token)):
    from services.batch_task import batch_tasks

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

