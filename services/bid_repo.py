"""标书主表 CRUD 操作"""

from core.database import get_pool


async def insert_bid(bid_data: dict) -> int:
    """插入一条标书到 bids 表，返回 bid_id"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                INSERT INTO bids (
                    site_id, source, scrape_time, url, content, title, notice_type,
                    publish_time, publish_date, bid_time, bid_date,
                    summary, keywords, budget,
                    purchaser, purchaser_region, service_category,
                    service_province, service_city, service_location, remarks
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
            """, (
                bid_data.get("site_id"),
                bid_data.get("source"),
                bid_data.get("scrape_time"),
                bid_data.get("url"),
                bid_data.get("content"),
                bid_data.get("title"),
                bid_data.get("notice_type"),
                bid_data.get("publish_time"),
                bid_data.get("publish_date"),
                bid_data.get("bid_time"),
                bid_data.get("bid_date"),
                bid_data.get("summary"),
                bid_data.get("keywords_json"),  # JSON 字符串
                bid_data.get("budget"),
                bid_data.get("purchaser"),
                bid_data.get("purchaser_region"),
                bid_data.get("service_category"),
                bid_data.get("service_province"),
                bid_data.get("service_city"),
                bid_data.get("service_location"),
                bid_data.get("remarks"),
            ))
            return cur.lastrowid


async def get_site_id_by_scraper_name(scraper_name: str):
    """通过 scraper_name 查询 sites 表的唯一 ID，不存在返回 None"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id FROM sites WHERE scraper_name = %s", (scraper_name,))
            row = await cur.fetchone()
    return row[0] if row else None


async def get_scraper_to_site_id_map() -> dict:
    """返回 {scraper_name: site_id} 映射（供 extract_fields 批量查询）"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT scraper_name, id FROM sites WHERE scraper_name IS NOT NULL")
            rows = await cur.fetchall()
    return {r[0]: r[1] for r in rows}


async def delete_bids_by_source_date(site_id: int, data_date: str) -> int:
    """
    通过爬取索引表级联删除指定站点 + 日期的标书数据。
    流程：读索引表 bid_id → 删除订阅词子表 → 删除省份索引表 → 删除 bids 主表 → 清空索引表。
    返回删除的 bids 数量。
    """
    from services.scrape_index import scrape_idx_table_name

    pool = await get_pool()
    table_name = scrape_idx_table_name(site_id, data_date)

    # 1. 检查索引表是否存在，不存在则无需删除
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema = DATABASE() AND table_name = %s",
                (table_name,)
            )
            if (await cur.fetchone())[0] == 0:
                return 0

    # 2. 从索引表读取所有 bid_id
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(f"SELECT bid_id FROM `{table_name}`")
            rows = await cur.fetchall()

    if not rows:
        return 0

    bid_ids = [r[0] for r in rows]
    placeholders = ",".join(["%s"] * len(bid_ids))

    # 3. 删除所有订阅词子表中的关联记录
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id FROM keywords")
            kw_rows = await cur.fetchall()
    for kw_row in kw_rows:
        sub_table = f"sub_{kw_row[0]}"
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    f"DELETE FROM `{sub_table}` WHERE bid_id IN ({placeholders})",
                    tuple(bid_ids),
                )

    # 4. 删除所有省份索引表中的关联记录
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id FROM provinces")
            province_rows = await cur.fetchall()
    for province_row in province_rows:
        province_table = f"province_{province_row[0]}"
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    f"DELETE FROM `{province_table}` WHERE bid_id IN ({placeholders})",
                    tuple(bid_ids),
                )

    # 5. 删除 bids 主表记录
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                f"DELETE FROM bids WHERE id IN ({placeholders})",
                tuple(bid_ids),
            )

    # 6. 清空索引表（保留表结构，下次爬取复用）
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(f"TRUNCATE TABLE `{table_name}`")

    return len(bid_ids)
