"""数据展示路由 - 从数据库读取标书数据"""

import json

from fastapi import APIRouter, HTTPException, Query

from db import get_pool

router = APIRouter(prefix="/api", tags=["数据展示"])

DATA_CATEGORIES = ["采购公告", "结果公告", "其他"]


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


@router.get("/data/{category}")
async def get_category_data(
    category: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
):
    """从 DB 读取指定分类的标书数据（支持分页）"""
    if category not in DATA_CATEGORIES:
        raise HTTPException(status_code=404, detail=f"分类不存在: {category}")

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # 查询总数
            await cur.execute(
                "SELECT COUNT(*) FROM bids WHERE notice_type = %s", (category,)
            )
            total = (await cur.fetchone())[0]

            # 分页查询
            offset = (page - 1) * page_size
            await cur.execute("""
                SELECT id, source, scrape_time, url, content, title, notice_type,
                       publish_time, bid_time, summary, keywords, budget,
                       purchaser, purchaser_region, service_category,
                       service_province, service_location, remarks, created_at
                FROM bids
                WHERE notice_type = %s
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
            """, (category, page_size, offset))
            rows = await cur.fetchall()

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
            "service_location": row[16],
            "remarks": row[17],
        })

    return {
        "category": category,
        "totalRecords": total,
        "page": page,
        "pageSize": page_size,
        "records": records,
    }
