#!/usr/bin/env python3
"""一次性迁移脚本：将 sites.json 数据导入 MySQL sites 表"""

import asyncio
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

# 加载 .env
env_path = PROJECT_ROOT / ".env"
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, val = line.split('=', 1)
                os.environ.setdefault(key.strip(), val.strip())

import aiomysql

SITES_FILE = PROJECT_ROOT / "sites.json"


async def migrate():
    if not SITES_FILE.exists():
        print("sites.json 不存在，无需迁移")
        return

    with open(SITES_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    sites = data.get("sites", [])

    if not sites:
        print("sites.json 中没有站点数据")
        return

    pool = await aiomysql.create_pool(
        host=os.environ.get("DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("DB_PORT", "3306")),
        user=os.environ.get("DB_USER", "app_user"),
        password=os.environ.get("DB_PASSWORD", "app_pass123"),
        db=os.environ.get("DB_NAME", "ai_yuangong"),
        charset="utf8mb4",
        autocommit=True,
    )

    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # 建表
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS sites (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    name VARCHAR(200) NOT NULL,
                    url VARCHAR(500) NOT NULL UNIQUE,
                    scraper_name VARCHAR(100) DEFAULT NULL,
                    description VARCHAR(500) DEFAULT '',
                    status VARCHAR(20) DEFAULT 'active',
                    hidden TINYINT(1) DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)

            inserted = 0
            skipped = 0
            for s in sites:
                try:
                    await cur.execute(
                        """INSERT INTO sites (id, name, url, scraper_name, description, status, hidden)
                           VALUES (%s, %s, %s, %s, %s, %s, %s)
                           ON DUPLICATE KEY UPDATE id=id""",
                        (
                            s["id"],
                            s["name"],
                            s["url"],
                            s.get("scraper_name"),
                            s.get("description", ""),
                            s.get("status", "active"),
                            1 if s.get("hidden") else 0,
                        )
                    )
                    if cur.rowcount > 0:
                        inserted += 1
                    else:
                        skipped += 1
                except Exception as e:
                    print(f"  跳过 {s['name']}: {e}")
                    skipped += 1

            print(f"迁移完成: 插入 {inserted} 条, 跳过 {skipped} 条")

    pool.close()
    await pool.wait_closed()


if __name__ == "__main__":
    asyncio.run(migrate())
