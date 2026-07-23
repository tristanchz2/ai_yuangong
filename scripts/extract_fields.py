#!/usr/bin/env python3
"""
公告字段提取器 - 使用 LLM JSON Schema 模式从 raw_data 中提取结构化字段

用法：
  python scripts/extract_fields.py                    # 处理所有 raw_data 文件
  python scripts/extract_fields.py --source ccb       # 只处理 ccb_data.json
  python scripts/extract_fields.py --source icbc,ccgp # 处理多个源
  python scripts/extract_fields.py --concurrency 3    # 设置并发数
  python scripts/extract_fields.py --batch-size 5     # 每次 LLM 调用处理的条数

输出：写入 MySQL bids 表（前端唯一数据源）
"""

import asyncio
import json
import sys
import glob
import argparse
import time
from pathlib import Path

# 确保项目根目录在 sys.path 中（支持从任意位置运行）
_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv

from config.settings import PROJECT_ROOT, RAW_DATA_DIR
from config.constants import DEFAULT_CONCURRENCY, BATCH_SIZE
from core.database import init_db, close_db, get_yesterday_str
from core.utils import parse_date_str
from services.region import parse_service_region
from services.subscription import get_all_subscription_keywords, ensure_subscription_table, insert_bid_subscription
from services.province_index import get_all_provinces, insert_bid_province
from services.scrape_index import ensure_scrape_idx_table, insert_scrape_idx
from services.bid_repo import (
    insert_bid, get_scraper_to_site_id_map, get_site_id_to_name_map, delete_bids_by_source_date
)
from services.llm_extractor import (
    get_client, process_file, is_cancelled, set_cancel_file
)

# 加载环境变量
load_dotenv(PROJECT_ROOT / ".env")


