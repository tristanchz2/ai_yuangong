"""数据展示路由 - 从数据库读取标书数据"""

import json
import re

from fastapi import APIRouter, HTTPException, Query

from core.database import get_pool
from config.constants import PROVINCE_CITY_MAP, DATA_CATEGORIES
from services.site_repo import _parse_aliases

router = APIRouter(prefix="/api", tags=["数据展示"])


@router.get("/categories")
async def get_categories():
    """返回所有数据分类及其记录数（从 DB bids 表统计）"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # 按 notice_type 统计记录数、源数量、最近更新时间
            await cur.execute("""
                SELECT notice_type, COUNT(*) as cnt, COUNT(DISTINCT source) as src_cnt,
                       MAX(created_at) as latest
                FROM bids
                GROUP BY notice_type
            """)
            rows = await cur.fetchall()

    # 构建结果
    stats = {}
    for row in rows:
        nt = row[0] or "其他"
        if nt not in DATA_CATEGORIES:
            nt = "其他"
        if nt not in stats:
            stats[nt] = {"count": 0, "sources": 0, "latest": None}
        stats[nt]["count"] += row[1]
        stats[nt]["sources"] += row[2]
        if row[3] and (not stats[nt]["latest"] or row[3] > stats[nt]["latest"]):
            stats[nt]["latest"] = row[3]

    categories = []
    for cat in DATA_CATEGORIES:
        s = stats.get(cat, {"count": 0, "sources": 0, "latest": None})
        categories.append({
            "name": cat,
            "fileCount": s["sources"],
            "totalRecords": s["count"],
            "latestExtractedAt": s["latest"].isoformat() if s["latest"] else None,
        })
    return {"categories": categories}


@router.get("/sources")
async def get_sources():
    """返回有数据的来源列表（从 scrape_idx 索引表提取 site_id，JOIN sites 取当前名称）
    已删除的站点不会出现在列表中。"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # 从 information_schema 中找到所有 scrape_idx_site{N}_{date} 表
            await cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = DATABASE() AND table_name LIKE 'scrape_idx_site%%'"
            )
            rows = await cur.fetchall()

    # 从表名中提取 site_id（去重）
    site_ids = set()
    for (table_name,) in rows:
        m = re.match(r"scrape_idx_site(\d+)_\d{8}$", table_name)
        if m:
            site_ids.add(int(m.group(1)))

    if not site_ids:
        return {"sources": []}

    # JOIN sites 表取当前名称，已删除的站点自然被排除
    placeholders = ",".join(["%s"] * len(site_ids))
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                f"SELECT id, name, description, aliases FROM sites WHERE id IN ({placeholders}) ORDER BY id",
                tuple(site_ids),
            )
            rows = await cur.fetchall()

    return {"sources": [{"id": r[0], "name": r[1], "description": r[2] or "", "aliases": _parse_aliases(r[3])} for r in rows]}


@router.get("/subscription-keywords")
async def get_subscription_keywords():
    """返回所有订阅词（供前端筛选下拉使用）"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id, word FROM keywords ORDER BY id")
            rows = await cur.fetchall()
    return {"keywords": [{"id": r[0], "word": r[1]} for r in rows]}


@router.get("/provinces")
async def get_provinces():
    """返回所有省份及其下辖城市（供前端省市级联筛选使用）"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id, name FROM provinces ORDER BY id")
            rows = await cur.fetchall()
    provinces = [
        {"id": r[0], "name": r[1], "cities": PROVINCE_CITY_MAP.get(r[1], [])}
        for r in rows
    ]
    return {"provinces": provinces}


async def _build_matched_keywords(bid_ids: list) -> dict:
    """计算一批标书各自命中的订阅词，返回 {bid_id: [word, ...]}"""
    matched_map: dict = {}
    if not bid_ids:
        return matched_map
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id, word FROM keywords ORDER BY id")
            all_kws = await cur.fetchall()
    if not all_kws:
        return matched_map
    # 一条 UNION ALL 查询汇总本页标书在各订阅词子表中的命中情况
    placeholders = ",".join(["%s"] * len(bid_ids))
    union_parts = [
        f"SELECT bid_id, {kid} AS kw_id FROM sub_{kid} WHERE bid_id IN ({placeholders})"
        for kid, _ in all_kws
    ]
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                " UNION ALL ".join(union_parts),
                tuple(bid_ids) * len(all_kws),
            )
            hit_rows = await cur.fetchall()
    kw_word_map = {r[0]: r[1] for r in all_kws}
    for bid_id, kw_id in hit_rows:
        matched_map.setdefault(bid_id, []).append(kw_word_map[kw_id])
    return matched_map


