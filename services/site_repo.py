"""站点表 CRUD 操作"""

import asyncio
import json

from core.database import get_pool

# 并发锁：保护 create_site 中 INSERT + MAX(id) 回退的原子性
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
    """创建站点，返回新 ID（加锁防止并发下 MAX(id) 回退不准）"""
    pool = await get_pool()
    async with _create_lock:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """INSERT INTO sites (name, url, scraper_name, description, aliases, status, hidden)
                       VALUES (%s, %s, %s, %s, %s, 'active', 0)""",
                    (name, url, scraper_name, description, _dump_aliases(aliases))
                )
                new_id = cur.lastrowid
                if new_id is None:
                    # Doris 可能不返回 lastrowid，回退查询
                    await cur.execute("SELECT MAX(id) FROM sites")
                    row = await cur.fetchone()
                    new_id = row[0] if row else None
                return new_id


async def update_site(site_id: int, name: str, description: str = "", aliases: list | None = None):
    """更新站点名称、描述和别名（Doris DUPLICATE KEY 不支持 UPDATE，用 DELETE+INSERT 替代）"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # 先读取当前行数据
            await cur.execute(
                "SELECT id, name, url, scraper_name, description, status, hidden, aliases FROM sites WHERE id = %s",
                (site_id,)
            )
            row = await cur.fetchone()
            if not row:
                return
            old = {
                "url": row[2], "scraper_name": row[3], "status": row[5],
                "hidden": row[6], "old_aliases": row[7],
            }
            # 删除旧行
            await cur.execute("DELETE FROM sites WHERE id = %s", (site_id,))
            # 插入新行（保留未变更字段）
            await cur.execute(
                """INSERT INTO sites (id, name, url, scraper_name, description, aliases, status, hidden)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (site_id, name, old["url"], old["scraper_name"], description,
                 _dump_aliases(aliases), old["status"], old["hidden"])
            )


async def delete_site(site_id: int):
    """删除站点"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM sites WHERE id = %s", (site_id,))


async def set_site_hidden(site_id: int, hidden: bool):
    """设置站点隐藏/显示状态（Doris DUPLICATE KEY 不支持 UPDATE，用 DELETE+INSERT 替代）"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # 先读取当前行完整数据
            await cur.execute(
                "SELECT id, name, url, scraper_name, description, status, hidden, aliases FROM sites WHERE id = %s",
                (site_id,)
            )
            row = await cur.fetchone()
            if not row:
                return
            new_hidden = 1 if hidden else 0
            # 如果值没变，跳过
            if row[6] == new_hidden:
                return
            # 删除旧行并插入新行
            await cur.execute("DELETE FROM sites WHERE id = %s", (site_id,))
            await cur.execute(
                """INSERT INTO sites (id, name, url, scraper_name, description, aliases, status, hidden)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (row[0], row[1], row[2], row[3], row[4], row[7], row[5], new_hidden)
            )
