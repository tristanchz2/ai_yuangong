#!/usr/bin/env python3
"""数据库配置导出/导入工具（独立版，无项目依赖）

只依赖 pymysql，支持 Python 3.6+。

用法:
  # 安装 pymysql（如果没有）
  pip3 install pymysql --user

  # 从当前数据库导出配置（sites + keywords）到 JSON 文件
  python3 scripts/db_migrate_standalone.py export [--output config_backup.json]

  # 从 JSON 文件导入配置到当前数据库
  python3 scripts/db_migrate_standalone.py import [--input config_backup.json]

  # 查看导出文件内容（不写入数据库）
  python3 scripts/db_migrate_standalone.py show [--input config_backup.json]
"""

import argparse
import json
import os
import sys
from pathlib import Path


def load_env(project_root: Path):
    """从 .env 文件加载环境变量"""
    env_path = project_root / ".env"
    if not env_path.exists():
        return
    with open(env_path, "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                # 去除行内注释
                if " #" in val:
                    val = val[: val.index(" #")]
                os.environ.setdefault(key.strip(), val.strip())


def get_db_config():
    """从环境变量获取数据库配置"""
    return {
        "host": os.environ.get("DB_HOST", "127.0.0.1"),
        "port": int(os.environ.get("DB_PORT", "3306")),
        "user": os.environ.get("DB_USER", "app_user"),
        "password": os.environ.get("DB_PASSWORD", "app_pass123"),
        "database": os.environ.get("DB_NAME", "ai_yuangong"),
        "charset": "utf8mb4",
    }


def get_connection():
    """获取数据库连接"""
    import pymysql
    config = get_db_config()
    return pymysql.connect(**config)


def export_config(output_path: str):
    """导出 sites + keywords 到 JSON 文件"""
    conn = get_connection()
    try:
        data = {"sites": [], "keywords": []}

        with conn.cursor() as cur:
            # 导出 sites
            cur.execute(
                "SELECT id, name, url, scraper_name, description, status, hidden, aliases "
                "FROM sites ORDER BY id"
            )
            for row in cur.fetchall():
                site = {
                    "id": row[0],
                    "name": row[1],
                    "url": row[2],
                    "scraper_name": row[3],
                    "description": row[4] or "",
                    "status": row[5] or "active",
                    "hidden": bool(row[6]),
                }
                # aliases 可能是 JSON 字符串或 bytes
                aliases_raw = row[7]
                if aliases_raw:
                    if isinstance(aliases_raw, bytes):
                        aliases_raw = aliases_raw.decode("utf-8")
                    if isinstance(aliases_raw, str):
                        try:
                            parsed = json.loads(aliases_raw)
                            site["aliases"] = parsed if isinstance(parsed, list) else []
                        except (json.JSONDecodeError, TypeError):
                            site["aliases"] = []
                    elif isinstance(aliases_raw, list):
                        site["aliases"] = aliases_raw
                    else:
                        site["aliases"] = []
                else:
                    site["aliases"] = []
                data["sites"].append(site)

            # 导出 keywords
            cur.execute("SELECT id, word FROM keywords ORDER BY id")
            for row in cur.fetchall():
                data["keywords"].append({
                    "id": row[0],
                    "word": row[1],
                })

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        print(f"✓ 导出完成: {output_path}")
        print(f"  - sites: {len(data['sites'])} 条")
        print(f"  - keywords: {len(data['keywords'])} 条")
    finally:
        conn.close()


def import_config(input_path: str):
    """从 JSON 文件导入配置到数据库"""
    if not Path(input_path).exists():
        print(f"✗ 文件不存在: {input_path}")
        sys.exit(1)

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # 导入 sites
            sites = data.get("sites", [])
            if sites:
                # 确保表存在（Doris 语法）
                cur.execute("""
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
                        cur.execute("SELECT id FROM sites WHERE id = %s", (s["id"],))
                        exists = cur.fetchone()
                        if exists:
                            cur.execute(
                                """UPDATE sites SET name=%s, url=%s, scraper_name=%s,
                                   description=%s, aliases=%s, status=%s, hidden=%s
                                   WHERE id=%s""",
                                (
                                    s["name"], s["url"], s.get("scraper_name"),
                                    s.get("description", ""), aliases_json,
                                    s.get("status", "active"),
                                    1 if s.get("hidden") else 0,
                                    s["id"],
                                ),
                            )
                            updated += 1
                        else:
                            cur.execute(
                                """INSERT INTO sites (id, name, url, scraper_name, description, aliases, status, hidden)
                                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                                (
                                    s["id"], s["name"], s["url"], s.get("scraper_name"),
                                    s.get("description", ""), aliases_json,
                                    s.get("status", "active"),
                                    1 if s.get("hidden") else 0,
                                ),
                            )
                            inserted += 1
                    except Exception as e:
                        print(f"  ⚠ 跳过 site {s.get('name', '?')}: {e}")

                print(f"✓ sites: 插入 {inserted} 条, 更新 {updated} 条")

            # 导入 keywords
            keywords = data.get("keywords", [])
            if keywords:
                cur.execute("""
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
                        cur.execute("SELECT id FROM keywords WHERE word = %s", (k["word"],))
                        if cur.fetchone():
                            skipped += 1
                            continue
                        cur.execute(
                            "INSERT INTO keywords (id, word) VALUES (%s, %s)",
                            (k["id"], k["word"]),
                        )
                        inserted += 1
                    except Exception as e:
                        print(f"  ⚠ 跳过 keyword {k.get('word', '?')}: {e}")
                        skipped += 1

                print(f"✓ keywords: 插入 {inserted} 条, 跳过 {skipped} 条")

        conn.commit()
        print(f"\n✓ 导入完成!")
    finally:
        conn.close()


def show_config(input_path: str):
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
    # 找到项目根目录（脚本在 scripts/ 下）
    project_root = Path(__file__).resolve().parent.parent
    load_env(project_root)

    parser = argparse.ArgumentParser(description="数据库配置导出/导入工具")
    parser.add_argument(
        "action", choices=["export", "import", "show"],
        help="操作: export(导出), import(导入), show(查看)"
    )
    parser.add_argument("--output", "-o", default="config_backup.json", help="导出文件路径")
    parser.add_argument("--input", "-i", default="config_backup.json", help="导入文件路径")

    args = parser.parse_args()

    if args.action == "export":
        export_config(args.output)
    elif args.action == "import":
        import_config(args.input)
    elif args.action == "show":
        show_config(args.input)


if __name__ == "__main__":
    main()
