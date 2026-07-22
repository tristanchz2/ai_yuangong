"""数据库模块 - 兼容性 shim，实际逻辑已迁移至 core/ 和 services/ 模块"""

# 连接池管理
from core.database import init_db, get_pool, close_db, get_yesterday_str

# 建表与迁移
from core.schema import ensure_tables

# 省市数据
from config.constants import PROVINCE_CITY_MAP

# 地区解析
from services.region import parse_service_region

# 订阅词管理
from services.subscription import (
    ensure_subscription_table,
    drop_subscription_table,
    ensure_all_subscription_tables,
    get_all_subscription_keywords,
    insert_bid_subscription,
)

# 省份索引
from services.province_index import (
    ensure_all_province_tables,
    get_all_provinces,
    insert_bid_province,
)

# 爬取索引
from services.scrape_index import (
    ensure_scrape_idx_table,
    insert_scrape_idx,
)

# 标书 CRUD
from services.bid_repo import (
    insert_bid,
    get_site_id_by_scraper_name,
    get_scraper_to_site_id_map,
    delete_bids_by_source_date,
)
