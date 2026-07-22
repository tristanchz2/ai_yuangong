"""站点表 CRUD 操作"""

from core.database import get_pool


async def list_sites(include_hidden: bool = True) -> list:
    """获取站点列表"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            if include_hidden:
                await cur.execute(
                    "SELECT id, name, url, scraper_name, description, status, hidden FROM sites ORDER BY id"
                )
            else:
                await cur.execute(
                    "SELECT id, name, url, scraper_name, description, status, hidden FROM sites WHERE hidden = 0 ORDER BY id"
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


async def get_site_by_id(site_id: int):
    """通过 ID 获取站点，不存在返回 None"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT id, name, url, scraper_name, description, status, hidden FROM sites WHERE id = %s",
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
    }


async def site_url_exists(url: str) -> bool:
    """检查 URL 是否已存在"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id FROM sites WHERE url = %s", (url,))
            return await cur.fetchone() is not None


async def create_site(name: str, url: str, scraper_name: str, description: str = "") -> int:
    """创建站点，返回新 ID"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """INSERT INTO sites (name, url, scraper_name, description, status, hidden)
                   VALUES (%s, %s, %s, %s, 'active', 0)""",
                (name, url, scraper_name, description)
            )
            return cur.lastrowid


async def update_site(site_id: int, name: str, description: str = ""):
    """更新站点名称和描述"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE sites SET name = %s, description = %s WHERE id = %s",
                (name, description, site_id)
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
