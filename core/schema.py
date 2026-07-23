"""数据库建表与迁移逻辑"""

from config.constants import PROVINCE_CITY_MAP
from core.database import get_pool


async def ensure_tables():
    """自动建表（如果不存在）"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # 关闭当前会话的 warning 输出（IF NOT EXISTS 表已存在时不报警）
            await cur.execute("SET sql_notes = 0")
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS sites (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    name VARCHAR(200) NOT NULL,
                    url VARCHAR(500) NOT NULL UNIQUE,
                    scraper_name VARCHAR(100) DEFAULT NULL,
                    description VARCHAR(500) DEFAULT '',
                    aliases JSON DEFAULT NULL,
                    status VARCHAR(20) DEFAULT 'active',
                    hidden BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS keywords (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    word VARCHAR(200) NOT NULL UNIQUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            # 省份配置表：预建固定省份列表（用于省份索引表与前端筛选）
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS provinces (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    name VARCHAR(100) NOT NULL UNIQUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            # 预填充省份数据（先查已有再插缺失，避免 INSERT IGNORE 产生 duplicate 警告）
            await cur.execute("SELECT name FROM provinces")
            existing_provinces = {r[0] for r in await cur.fetchall()}
            for province_name in PROVINCE_CITY_MAP.keys():
                if province_name not in existing_provinces:
                    await cur.execute(
                        "INSERT INTO provinces (name) VALUES (%s)",
                        (province_name,)
                    )
            # 标书主表：存储 LLM 提取的全部结构化字段
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS bids (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    source VARCHAR(100) DEFAULT NULL,
                    scrape_time VARCHAR(50) DEFAULT NULL,
                    url VARCHAR(1000) DEFAULT NULL,
                    content LONGTEXT,
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
                    remarks TEXT DEFAULT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_source (source),
                    INDEX idx_notice_type (notice_type),
                    INDEX idx_publish_time (publish_time),
                    INDEX idx_type_publish (notice_type, publish_date),
                    INDEX idx_type_bid (notice_type, bid_date),
                    INDEX idx_budget (budget)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            await cur.execute("SET sql_notes = 1")

    # 兼容旧库：若 bids 表缺少 service_city 列（早期版本建的表），自动补加
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SHOW COLUMNS FROM bids LIKE 'service_city'")
            if not await cur.fetchone():
                await cur.execute(
                    "ALTER TABLE bids ADD COLUMN service_city VARCHAR(50) DEFAULT NULL AFTER service_province"
                )

    # 兼容旧库：若 bids 表缺少 site_id 列，自动补加（关联 sites 表唯一 ID）
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SHOW COLUMNS FROM bids LIKE 'site_id'")
            if not await cur.fetchone():
                await cur.execute(
                    "ALTER TABLE bids ADD COLUMN site_id INT DEFAULT NULL AFTER id, ADD INDEX idx_site_id (site_id)"
                )

    # 兼容旧库：若 sites 表缺少 aliases 列（搜索别名，JSON 数组），自动补加
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SHOW COLUMNS FROM sites LIKE 'aliases'")
            if not await cur.fetchone():
                await cur.execute(
                    "ALTER TABLE sites ADD COLUMN aliases JSON DEFAULT NULL AFTER description"
                )

    # 兼容旧库：若 bids 表缺少 publish_date / bid_date 列，自动补加 + 索引
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SHOW COLUMNS FROM bids LIKE 'publish_date'")
            if not await cur.fetchone():
                await cur.execute(
                    "ALTER TABLE bids ADD COLUMN publish_date DATE DEFAULT NULL AFTER publish_time, "
                    "ADD INDEX idx_type_publish (notice_type, publish_date)"
                )
            await cur.execute("SHOW COLUMNS FROM bids LIKE 'bid_date'")
            if not await cur.fetchone():
                await cur.execute(
                    "ALTER TABLE bids ADD COLUMN bid_date DATE DEFAULT NULL AFTER bid_time, "
                    "ADD INDEX idx_type_bid (notice_type, bid_date)"
                )
            # budget 索引
            await cur.execute("SHOW INDEX FROM bids WHERE Key_name = 'idx_budget'")
            if not await cur.fetchone():
                await cur.execute("ALTER TABLE bids ADD INDEX idx_budget (budget)")

    # 确保所有订阅词对应的子表存在
    from services.subscription import ensure_all_subscription_tables
    await ensure_all_subscription_tables()
    # 确保所有省份索引表存在
    from services.province_index import ensure_all_province_tables
    await ensure_all_province_tables()