@router.get("/data/{category}")
async def get_category_data(
    category: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    keyword_ids: str = Query(default="", description="逗号分隔的订阅词ID，用于筛选"),
    site_ids: str = Query(default="", description="逗号分隔的来源站点ID，用于筛选"),
    province_ids: str = Query(default="", description="逗号分隔的省份ID，走省份索引表筛选"),
    city: str = Query(default="", description="城市名，走 WHERE service_city 筛选"),
    budget_min: float = Query(default=None, description="预算下限（元）"),
    budget_max: float = Query(default=None, description="预算上限（元）"),
    publish_date_from: str = Query(default="", description="发布时间起（YYYY-MM-DD）"),
    publish_date_to: str = Query(default="", description="发布时间止（YYYY-MM-DD）"),
    bid_date_from: str = Query(default="", description="招标时间起（YYYY-MM-DD）"),
    bid_date_to: str = Query(default="", description="招标时间止（YYYY-MM-DD）"),
):
    """从 DB 读取指定分类的标书数据（支持分页 + 订阅词 + 省市 + 预算 + 时间范围筛选）"""
    if category not in DATA_CATEGORIES:
        raise HTTPException(status_code=404, detail=f"分类不存在: {category}")

    pool = await get_pool()

    # 解析并校验订阅词 ID（仅允许 keywords 表中存在的整数 ID，防止拼接表名注入）
    kw_id_list: list = []
    if keyword_ids.strip():
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT id FROM keywords")
                valid_ids = {r[0] for r in await cur.fetchall()}
        for part in keyword_ids.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                kid = int(part)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"非法的订阅词ID: {part}")
            if kid not in valid_ids:
                raise HTTPException(status_code=400, detail=f"订阅词不存在: id={kid}")
            kw_id_list.append(kid)
        # 去重保序
        kw_id_list = list(dict.fromkeys(kw_id_list))

    # 解析并校验来源站点 ID（仅允许 sites 表中存在的整数 ID）
    site_id_list: list = []
    if site_ids.strip():
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT id FROM sites")
                valid_site_ids = {r[0] for r in await cur.fetchall()}
        for part in site_ids.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                sid = int(part)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"非法的站点ID: {part}")
            if sid not in valid_site_ids:
                raise HTTPException(status_code=400, detail=f"站点不存在: id={sid}")
            site_id_list.append(sid)
        site_id_list = list(dict.fromkeys(site_id_list))

    # 解析并校验省份 ID（仅允许 provinces 表中存在的整数 ID，防止拼接表名注入）
    prov_id_list: list = []
    if province_ids.strip():
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT id FROM provinces")
                valid_prov_ids = {r[0] for r in await cur.fetchall()}
        for part in province_ids.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                pid = int(part)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"非法的省份ID: {part}")
            if pid not in valid_prov_ids:
                raise HTTPException(status_code=400, detail=f"省份不存在: id={pid}")
            prov_id_list.append(pid)
        prov_id_list = list(dict.fromkeys(prov_id_list))

    # 来源站点筛选条件：WHERE site_id IN (...)
    site_filter = ""
    if site_id_list:
        site_ph = ",".join(["%s"] * len(site_id_list))
        site_filter = f" AND bids.site_id IN ({site_ph})"

    # 订阅词筛选条件：UNION 各订阅词子表（UNION 天然去重，避免重复记录）
    sub_filter = ""
    if kw_id_list:
        unions = " UNION ".join(f"SELECT bid_id FROM sub_{kid}" for kid in kw_id_list)
        sub_filter = f" AND bids.id IN ({unions})"

    # 省份筛选条件：UNION 各省份索引表
    prov_filter = ""
    if prov_id_list:
        unions = " UNION ".join(f"SELECT bid_id FROM province_{pid}" for pid in prov_id_list)
        prov_filter = f" AND bids.id IN ({unions})"

    # 城市筛选条件：直接 WHERE service_city（参数化，防注入）
    city_filter = ""
    city_param = None
    if city.strip():
        city_filter = " AND bids.service_city = %s"
        city_param = city.strip()

    # 预算范围筛选
    budget_filter = ""
    budget_params: list = []
    if budget_min is not None:
        budget_filter += " AND bids.budget >= %s"
        budget_params.append(budget_min)
    if budget_max is not None:
        budget_filter += " AND bids.budget <= %s"
        budget_params.append(budget_max)

    # 发布时间范围筛选
    publish_filter = ""
    publish_params: list = []
    if publish_date_from.strip():
        publish_filter += " AND bids.publish_date >= %s"
        publish_params.append(publish_date_from.strip())
    if publish_date_to.strip():
        publish_filter += " AND bids.publish_date <= %s"
        publish_params.append(publish_date_to.strip())

    # 招标时间范围筛选
    bid_filter = ""
    bid_params: list = []
    if bid_date_from.strip():
        bid_filter += " AND bids.bid_date >= %s"
        bid_params.append(bid_date_from.strip())
    if bid_date_to.strip():
        bid_filter += " AND bids.bid_date <= %s"
        bid_params.append(bid_date_to.strip())

    # 组装查询参数（COUNT 与分页查询共用）
    base_params: list = [category]
    base_params += site_id_list
    if city_param is not None:
        base_params.append(city_param)
    base_params += budget_params + publish_params + bid_params

    # LEFT JOIN sites：来源名称实时取 sites 表（改名即生效），站点已删除时回退到 bids.source
    join_clause = "FROM bids LEFT JOIN sites ON bids.site_id = sites.id"
    all_filters = f"{site_filter}{sub_filter}{prov_filter}{city_filter}{budget_filter}{publish_filter}{bid_filter}"

    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # 查询总数
            await cur.execute(
                f"SELECT COUNT(*) {join_clause} WHERE bids.notice_type = %s{all_filters}",
                tuple(base_params),
            )
            total = (await cur.fetchone())[0]

            # 分页查询
            offset = (page - 1) * page_size
            await cur.execute(f"""
                SELECT bids.id, COALESCE(sites.name, bids.source), bids.scrape_time, bids.url,
                       bids.content, bids.title, bids.notice_type,
                       bids.publish_time, bids.bid_time, bids.summary, bids.keywords, bids.budget,
                       bids.purchaser, bids.purchaser_region, bids.service_category,
                       bids.service_province, bids.service_city, bids.service_location,
                       bids.remarks, bids.created_at, bids.site_id
                {join_clause}
                WHERE bids.notice_type = %s{all_filters}
                ORDER BY bids.created_at DESC
                LIMIT %s OFFSET %s
            """, tuple(base_params + [page_size, offset]))
            rows = await cur.fetchall()

    # 计算本页每条标书命中的订阅词（用于前端灯泡展示）
    matched_map = await _build_matched_keywords([r[0] for r in rows])

    records = []
    for row in rows:
        # keywords 字段是 JSON 字符串，解析为列表
        kw_raw = row[10]
        if kw_raw:
            try:
                kw_list = json.loads(kw_raw) if isinstance(kw_raw, str) else kw_raw
            except (json.JSONDecodeError, TypeError):
                kw_list = []
        else:
            kw_list = []

        records.append({
            "id": row[0],
            "source": row[1],
            "scrape_time": row[2],
            "url": row[3],
            "content": row[4],
            "title": row[5],
            "notice_type": row[6],
            "publish_time": row[7],
            "bid_time": row[8],
            "summary": row[9],
            "keywords": kw_list,
            "budget": row[11],
            "purchaser": row[12],
            "purchaser_region": row[13],
            "service_category": row[14],
            "service_province": row[15],
            "service_city": row[16],
            "service_location": row[17],
            "remarks": row[18],
            "site_id": row[20],
            "matched_keywords": matched_map.get(row[0], []),
        })

    return {
        "category": category,
        "totalRecords": total,
        "page": page,
        "pageSize": page_size,
        "records": records,
    }
