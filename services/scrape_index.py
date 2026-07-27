"""爬取索引表管理（适配 Doris 3.x，source+date 独立索引）"""

from core.database import get_pool


def scrape_idx_table_name(site_id: int, data_date: str) -> str:
    """生成爬取索引表名，格式: scrape_idx_site{site_id}_{YYYYMMDD}"""
    date_compact = data_date.replace("-", "")
    return f"scrape_idx_site{site_id}_{date_compact}"


async def ensure_scrape_idx_table(site_id: int, data_date: str):
    """确保某个站点+日期的爬取索引表存在（只有一列 bid_id）"""
    table_name = scrape_idx_table_name(site_id, data_date)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(f"""
                CREATE TABLE IF NOT EXISTS `{table_name}` (
                    bid_id BIGINT NOT NULL
                )
                UNIQUE KEY(bid_id)
                DISTRIBUTED BY HASH(bid_id) BUCKETS 1
                PROPERTIES ("replication_num" = "1")
            """)


async def insert_scrape_idx(site_id: int, data_date: str, bid_id: int):
    """将 bid_id 写入对应的爬取索引表（UNIQUE KEY 自动去重）"""
    table_name = scrape_idx_table_name(site_id, data_date)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                f"INSERT INTO `{table_name}` (bid_id) VALUES (%s)",
                (bid_id,)
            )
