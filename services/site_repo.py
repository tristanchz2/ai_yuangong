"""站点表 CRUD 操作"""

import json

from core.database import get_pool


def _parse_aliases(val) -> list:
    """将 DB 中的 JSON 字符串解析为别名列表，异常/空值返回 []"""
    if not val:
        return []
    if isinstance(val, list):
        return val
    try:
        parsed = json.loads(val)
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _dump_aliases(aliases) -> str | None:
    """将别名列表序列化为 JSON 字符串，空列表返回 None"""
    if not aliases:
        return None
    return json.dumps(aliases, ensure_ascii=False)


async def list_sites(include_hidden: bool = True) -> list:
    """获取站点列表"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            if include_hidden:
                await cur.execute(
                    "SELECT id, name, url, scraper_name, description, status, hidden, aliases FROM sites ORDER BY id"
                )
            else:
                await cur.execute(
                    "SELECT id, name, url, scraper_name, description, status, hidden, aliases FROM sites WHERE hidden = 0 ORDER BY id"
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
            "aliases": _parse_aliases(row[7]),
        })
    return sites


async def get_site_by_id(site_id: int):
    """通过 ID 获取站点，不存在返回 None"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT id, name, url, scraper_name, description, status, hidden, aliases FROM sites WHERE id = %s",
                (site_id,)
            )
            row = await cur.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "name": row[1],
        "url": row[2],
        "scraper_name": row[3],
        "description": row[4] or "",
        "status": row[5],
        "hidden": bool(row[6]),
        "aliases": _parse_aliases(row[7]),
    }


async def site_url_exists(url: str) -> bool:
    """检查 URL 是否已存在"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id FROM sites WHERE url = %s", (url,))
            return await cur.fetchone() is not None


async def create_site(name: str, url: str, scraper_name: str, description: str = "", aliases: list | None = None) -> int:
    """创建站点，返回新 ID"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """INSERT INTO sites (name, url, scraper_name, description, aliases, status, hidden)
                   VALUES (%s, %s, %s, %s, %s, 'active', 0)""",
                (name, url, scraper_name, description, _dump_aliases(aliases))
            )
            return cur.lastrowid


async def update_site(site_id: int, name: str, description: str = "", aliases: list | None = None):
    """更新站点名称、描述和别名"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE sites SET name = %s, description = %s, aliases = %s WHERE id = %s",
                (name, description, _dump_aliases(aliases), site_id)
            )


async def delete_site(site_id: int):
    """删除站点"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM sites WHERE id = %s", (site_id,))


async def set_site_hidden(site_id: int, hidden: bool):
    """设置站点隐藏/显示状态"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE sites SET hidden = %s WHERE id = %s",
                (1 if hidden else 0, site_id)
            )