async def async_main():
    parser = argparse.ArgumentParser(description="从 raw_data 中提取公告字段")
    parser.add_argument(
        "--source",
        type=str,
        default=None,
        help="指定要处理的源名称（逗号分隔），如 ccb,icbc。不指定则处理所有文件。",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="输出文件名（默认: extracted_all.json）",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=DEFAULT_CONCURRENCY,
        help=f"并发数（默认 {DEFAULT_CONCURRENCY}）",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=BATCH_SIZE,
        help=f"每次 LLM 调用处理的公告条数（默认 {BATCH_SIZE}）",
    )
    parser.add_argument(
        "--suffix",
        type=str,
        default=None,
        help="输出文件名后缀（如 abc_puc_1234），用于区分不同运行。不加后缀则按日期覆盖。",
    )
    parser.add_argument(
        "--cancel-file",
        type=str,
        default=None,
        help="取消信号文件路径。如果该文件存在，则跳过写入。",
    )
    args = parser.parse_args()

    # ★ 设置全局取消信号文件路径，供 is_cancelled() 检查
    if args.cancel_file:
        set_cancel_file(Path(args.cancel_file))

    # ★ 初始化数据库连接，获取订阅词列表
    await init_db()
    subscription_keywords = await get_all_subscription_keywords()  # [(id, word), ...]
    if subscription_keywords:
        print(f"📌 当前订阅词({len(subscription_keywords)}个): {', '.join(w for _, w in subscription_keywords)}")
        # 确保所有订阅词子表存在
        for kid, _ in subscription_keywords:
            await ensure_subscription_table(kid)
    else:
        print("📌 当前无订阅词")

    # 确定要处理的文件
    if args.source:
        sources = [s.strip() for s in args.source.split(",")]
        files = []
        for src in sources:
            pattern = RAW_DATA_DIR / f"{src}_data.json"
            matched = glob.glob(str(pattern))
            if matched:
                files.append(Path(matched[0]))
            else:
                print(f"⚠️  未找到匹配文件: {pattern}")
    else:
        files = sorted(RAW_DATA_DIR.glob("*_data.json"))

    if not files:
        print("❌ 没有要处理的文件")
        await close_db()
        return

    # 统计总条目数
    total_items = 0
    for fp in files:
        with open(fp) as f:
            d = json.load(f)
            total_items += len(d.get("rows", []))

    print(f"🚀 共 {len(files)} 个文件, {total_items} 条记录待处理")
    print(f"⚡ 并发数: {args.concurrency}, 批次大小: {args.batch_size}")

    client = get_client()
    semaphore = asyncio.Semaphore(args.concurrency)

    start_time = time.time()

    # 所有文件的所有条目并发处理（跨文件也并发）
    all_file_coros = [
        process_file(client, fp, semaphore, batch_size=args.batch_size, subscription_keywords=subscription_keywords)
        for fp in files
    ]
    all_file_results = await asyncio.gather(*all_file_coros)

    # ★ LLM 完成后立即检查取消信号，避免已取消的任务还写入数据
    if is_cancelled():
        print(f"\n🛑 LLM 提取完成后检测到取消信号，跳过数据写入")
        await close_db()
        return

    all_results = []
    for results in all_file_results:
        all_results.extend(results)

    elapsed = time.time() - start_time

    # ★ 统一 source 名称：建立 爬虫原始source文字 → sites表名称 的映射，并改写每条记录的 source 字段
    #   让分组输出目录、extracted JSON、DB 写入的来源名全部以 sites 表（site_id）为准
    source_to_scraper: dict = {}
    for fp in files:
        try:
            with open(fp, "r", encoding="utf-8") as f:
                d = json.load(f)
            raw_source = d.get("source", "")
            scraper = fp.stem[:-5] if fp.stem.endswith("_data") else fp.stem
            if raw_source:
                source_to_scraper[raw_source] = scraper
        except Exception:
            pass
    scraper_to_site_id = await get_scraper_to_site_id_map()
    site_id_to_name = await get_site_id_to_name_map()
    site_name_to_id = {name: sid for sid, name in site_id_to_name.items()}
    source_to_site_name: dict = {}
    for raw_src, scraper in source_to_scraper.items():
        sid = scraper_to_site_id.get(scraper)
        if sid and sid in site_id_to_name:
            source_to_site_name[raw_src] = site_id_to_name[sid]
    for r in all_results:
        raw_src = r.get("source", "")
        if raw_src in source_to_site_name:
            r["source"] = source_to_site_name[raw_src]

    # ★ 写入数据库：将每条标书存入 bids 表 + 订阅词子表 + 爬取索引表
    db_saved = 0
    if all_results and not is_cancelled():
        print(f"\n💾 开始写入数据库...")
        # 确保爬取索引表存在
        yesterday = get_yesterday_str()
        ensured_site_ids: set = set()
        for r in all_results:
            src_name = r.get("source", "")
            sid = site_name_to_id.get(src_name)
            if sid is None:
                sid = scraper_to_site_id.get(source_to_scraper.get(src_name, ""))
            if sid and sid not in ensured_site_ids:
                await ensure_scrape_idx_table(sid, yesterday)
                ensured_site_ids.add(sid)
        # ★ 入库前清理旧数据
        for sid in ensured_site_ids:
            try:
                deleted = await delete_bids_by_source_date(sid, yesterday)
                if deleted > 0:
                    print(f"🗑️ 已清理旧数据: site_id={sid} ({yesterday}) 共 {deleted} 条")
            except Exception as e:
                print(f"⚠️ 清理旧数据失败 (site_id={sid}): {e}")
        # 构建订阅词 word -> id 的映射
        sub_word_to_id = {word: kid for kid, word in subscription_keywords}
        # 构建省份 name -> id 的映射
        province_name_to_id = {name: pid for pid, name in await get_all_provinces()}
        for r in all_results:
            if is_cancelled():
                print(f"🛑 检测到取消信号，停止 DB 写入（已写入 {db_saved} 条）")
                break
            try:
                sub_matches = r.pop("subscription_matches", None) or {}
                keywords_list = r.get("keywords") or []
                keywords_json = json.dumps(keywords_list, ensure_ascii=False) if keywords_list else None
                service_province, service_city = parse_service_region(r.get("service_region"))
                src_name = r.get("source", "")
                site_id = site_name_to_id.get(src_name)
                if site_id is None:
                    site_id = scraper_to_site_id.get(source_to_scraper.get(src_name, ""))
                bid_data = {
                    "site_id": site_id,
                    "source": r.get("source"),
                    "scrape_time": r.get("scrape_time"),
                    "url": r.get("url"),
                    "content": r.get("content"),
                    "title": r.get("title"),
                    "notice_type": r.get("notice_type"),
                    "publish_time": r.get("publish_time"),
                    "publish_date": parse_date_str(r.get("publish_time")),
                    "bid_time": r.get("bid_time"),
                    "bid_date": parse_date_str(r.get("bid_time")),
                    "summary": r.get("summary"),
                    "keywords_json": keywords_json,
                    "budget": r.get("budget"),
                    "purchaser": r.get("purchaser"),
                    "purchaser_region": r.get("purchaser_region"),
                    "service_category": r.get("service_category"),
                    "service_province": service_province,
                    "service_city": service_city,
                    "service_location": r.get("service_location"),
                    "remarks": r.get("remarks"),
                }
                bid_id = await insert_bid(bid_data)
                if site_id:
                    await insert_scrape_idx(site_id, yesterday, bid_id)
                if service_province and service_province in province_name_to_id:
                    await insert_bid_province(bid_id, province_name_to_id[service_province])
                if sub_matches and isinstance(sub_matches, dict):
                    for word, matched in sub_matches.items():
                        if matched == 1 and word in sub_word_to_id:
                            await insert_bid_subscription(bid_id, sub_word_to_id[word])
                db_saved += 1
            except Exception as e:
                print(f"  ❌ DB 写入失败 (标题: {r.get('title', 'N/A')[:20]}): {e}")
        print(f"💾 数据库写入完成，共 {db_saved} 条")

    print(f"\n✅ 提取完成！数据库共写入 {db_saved} 条记录")
    print(f"⏱️  耗时: {elapsed:.1f}s")

    # 关闭数据库连接
    await close_db()


if __name__ == "__main__":
    asyncio.run(async_main())
