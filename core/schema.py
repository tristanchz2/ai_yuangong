"""数据库建表与迁移逻辑（适配 Apache Doris 3.x）"""

from config.constants import PROVINCE_CITY_MAP
from core.database import get_pool


async def _column_exists(cur, table: str, column: str) -> bool:
    """通过 information_schema 检查列是否存在"""
    await cur.execute(
        "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s",
        (table, column),
    )
    return await cur.fetchone() is not None


async def ensure_tables():
    """自动建表（如果不存在）—— Doris 3.x 语法"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # ---- sites 表 ----
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS sites (
                    id BIGINT NOT NULL AUTO_INCREMENT,
                    name VARCHAR(200) NOT NULL,
                    url VARCHAR(500) NOT NULL,
                    scraper_name VARCHAR(100) DEFAULT NULL,
                    description VARCHAR(500) DEFAULT '',
                    aliases JSON DEFAULT NULL,
                    status VARCHAR(20) DEFAULT 'active',
                    hidden TINYINT DEFAULT '0',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                UNIQUE KEY(id)
                DISTRIBUTED BY HASH(id) BUCKETS 1
                PROPERTIES ("replication_num" = "1")
            """)

            # ---- keywords 表 ----
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS keywords (
                    id BIGINT NOT NULL AUTO_INCREMENT,
                    word VARCHAR(200) NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                UNIQUE KEY(id)
                DISTRIBUTED BY HASH(id) BUCKETS 1
                PROPERTIES ("replication_num" = "1")
            """)

            # ---- provinces 表 ----
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS provinces (
                    id BIGINT NOT NULL AUTO_INCREMENT,
                    name VARCHAR(100) NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                UNIQUE KEY(id)
                DISTRIBUTED BY HASH(id) BUCKETS 1
                PROPERTIES ("replication_num" = "1")
            """)

            # 预填充省份数据
            await cur.execute("SELECT name FROM provinces")
            existing_provinces = {r[0] for r in await cur.fetchall()}
            for province_name in PROVINCE_CITY_MAP.keys():
                if province_name not in existing_provinces:
                    await cur.execute(
                        "INSERT INTO provinces (name) VALUES (%s)",
                        (province_name,)
                    )

            # ---- bids 主表 ----
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS bids (
                    id BIGINT NOT NULL AUTO_INCREMENT,
                    site_id BIGINT DEFAULT NULL,
                    source VARCHAR(100) DEFAULT NULL,
                    scrape_time VARCHAR(50) DEFAULT NULL,
                    url VARCHAR(1000) DEFAULT NULL,
                    content STRING DEFAULT NULL,
                    title VARCHAR(500) DEFAULT NULL,
                    notice_type VARCHAR(20) DEFAULT NULL,
                    publish_time VARCHAR(20) DEFAULT NULL,
                    publish_date DATE DEFAULT NULL,
                    bid_time VARCHAR(20) DEFAULT NULL,
                    bid_date DATE DEFAULT NULL,
                    summary VARCHAR(500) DEFAULT NULL,
                    keywords JSON DEFAULT NULL,
                    budget DOUBLE DEFAULT NULL,
                    purchaser VARCHAR(300) DEFAULT NULL,
                    purchaser_region VARCHAR(20) DEFAULT NULL,
                    service_category VARCHAR(200) DEFAULT NULL,
                    service_province VARCHAR(20) DEFAULT NULL,
                    service_city VARCHAR(50) DEFAULT NULL,
                    service_location VARCHAR(500) DEFAULT NULL,
                    remarks STRING DEFAULT NULL,
                    winners JSON DEFAULT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                DUPLICATE KEY(id)
                DISTRIBUTED BY HASH(id) BUCKETS 8
                PROPERTIES ("replication_num" = "1")
            """)

    # 兼容旧库：若 bids 表缺少列，自动补加
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            for col_name, col_def in [
                ("service_city", "VARCHAR(50) DEFAULT NULL"),
                ("site_id", "BIGINT DEFAULT NULL"),
                ("publish_date", "DATE DEFAULT NULL"),
                ("bid_date", "DATE DEFAULT NULL"),
                ("winners", "JSON DEFAULT NULL"),
            ]:
                if not await _column_exists(cur, "bids", col_name):
                    try:
                        await cur.execute(
                            f"ALTER TABLE bids ADD COLUMN {col_name} {col_def}"
                        )
                    except Exception:
                        pass

    # 兼容旧库：若 sites 表缺少 aliases 列，自动补加
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            if not await _column_exists(cur, "sites", "aliases"):
                try:
                    await cur.execute(
                        "ALTER TABLE sites ADD COLUMN aliases JSON DEFAULT NULL"
                    )
                except Exception:
                    pass

    # 确保所有订阅词对应的子表存在
    from services.subscription import ensure_all_subscription_tables
    await ensure_all_subscription_tables()
    # 确保所有省份索引表存在
    from services.province_index import ensure_all_province_tables
    await ensure_all_province_tables()
