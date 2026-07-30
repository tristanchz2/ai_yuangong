"""标书主表 CRUD 操作"""

import asyncio

from core.database import get_pool

# 预生成 ID 的互斥锁，防止并发下 MAX(id)+1 冲突
_id_lock = asyncio.Lock()


async def insert_bid(bid_data: dict) -> int:
    """插入一条标书到 bids 表，返回 bid_id。
    Doris DUPLICATE KEY 表下 aiomysql.lastrowid 不可靠，
    改用预生成 ID（MAX(id)+1）+ 显式写入，asyncio.Lock 保证并发安全。
    """
    pool = await get_pool()
    async with _id_lock:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                # 1. 预生成下一个 ID
                await cur.execute("SELECT IFNULL(MAX(id), 0) + 1 FROM bids")
                row = await cur.fetchone()
                new_id = row[0] if row else 1

                # 2. 显式写入 id
                await cur.execute("""
                    INSERT INTO bids (
                        id,
                        site_id, source, scrape_time, url, content, title, notice_type,
                        publish_time, publish_date, bid_time, bid_date,
                        summary, keywords, budget,
                        purchaser, purchaser_region, service_category,
                        service_province, service_city, service_location, remarks, winners
                    ) VALUES (
                        %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s
                    )
                """, (
                    new_id,
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
                    bid_data.get("winners_json"),  # JSON 字符串
                ))
                return new_id


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


async def get_site_id_to_name_map() -> dict:
    """返回 {site_id: site_name} 映射（用于统一 source 名称为 sites 表当前名）"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id, name FROM sites")
            rows = await cur.fetchall()
    return {r[0]: r[1] for r in rows}


async def delete_bids_by_source_date(site_id: int, data_date: str) -> int:
    """
    直接从 bids 表中删除指定站点 + 日期的标书数据，并级联清理子表。
    返回删除的 bids 数量。
    """
    pool = await get_pool()

    # 1. 先查出要删除的 bid_id（供子表清理用）
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT id FROM bids WHERE site_id = %s AND publish_date = %s",
                (site_id, data_date),
            )
            rows = await cur.fetchall()

    if not rows:
        return 0

    bid_ids = [r[0] for r in rows]
    placeholders = ",".join(["%s"] * len(bid_ids))

    # 2. 删除所有订阅词子表中的关联记录
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

    # 3. 删除 bids 主表记录
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                f"DELETE FROM bids WHERE id IN ({placeholders})",
                tuple(bid_ids),
            )

    return len(bid_ids)
