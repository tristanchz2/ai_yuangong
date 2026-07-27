#!/usr/bin/env python3
"""数据库配置导出/导入工具

用法:
  # 从当前数据库导出配置（sites + keywords）到 JSON 文件
  python scripts/db_migrate.py export [--output config_backup.json]

  # 从 JSON 文件导入配置到当前数据库
  python scripts/db_migrate.py import [--input config_backup.json]

  # 查看导出文件内容（不写入数据库）
  python scripts/db_migrate.py show [--input config_backup.json]
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 加载 .env
import config.settings  # noqa: F401


async def export_config(output_path: str):
    """导出 sites + keywords 到 JSON 文件"""
    import aiomysql
    from core.database import get_pool, init_db, close_db

    await init_db()
    pool = await get_pool()

    data = {"sites": [], "keywords": []}

    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # 导出 sites
            await cur.execute(
                "SELECT id, name, url, scraper_name, description, status, hidden, aliases, has_attachment "
                "FROM sites ORDER BY id"
            )
            for row in await cur.fetchall():
                site = {
                    "id": row[0],
                    "name": row[1],
                    "url": row[2],
                    "scraper_name": row[3],
                    "description": row[4] or "",
                    "status": row[5] or "active",
                    "hidden": bool(row[6]),
                    "has_attachment": bool(row[8]) if len(row) > 8 else False,
                }
                # aliases 可能是 JSON 字符串或 dict（取决于驱动），统一转成列表
                aliases_raw = row[7]
                if aliases_raw:
                    if isinstance(aliases_raw, (list, dict)):
                        site["aliases"] = aliases_raw if isinstance(aliases_raw, list) else []
                    else:
                        try:
                            parsed = json.loads(aliases_raw)
                            site["aliases"] = parsed if isinstance(parsed, list) else []
                        except (json.JSONDecodeError, TypeError):
                            site["aliases"] = []
                else:
                    site["aliases"] = []
                data["sites"].append(site)

            # 导出 keywords
            await cur.execute("SELECT id, word FROM keywords ORDER BY id")
            for row in await cur.fetchall():
                data["keywords"].append({
                    "id": row[0],
                    "word": row[1],
                })

    await close_db()

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"✓ 导出完成: {output_path}")
    print(f"  - sites: {len(data['sites'])} 条")
    print(f"  - keywords: {len(data['keywords'])} 条")


async def import_config(input_path: str):
    """从 JSON 文件导入配置到数据库"""
    import aiomysql
    from core.database import init_db, close_db, get_pool

    if not Path(input_path).exists():
        print(f"✗ 文件不存在: {input_path}")
        sys.exit(1)

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    await init_db()
    pool = await get_pool()

    # 导入 sites
    sites = data.get("sites", [])
    if sites:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                # 确保表存在
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

                inserted = 0
                updated = 0
                for s in sites:
                    aliases_json = json.dumps(s.get("aliases", []), ensure_ascii=False) if s.get("aliases") else None
                    try:
                        # 先尝试按 id 更新
                        await cur.execute(
                            "SELECT id FROM sites WHERE id = %s", (s["id"],)
                        )
                        exists = await cur.fetchone()
                        if exists:
                            await cur.execute(
                                """UPDATE sites SET name=%s, url=%s, scraper_name=%s,
                                   description=%s, aliases=%s, status=%s, hidden=%s
                                   WHERE id=%s""",
                                (
                                    s["name"], s["url"], s.get("scraper_name"),
                                    s.get("description", ""), aliases_json,
                                    s.get("status", "active"),
                                    1 if s.get("hidden") else 0,
                                    s["id"],
                                )
                            )
                            updated += 1
                        else:
                            await cur.execute(
                                """INSERT INTO sites (id, name, url, scraper_name, description, aliases, status, hidden)
                                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                                (
                                    s["id"], s["name"], s["url"], s.get("scraper_name"),
                                    s.get("description", ""), aliases_json,
                                    s.get("status", "active"),
                                    1 if s.get("hidden") else 0,
                                )
                            )
                            inserted += 1
                    except Exception as e:
                        print(f"  ⚠ 跳过 site {s.get('name', '?')}: {e}")

        print(f"✓ sites: 插入 {inserted} 条, 更新 {updated} 条")

    # 导入 keywords
    keywords = data.get("keywords", [])
    if keywords:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                # 确保表存在
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

                inserted = 0
                skipped = 0
                for k in keywords:
                    try:
                        # 检查是否已存在（按 word 去重）
                        await cur.execute(
                            "SELECT id FROM keywords WHERE word = %s", (k["word"],)
                        )
                        if await cur.fetchone():
                            skipped += 1
                            continue
                        await cur.execute(
                            "INSERT INTO keywords (id, word) VALUES (%s, %s)",
                            (k["id"], k["word"])
                        )
                        inserted += 1
                    except Exception as e:
                        print(f"  ⚠ 跳过 keyword {k.get('word', '?')}: {e}")
                        skipped += 1

        print(f"✓ keywords: 插入 {inserted} 条, 跳过 {skipped} 条")

        # 为新增的 keywords 创建订阅子表
        from services.subscription import ensure_all_subscription_tables
        await ensure_all_subscription_tables()

    await close_db()
    print(f"\n✓ 导入完成!")


async def show_config(input_path: str):
    """显示导出文件的内容"""
    if not Path(input_path).exists():
        print(f"✗ 文件不存在: {input_path}")
        sys.exit(1)

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    sites = data.get("sites", [])
    keywords = data.get("keywords", [])

    print(f"=== Sites ({len(sites)} 条) ===")
    for s in sites:
        hidden_mark = " [隐藏]" if s.get("hidden") else ""
        scraper = s.get("scraper_name") or "(无爬虫)"
        print(f"  [{s['id']}] {s['name']}{hidden_mark}")
        print(f"      URL: {s['url']}")
        print(f"      爬虫: {scraper}")
        if s.get("description"):
            print(f"      描述: {s['description']}")
        if s.get("aliases"):
            print(f"      别名: {', '.join(s['aliases'])}")
        print()

    print(f"=== Keywords ({len(keywords)} 条) ===")
    for k in keywords:
        print(f"  [{k['id']}] {k['word']}")


def main():
    parser = argparse.ArgumentParser(description="数据库配置导出/导入工具")
    parser.add_argument("action", choices=["export", "import", "show"],
                        help="操作: export(导出), import(导入), show(查看)")
    parser.add_argument("--output", "-o", default="config_backup.json",
                        help="导出文件路径 (默认: config_backup.json)")
    parser.add_argument("--input", "-i", default="config_backup.json",
                        help="导入文件路径 (默认: config_backup.json)")

    args = parser.parse_args()

    if args.action == "export":
        asyncio.run(export_config(args.output))
    elif args.action == "import":
        asyncio.run(import_config(args.input))
    elif args.action == "show":
        asyncio.run(show_config(args.input))


if __name__ == "__main__":
    main()
