"""数据库模块 - aiomysql 连接池管理"""

import os
from datetime import date, timedelta
from pathlib import Path

import aiomysql

_pool: aiomysql.Pool | None = None

PROJECT_ROOT = Path(__file__).parent

# 省份 → 城市列表映射（用于校验 LLM 输出的"xx省xx市"是否匹配，以及前端级联筛选）
PROVINCE_CITY_MAP = {
    "北京": ["北京"],
    "天津": ["天津"],
    "上海": ["上海"],
    "重庆": ["重庆"],
    "河北": ["石家庄", "唐山", "保定", "邯郸", "廊坊", "秦皇岛", "沧州", "邢台", "衡水", "张家口", "承德"],
    "山西": ["太原", "大同", "运城", "临汾", "晋中", "长治", "晋城", "朔州", "忻州", "吕梁", "阳泉"],
    "辽宁": ["沈阳", "大连", "鞍山", "抚顺", "本溪", "丹东", "锦州", "营口", "阜新", "辽阳", "盘锦", "铁岭", "朝阳", "葫芦岛"],
    "吉林": ["长春", "吉林", "四平", "辽源", "通化", "白山", "松原", "白城"],
    "黑龙江": ["哈尔滨", "齐齐哈尔", "大庆", "牡丹江", "佳木斯", "鸡西", "双鸭山", "伊春", "七台河", "鹤岗", "绥化"],
    "江苏": ["南京", "苏州", "无锡", "常州", "徐州", "南通", "扬州", "盐城", "镇江", "泰州", "淮安", "连云港", "宿迁"],
    "浙江": ["杭州", "宁波", "温州", "绍兴", "嘉兴", "金华", "台州", "湖州", "丽水", "衢州", "舟山"],
    "安徽": ["合肥", "芜湖", "蚌埠", "淮南", "马鞍山", "淮北", "铜陵", "安庆", "黄山", "滁州", "阜阳", "宿州", "六安", "亳州", "池州", "宣城"],
    "福建": ["福州", "厦门", "泉州", "漳州", "莆田", "龙岩", "三明", "南平", "宁德"],
    "江西": ["南昌", "九江", "赣州", "吉安", "宜春", "抚州", "上饶", "萍乡", "景德镇", "新余", "鹰潭"],
    "山东": ["济南", "青岛", "烟台", "潍坊", "临沂", "淄博", "威海", "济宁", "泰安", "日照", "德州", "聊城", "滨州", "菏泽", "东营", "枣庄"],
    "河南": ["郑州", "洛阳", "南阳", "许昌", "周口", "新乡", "商丘", "信阳", "驻马店", "开封", "焦作", "安阳", "平顶山", "漯河", "濮阳", "鹤壁", "三门峡"],
    "湖北": ["武汉", "宜昌", "襄阳", "荆州", "黄冈", "十堰", "孝感", "荆门", "鄂州", "黄石", "咸宁", "随州"],
    "湖南": ["长沙", "株洲", "湘潭", "衡阳", "岳阳", "常德", "郴州", "娄底", "邵阳", "益阳", "永州", "怀化", "张家界"],
    "广东": ["广州", "深圳", "东莞", "佛山", "珠海", "中山", "惠州", "江门", "汕头", "湛江", "茂名", "肇庆", "揭阳", "梅州", "清远", "阳江", "韶关", "河源", "云浮", "汕尾", "潮州"],
    "广西": ["南宁", "柳州", "桂林", "玉林", "梧州", "北海", "钦州", "贵港", "百色", "河池", "来宾", "贺州", "防城港", "崇左"],
    "海南": ["海口", "三亚", "儋州", "三沙", "琼海", "文昌", "万宁", "五指山", "东方"],
    "四川": ["成都", "绵阳", "德阳", "宜宾", "南充", "泸州", "达州", "乐山", "自贡", "内江", "遂宁", "广安", "眉山", "雅安", "广元", "巴中", "资阳", "攀枝花"],
    "贵州": ["贵阳", "遵义", "六盘水", "安顺", "毕节", "铜仁", "黔南", "黔东南", "黔西南"],
    "云南": ["昆明", "曲靖", "大理", "红河", "玉溪", "楚雄", "昭通", "文山", "普洱", "保山", "临沧", "丽江", "德宏", "迪庆", "怒江", "西双版纳"],
    "西藏": ["拉萨", "日喀则", "昌都", "林芝", "山南", "那曲", "阿里"],
    "陕西": ["西安", "咸阳", "宝鸡", "渭南", "汉中", "榆林", "延安", "安康", "商洛", "铜川"],
    "甘肃": ["兰州", "天水", "白银", "庆阳", "平凉", "酒泉", "张掖", "武威", "定西", "金昌", "陇南", "嘉峪关"],
    "青海": ["西宁", "海东", "海西", "海北", "黄南", "海南州", "果洛", "玉树"],
    "宁夏": ["银川", "石嘴山", "吴忠", "固原", "中卫"],
    "新疆": ["乌鲁木齐", "昌吉", "伊犁", "阿克苏", "巴音郭楞", "喀什", "哈密", "克拉玛依", "博尔塔拉", "塔城", "阿勒泰", "和田"],
    "内蒙古": ["呼和浩特", "包头", "鄂尔多斯", "赤峰", "通辽", "呼伦贝尔", "巴彦淖尔", "乌兰察布", "乌海", "锡林郭勒", "兴安盟", "阿拉善盟"],
    "台湾": ["台北", "高雄", "台中", "台南", "基隆", "新竹", "嘉义"],
    "香港": ["香港"],
    "澳门": ["澳门"],
}


