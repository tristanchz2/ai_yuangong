"""订阅词子表管理"""

from core.database import get_pool


async def ensure_subscription_table(keyword_id: int):
    """确保某个订阅词对应的子表存在（表名: sub_{keyword_id}）"""
    table_name = f"sub_{keyword_id}"
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SET sql_notes = 0")
            await cur.execute(f"""
                CREATE TABLE IF NOT EXISTS `{table_name}` (
                    bid_id BIGINT NOT NULL,
                    PRIMARY KEY (bid_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            await cur.execute("SET sql_notes = 1")


async def drop_subscription_table(keyword_id: int):
    """删除某个订阅词对应的子表"""
    table_name = f"sub_{keyword_id}"
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(f"DROP TABLE IF EXISTS `{table_name}`")


async def ensure_all_subscription_tables():
    """为 keywords 表中所有订阅词确保对应子表存在"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id FROM keywords")
            rows = await cur.fetchall()
    for row in rows:
        await ensure_subscription_table(row[0])


async def get_all_subscription_keywords() -> list:
    """获取所有订阅词，返回 [(id, word), ...]"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id, word FROM keywords ORDER BY id")
            rows = await cur.fetchall()
    return [(row[0], row[1]) for row in rows]


async def insert_bid_subscription(bid_id: int, keyword_id: int):
    """将标书 ID 插入到对应订阅词的子表中"""
    table_name = f"sub_{keyword_id}"
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                f"INSERT IGNORE INTO `{table_name}` (bid_id) VALUES (%s)",
                (bid_id,)
            )
