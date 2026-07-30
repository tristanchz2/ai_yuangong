"""省份数据查询（已移除省份索引子表机制，省份筛选改为直接查 bids.service_province）"""

from core.database import get_pool


async def get_all_provinces() -> list:
    """获取所有省份，返回 [(id, name), ...]"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id, name FROM provinces ORDER BY id")
            rows = await cur.fetchall()
    return [(row[0], row[1]) for row in rows]
