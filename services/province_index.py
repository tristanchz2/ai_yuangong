"""省份索引表管理（适配 Doris 3.x）"""

from core.database import get_pool


async def ensure_all_province_tables():
    """为 provinces 表中所有省份创建索引子表"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id FROM provinces")
            rows = await cur.fetchall()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            for (province_id,) in rows:
                await cur.execute(f"""
                    CREATE TABLE IF NOT EXISTS `province_{province_id}` (
                        bid_id BIGINT NOT NULL
                    )
                    DUPLICATE KEY(bid_id)
                    DISTRIBUTED BY HASH(bid_id) BUCKETS 1
                    PROPERTIES ("replication_num" = "1")
                """)


async def get_all_provinces() -> list:
    """获取所有省份，返回 [(id, name), ...]"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id, name FROM provinces ORDER BY id")
            rows = await cur.fetchall()
    return [(row[0], row[1]) for row in rows]


async def insert_bid_province(bid_id: int, province_id: int):
    """将标书 ID 插入到对应省份的索引子表中（UNIQUE KEY 自动去重）"""
    table_name = f"province_{province_id}"
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                f"INSERT INTO `{table_name}` (bid_id) VALUES (%s)",
                (bid_id,)
            )
