"""数据库模块 - aiomysql 连接池管理"""

import os
from pathlib import Path

import aiomysql

_pool: aiomysql.Pool | None = None

PROJECT_ROOT = Path(__file__).parent


def _load_env():
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, val = line.split('=', 1)
                    os.environ.setdefault(key.strip(), val.strip())


_load_env()


async def init_db():
    """初始化数据库连接池"""
    global _pool
    _pool = await aiomysql.create_pool(
        host=os.environ.get("DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("DB_PORT", "3306")),
        user=os.environ.get("DB_USER", "app_user"),
        password=os.environ.get("DB_PASSWORD", "app_pass123"),
        db=os.environ.get("DB_NAME", "ai_yuangong"),
        charset="utf8mb4",
        autocommit=True,
        minsize=2,
        maxsize=10,
    )


async def get_pool() -> aiomysql.Pool:
    """获取连接池"""
    if _pool is None:
        await init_db()
    return _pool


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
                    bid_time VARCHAR(20) DEFAULT NULL,
                    summary VARCHAR(500) DEFAULT NULL,
                    keywords JSON DEFAULT NULL,
                    budget DOUBLE DEFAULT NULL,
                    purchaser VARCHAR(300) DEFAULT NULL,
                    purchaser_region VARCHAR(20) DEFAULT NULL,
                    service_category VARCHAR(200) DEFAULT NULL,
                    service_province VARCHAR(20) DEFAULT NULL,
                    service_location VARCHAR(500) DEFAULT NULL,
                    remarks TEXT DEFAULT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_source (source),
                    INDEX idx_notice_type (notice_type),
                    INDEX idx_publish_time (publish_time)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            # 标书关键词关联表（LLM 提取的关键词，每个关键词一行）
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS bid_keywords (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    bid_id BIGINT NOT NULL,
                    keyword VARCHAR(200) NOT NULL,
                    INDEX idx_bid_id (bid_id),
                    INDEX idx_keyword (keyword)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            await cur.execute("SET sql_notes = 1")

    # 确保所有订阅词对应的子表存在
    await ensure_all_subscription_tables()


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


async def insert_bid(bid_data: dict) -> int:
    """插入一条标书到 bids 表，返回 bid_id"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                INSERT INTO bids (
                    source, scrape_time, url, content, title, notice_type,
                    publish_time, bid_time, summary, keywords, budget,
                    purchaser, purchaser_region, service_category,
                    service_province, service_location, remarks
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
            """, (
                bid_data.get("source"),
                bid_data.get("scrape_time"),
                bid_data.get("url"),
                bid_data.get("content"),
                bid_data.get("title"),
                bid_data.get("notice_type"),
                bid_data.get("publish_time"),
                bid_data.get("bid_time"),
                bid_data.get("summary"),
                bid_data.get("keywords_json"),  # JSON 字符串
                bid_data.get("budget"),
                bid_data.get("purchaser"),
                bid_data.get("purchaser_region"),
                bid_data.get("service_category"),
                bid_data.get("service_province"),
                bid_data.get("service_location"),
                bid_data.get("remarks"),
            ))
            return cur.lastrowid


async def insert_bid_keywords(bid_id: int, keywords: list):
    """插入标书的提取关键词到 bid_keywords 表"""
    if not keywords:
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            for kw in keywords:
                await cur.execute(
                    "INSERT INTO bid_keywords (bid_id, keyword) VALUES (%s, %s)",
                    (bid_id, kw)
                )


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


async def close_db():
    """关闭连接池"""
    global _pool
    if _pool:
        _pool.close()
        await _pool.wait_closed()
        _pool = None
