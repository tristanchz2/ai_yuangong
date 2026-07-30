"""站点表 CRUD 操作"""

import asyncio
import json

from core.database import get_pool

# 并发锁：保护 create_site 中 MAX(id)+1 预生成 ID 的原子性
_create_lock = asyncio.Lock()


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
    """创建站点，返回新 ID（UNIQUE KEY MoW 下 MAX(id) 准确可靠）"""
    pool = await get_pool()
    async with _create_lock:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                # 1. 预生成下一个 ID（Doris AUTO_INCREMENT 不可靠）
                await cur.execute("SELECT IFNULL(MAX(id), 0) + 1 FROM sites")
                row = await cur.fetchone()
                new_id = row[0] if row else 1

                # 2. 显式写入 id
                await cur.execute(
                    """INSERT INTO sites (id, name, url, scraper_name, description, aliases, status, hidden)
                       VALUES (%s, %s, %s, %s, %s, %s, 'active', 0)""",
                    (new_id, name, url, scraper_name, description, _dump_aliases(aliases))
                )
                return new_id


async def update_site(site_id: int, name: str, description: str = "", aliases: list | None = None):
    """更新站点名称、描述和别名（UNIQUE KEY MoW 支持 UPDATE）"""
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
    """设置站点隐藏/显示状态（UNIQUE KEY MoW 支持 UPDATE）"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            new_hidden = 1 if hidden else 0
            await cur.execute(
                "UPDATE sites SET hidden = %s WHERE id = %s",
                (new_hidden, site_id)
            )
