#!/usr/bin/env python3
"""诊断 sub_{id} 表里的 bid_id 是否在 bids 表中存在"""

import asyncio
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
    print("📌 检查 sub_{id} 表里的 bid_id 是否在 bids 表中存在")
    print("=" * 60)

    # 获取所有订阅词
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id, word FROM keywords ORDER BY id")
            keywords = await cur.fetchall()

    if not keywords:
        print("  ❌ keywords 表为空")
        await close_db()
        return

    all_orphan_count = 0
    all_valid_count = 0

    for kid, word in keywords:
        table_name = f"sub_{kid}"
        
        # 检查子表是否存在
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SHOW TABLES")
                all_tables = {r[0] for r in await cur.fetchall()}
        
        if table_name not in all_tables:
            print(f"\n  ❌ {table_name} (订阅词: {word}) - 子表不存在")
            continue

        # 查询子表里的 bid_id
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(f"SELECT bid_id FROM `{table_name}`")
                sub_bid_ids = [r[0] for r in await cur.fetchall()]

        if not sub_bid_ids:
            print(f"\n  ⚠️ {table_name} (订阅词: {word}) - 子表为空")
            continue

        # 查询这些 bid_id 在 bids 表中是否存在
        placeholders = ",".join(["%s"] * len(sub_bid_ids))
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    f"SELECT id FROM bids WHERE id IN ({placeholders})",
                    tuple(sub_bid_ids)
                )
                valid_bid_ids = {r[0] for r in await cur.fetchall()}

        orphan_ids = [bid for bid in sub_bid_ids if bid not in valid_bid_ids]
        valid_count = len(sub_bid_ids) - len(orphan_ids)
        
        all_valid_count += valid_count
        all_orphan_count += len(orphan_ids)

        print(f"\n  📊 {table_name} (订阅词: {word})")
        print(f"     子表共 {len(sub_bid_ids)} 条")
        print(f"     ✅ 有效: {valid_count} 条")
        if orphan_ids:
            print(f"     ❌ 孤儿 (bids 表不存在): {len(orphan_ids)} 条")
            print(f"        孤儿 ID 示例: {orphan_ids[:5]}...")

    print("\n" + "=" * 60)
    print("📌 汇总")
    print("=" * 60)
    print(f"  有效记录: {all_valid_count} 条")
    print(f"  孤儿记录: {all_orphan_count} 条")
    
    if all_orphan_count > 0:
        print("\n  ⚠️ 发现问题：sub 表里有 bid_id 在 bids 表中不存在！")
        print("  → 原因可能是并发插入时 MAX(id) 回退查询返回了错误的 ID")
        print("  → 解决方案：修复 insert_bid 的 ID 获取逻辑")
    elif all_valid_count > 0:
        print("\n  ✅ 所有 sub 表数据都有效")
        print("  → 如果前端仍不显示灯泡，请检查前端代码")
    else:
        print("\n  ⚠️ 没有任何有效数据")

    await close_db()


if __name__ == "__main__":
    asyncio.run(main())