def parse_service_region(raw: str | None) -> tuple:
    """
    校验并分离 "xx省xx市" 字符串（兼容 广东深圳 / 广东省深圳市 / 广东深圳
    等多种写法）。
    返回 (province, city)；省市对不上或无法识别则返回 (None, None)。
    """
    if not raw:
        return (None, None)
    s = raw.strip()
    if not s:
        return (None, None)

    def _clean_city(c: str) -> str:
        for suffix in ("市", "地区", "自治州", "盟"):
            if c.endswith(suffix) and len(c) > len(suffix):
                return c[:-len(suffix)]
        return c

    # 按已知省份前缀匹配（优先匹配较长的省名，如 黑龙江 > 河北）
    for province in sorted(PROVINCE_CITY_MAP.keys(), key=len, reverse=True):
        if not s.startswith(province):
            continue
        rest = s[len(province):]
        # 去掉省/自治区后缀
        for suffix in ("壮族自治区", "回族自治区", "维吾尔自治区", "自治区", "特别行政区", "省"):
            if rest.startswith(suffix):
                rest = rest[len(suffix):]
                break
        city = _clean_city(rest.strip())
        # 直辖市：省=市
        if province in ("北京", "天津", "上海", "重庆"):
            if city in (province, ""):
                return (province, province)
            continue
        cities = PROVINCE_CITY_MAP[province]
        if city in cities:
            return (province, city)
        # 模糊匹配：如 "深圳特区" → "深圳"
        for c in cities:
            if city and (city.startswith(c) or c.startswith(city)):
                return (province, c)
        # 省匹配上了但市对不上
        return (None, None)
    return (None, None)


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
    await ensure_all_subscription_tables()
    # 确保所有省份索引表存在
    await ensure_all_province_tables()


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


# ──────────────────────────────────────────────
# 省份索引表管理（城市不建索引表，直接用 WHERE service_city 查询）
# ──────────────────────────────────────────────

async def ensure_all_province_tables():
    """为 provinces 表中所有省份创建索引子表"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id FROM provinces")
            rows = await cur.fetchall()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SET sql_notes = 0")
            for (province_id,) in rows:
                await cur.execute(f"""
                    CREATE TABLE IF NOT EXISTS `province_{province_id}` (
                        bid_id BIGINT NOT NULL,
                        PRIMARY KEY (bid_id)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """)
            await cur.execute("SET sql_notes = 1")


async def get_all_provinces() -> list:
    """获取所有省份，返回 [(id, name), ...]"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id, name FROM provinces ORDER BY id")
            rows = await cur.fetchall()
    return [(row[0], row[1]) for row in rows]


async def insert_bid_province(bid_id: int, province_id: int):
    """将标书 ID 插入到对应省份的索引子表中"""
    table_name = f"province_{province_id}"
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                f"INSERT IGNORE INTO `{table_name}` (bid_id) VALUES (%s)",
                (bid_id,)
            )


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


def get_yesterday_str() -> str:
    """获取昨天的日期字符串，格式: YYYY-MM-DD"""
    return (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")


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


def _scrape_idx_table(site_id: int, data_date: str) -> str:
    """生成爬取索引表名，格式: scrape_idx_site{site_id}_{YYYYMMDD}（用 sites 表唯一 ID，杜绝名称不一致）"""
    date_compact = data_date.replace("-", "")
    return f"scrape_idx_site{site_id}_{date_compact}"


async def ensure_scrape_idx_table(site_id: int, data_date: str):
    """确保某个站点+日期的爬取索引表存在（只有一列 bid_id）"""
    table_name = _scrape_idx_table(site_id, data_date)
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


async def insert_scrape_idx(site_id: int, data_date: str, bid_id: int):
    """将 bid_id 写入对应的爬取索引表"""
    table_name = _scrape_idx_table(site_id, data_date)
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                f"INSERT IGNORE INTO `{table_name}` (bid_id) VALUES (%s)",
                (bid_id,)
            )


async def delete_bids_by_source_date(site_id: int, data_date: str) -> int:
    """
    通过爬取索引表级联删除指定站点 + 日期的标书数据。
    流程：读索引表 bid_id → 删除订阅词子表 → 删除省份索引表 → 删除 bids 主表 → 清空索引表。
    返回删除的 bids 数量。
    """
    pool = await get_pool()
    table_name = _scrape_idx_table(site_id, data_date)

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
