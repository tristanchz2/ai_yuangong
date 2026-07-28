#!/usr/bin/env python3
"""诊断订阅词系统状态"""

import asyncio
import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(_PROJECT_ROOT / ".env")

from core.database import init_db, close_db, get_pool


async def main():
    await init_db()
    pool = await get_pool()

    print("=" * 60)
    print("📌 1. keywords 表内容")
    print("=" * 60)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id, word FROM keywords ORDER BY id")
            rows = await cur.fetchall()
    if not rows:
        print("  ❌ keywords 表为空！没有订阅词")
        await close_db()
        return
    keywords = [(r[0], r[1]) for r in rows]
    for kid, word in keywords:
        print(f"  id={kid}, word='{word}'")

    print()
    print("=" * 60)
    print("📌 2. sub_{id} 子表是否存在")
    print("=" * 60)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SHOW TABLES")
            all_tables = {r[0] for r in await cur.fetchall()}
    for kid, word in keywords:
        table_name = f"sub_{kid}"
        exists = table_name in all_tables
        if exists:
            # 查数据量
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(f"SELECT COUNT(*) FROM `{table_name}`")
                    cnt = (await cur.fetchone())[0]
            print(f"  ✅ {table_name} 存在, 共 {cnt} 条记录")
        else:
            print(f"  ❌ {table_name} 不存在！（订阅词 '{word}' 从未匹配过任何数据）")

    print()
    print("=" * 60)
    print("📌 3. bids 表最近 5 条数据")
    print("=" * 60)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT COUNT(*) FROM bids")
            total = (await cur.fetchone())[0]
    print(f"  bids 表共 {total} 条记录")
    if total > 0:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT id, title, notice_type, publish_date FROM bids ORDER BY created_at DESC LIMIT 5"
                )
                rows = await cur.fetchall()
        for r in rows:
            print(f"  id={r[0]}, title='{(r[1] or '')[:40]}', type={r[2]}, date={r[3]}")

    print()
    print("=" * 60)
    print("📌 4. 诊断结论")
    print("=" * 60)
    has_sub_data = False
    for kid, word in keywords:
        table_name = f"sub_{kid}"
        if table_name in all_tables:
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(f"SELECT COUNT(*) FROM `{table_name}`")
                    cnt = (await cur.fetchone())[0]
            if cnt > 0:
                has_sub_data = True

    if total == 0:
        print("  ⚠️ bids 表为空，没有数据可匹配")
    elif not has_sub_data:
        print("  ⚠️ 所有 sub 子表要么不存在，要么为空")
        print("  → 说明 LLM 从未成功匹配过任何订阅词")
        print("  → 可能原因: LLM 返回的 subscription_matches 的 key 与原始订阅词不一致")
        print("  → 建议: 跑一次爬虫，查看日志中是否有 '⚠️ LLM 返回的订阅词 key 不匹配' 的警告")
    else:
        print("  ✅ 订阅词系统正常工作，有匹配数据")

    await close_db()


if __name__ == "__main__":
    asyncio.run(main())
