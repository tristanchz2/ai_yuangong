"""管理员路由 - 登录、网站管理、批量爬取"""

import asyncio
import json
import os
import secrets
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel

router = APIRouter(prefix="/api/admin", tags=["管理员"])

PROJECT_ROOT = Path(__file__).parent.parent
SITES_FILE = PROJECT_ROOT / "sites.json"

# 管理员 token 存储
admin_tokens: dict = {}


def get_admin_password() -> str:
    return os.environ.get("ADMIN_PASSWORD", "admin123")


def load_sites() -> list:
    if SITES_FILE.exists():
        with open(SITES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("sites", [])
    return []


def save_sites(sites: list):
    with open(SITES_FILE, "w", encoding="utf-8") as f:
        json.dump({"sites": sites}, f, ensure_ascii=False, indent=2)


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


# ============ 登录 ============

@router.post("/login", response_model=LoginResponse)
async def admin_login(req: LoginRequest):
    correct_password = get_admin_password()
    if req.password != correct_password:
        raise HTTPException(status_code=401, detail="密码错误")
    token = secrets.token_urlsafe(32)
    admin_tokens[token] = {"role": "admin"}
    return LoginResponse(token=token, message="登录成功")


# ============ 网站管理 ============

@router.get("/sites")
async def list_sites(_=Depends(verify_admin_token)):
    sites = load_sites()
    for s in sites:
        if "hidden" not in s:
            s["hidden"] = False
    return sites


@router.post("/sites")
async def add_site(site: SiteCreate, _=Depends(verify_admin_token)):
    sites = load_sites()
    for s in sites:
        if s["url"] == site.url:
            raise HTTPException(status_code=400, detail=f"网站已存在: {site.url}")
    new_id = max([s["id"] for s in sites], default=0) + 1
    scraper_name = site.scraper_name
    if not scraper_name:
        from routers.scraper import derive_scraper_name
        scraper_name = derive_scraper_name(site.url)
    new_site = {
        "id": new_id, "name": site.name, "url": site.url,
        "scraper_name": scraper_name, "description": site.description or "",
        "status": "active", "hidden": False
    }
    sites.append(new_site)
    save_sites(sites)
    return new_site


@router.delete("/sites/{site_id}")
async def delete_site(site_id: int, _=Depends(verify_admin_token)):
    sites = load_sites()
    original_len = len(sites)
    sites = [s for s in sites if s["id"] != site_id]
    if len(sites) == original_len:
        raise HTTPException(status_code=404, detail=f"网站不存在: id={site_id}")
    save_sites(sites)
    return {"message": f"网站已删除: id={site_id}", "remaining": len(sites)}


@router.put("/sites/{site_id}")
async def update_site(site_id: int, site: SiteCreate, _=Depends(verify_admin_token)):
    sites = load_sites()
    for i, s in enumerate(sites):
        if s["id"] == site_id:
            scraper_name = site.scraper_name
            if not scraper_name:
                from routers.scraper import derive_scraper_name
                scraper_name = derive_scraper_name(site.url)
            sites[i] = {
                "id": site_id, "name": site.name, "url": site.url,
                "scraper_name": scraper_name, "description": site.description or "",
                "status": s.get("status", "active"), "hidden": s.get("hidden", False)
            }
            save_sites(sites)
            return sites[i]
    raise HTTPException(status_code=404, detail=f"网站不存在: id={site_id}")


# ============ 隐藏/显示 ============

@router.post("/sites/{site_id}/hide")
async def hide_site(site_id: int, _=Depends(verify_admin_token)):
    sites = load_sites()
    for s in sites:
        if s["id"] == site_id:
            s["hidden"] = True
            save_sites(sites)
            return {"message": f"网站已隐藏: {s['name']}", "hidden": True}
    raise HTTPException(status_code=404, detail=f"网站不存在: id={site_id}")


@router.post("/sites/{site_id}/unhide")
async def unhide_site(site_id: int, _=Depends(verify_admin_token)):
    sites = load_sites()
    for s in sites:
        if s["id"] == site_id:
            s["hidden"] = False
            save_sites(sites)
            return {"message": f"网站已显示: {s['name']}", "hidden": False}
    raise HTTPException(status_code=404, detail=f"网站不存在: id={site_id}")


# ============ 批量爬取 ============

@router.post("/batch-scrape")
async def start_batch_scrape(mode: str = "yesterday", _=Depends(verify_admin_token)):
    from routers.batch_scraper import create_batch_task, run_batch_scrape, get_latest_batch_task
    existing = get_latest_batch_task()
    if existing and existing.status == "running":
        raise HTTPException(status_code=400, detail="已有批量任务正在运行")
    sites = load_sites()
    active_sites = [s for s in sites if not s.get("hidden", False)]
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
    """获取单个站点的终端日志"""
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

