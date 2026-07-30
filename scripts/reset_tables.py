#!/usr/bin/env python3
"""重置数据库表：删除旧表后用新语法重建，并恢复 sites 数据"""

import asyncio
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 加载 .env
env_path = PROJECT_ROOT / ".env"
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, val = line.split('=', 1)
                if ' #' in val:
                    val = val[:val.index(' #')]
                os.environ.setdefault(key.strip(), val.strip())

import aiomysql

# 站点数据（硬编码，reset 时直接写入）
SITES_DATA = [
    (1, '农银e采', 'https://jc.abchina.com.cn/puc/', 'abc_puc', '中国农业银行采购平台', '["\u4e2d\u56fd\u519c\u4e1a\u94f6\u884c"]', 'active', 0),
    (2, '中银采购', 'https://purchasing.bankofchina.com/', 'boc_pcm', '中国银行采购平台', '["\u4e2d\u56fd\u94f6\u884c"]', 'active', 0),
    (3, '中国建设银行', 'https://www.ccb.com/', 'ccb', '中国建设银行', '["\u4e2d\u56fd\u5efa\u8bbe\u94f6\u884c"]', 'active', 0),
    (4, '中国政府采购网', 'http://www.ccgp.gov.cn/', 'ccgp', '中国政府采购网', None, 'active', 1),
    (5, '国家开发银行', 'https://www.cdb.com.cn/', 'cdb', '国家开发银行', None, 'active', 1),
    (6, '金采网', 'http://www.cfcpn.com/', 'cfcpn', '金采网', None, 'active', 1),
    (7, '广发银行', 'https://www.cgbchina.com.cn/', 'cgbchina', '广发银行', None, 'active', 0),
    (8, '中国邮政储蓄银行', 'https://www.chinapost.com.cn/cn/category/1813/137338-1.htm', 'chinapost', '中国邮政', '["\u4e2d\u56fd\u90ae\u50a8\u94f6\u884c"]', 'active', 0),
    (9, '华夏银行', 'https://www.hxb.com.cn/', 'hxb', '华夏银行', None, 'active', 0),
    (10, '中国工商银行', 'https://www.icbc.com.cn/', 'icbc', '中国工商银行', '["\u5de5\u94f6\u96c6\u91c7"]', 'active', 0),
    (11, '中国渤海银行', 'https://www.cbhb.com.cn/', 'cbhb', '渤海银行', None, 'active', 0),
    (12, '平安银行慧采系统', 'https://ebank.pingan.com.cn/cr/eps-sppt-portal/index.html#/login', 'pingan', '', None, 'active', 0),
    (13, '兴业银行采购管理系统', 'https://cg.cib.com.cn/cms/default/webfile/gyszj/index.html', 'cib', '', None, 'active', 0),
    (14, '浙商银行数字采购系统', 'https://ccgp.szcgpt.czbank.com/luban/category?parentId=700835&childrenCode=134-848230', 'czbank', '', None, 'active', 0),
    (15, '中国光大银行', 'https://www.cebbank.com/site/zhpd/zxgg35/cggg/index.html', 'cebbank', '中国光大银行采购公告', None, 'active', 0),
    (16, '中国民生银行', 'https://pms.cmbc.com.cn/purchase/listMore.html?categoryId=0205DC9E86F4C12C256094C8F271049D0289539534AEC561D051E4BB132055B0C181EF712D2717E0BCECBCF31010137B', 'cmbc', '', None, 'active', 0),
    (17, '浦发银行', 'https://ebuy.spdb.com.cn/#/notice', 'spdb', '浦东发展银行', None, 'active', 0),
    (18, '恒丰银行', 'https://www.hfbank.com.cn/gyhf/cgpt/jzcg/ygg/index.shtml', 'hfbank', '', None, 'active', 0),
    (19, '北京银行集中采购管理系统', 'https://login-cpm-xt.bankofbeijing.com.cn/cms/default/webfile/1ywgg1/index.html', 'bankofbeijing', '北京银行', None, 'active', 0),
    (20, '长沙银行', 'https://www.cscb.cn/site/col173/list.html', 'cscb', '', None, 'active', 1),  # 暂时不爬，hidden=1
    (21, '成都农商银行', 'https://www.cdrcb.com/cgnews/', 'cdrcb', '', None, 'active', 0),
]


async def reset_tables():
    pool = await aiomysql.create_pool(
        host=os.environ.get("DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("DB_PORT", "3306")),
        user=os.environ.get("DB_USER", "app_user"),
        password=os.environ.get("DB_PASSWORD", "app_pass123"),
        db=os.environ.get("DB_NAME", "ai_yuangong"),
        charset="utf8mb4",
        autocommit=True,
    )

    # 1. 获取所有表名
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = DATABASE()"
            )
            all_tables = [r[0] for r in await cur.fetchall()]

    # 2. 删除废弃的 scrape_idx_* 表
    print("🗑️  删除废弃的 scrape_idx 表...")
    for t in all_tables:
        if t.startswith("scrape_idx_"):
            async with pool.acquire() as c2:
                async with c2.cursor() as cur2:
                    await cur2.execute(f"DROP TABLE IF EXISTS `{t}`")
            print(f"   删除: {t}")

    # 3. 删除动态子表（sub_* / province_*）
    print("🗑️  删除动态索引子表...")
    for t in all_tables:
        if t.startswith("sub_") or t.startswith("province_"):
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(f"DROP TABLE IF EXISTS `{t}`")
            print(f"   删除: {t}")

    # 4. 删除主表
    for t in ["bids", "sites", "keywords", "provinces"]:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(f"DROP TABLE IF EXISTS `{t}`")
        print(f"   删除主表: {t}")

    # 5. 重建表
    print("🔨 重建表结构...")
    from core.schema import ensure_tables
    await ensure_tables()
    print("   表结构已重建")

    # 6. 恢复 sites 数据
    print(f"📥 恢复 sites 数据（共 {len(SITES_DATA)} 条）...")
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            for row in SITES_DATA:
                id_, name, url, scraper_name, description, aliases, status, hidden = row
                await cur.execute(
                    "INSERT INTO sites (id, name, url, scraper_name, description, aliases, status, hidden) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    (id_, name, url, scraper_name, description or '', aliases, status or 'active', hidden)
                )
    print(f"   已恢复 {len(SITES_DATA)} 条站点记录")

    pool.close()
    await pool.wait_closed()
    print("\n✅ 完成！表结构已更新，sites 数据已恢复")


if __name__ == "__main__":
    asyncio.run(reset_tables())

