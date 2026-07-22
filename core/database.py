"""数据库连接池管理"""

import os
from datetime import date, timedelta

import aiomysql

# 确保环境变量已加载
import config.settings  # noqa: F401

_pool: aiomysql.Pool | None = None


async def init_db():
    """初始化数据库连接池"""
    global _pool
    _pool = await aiomysql.create_pool(
        host=os.environ.get("DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("DB_PORT", "3306")),
        user=os.environ.get("DB_USER", "app_user"),
        password=os.environ.get("DB_PASSWORD", "app_pass123"),
        db=os.environ.get("DB_NAME", "ai_yuangong"),
        charset="utf8mb4",
        autocommit=True,
        minsize=2,
        maxsize=10,
        init_command="SET time_zone = '+08:00'",
    )


async def get_pool() -> aiomysql.Pool:
    """获取连接池"""
    if _pool is None:
        await init_db()
    return _pool


async def close_db():
    """关闭连接池"""
    global _pool
    if _pool:
        _pool.close()
        await _pool.wait_closed()
        _pool = None


def get_yesterday_str() -> str:
    """获取昨天的日期字符串，格式: YYYY-MM-DD"""
    return (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
