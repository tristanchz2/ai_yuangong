"""定时任务调度器 - 每日自动爬取 + 推送"""

import asyncio
import os
import time
import logging
from datetime import date, timedelta

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from zoneinfo import ZoneInfo

from config.settings import PROJECT_ROOT
from core.database import get_pool
import services.site_repo as site_repo

logger = logging.getLogger("scheduler")

# 调度器实例（全局单例）
_scheduler: AsyncIOScheduler | None = None

# 定时任务记录（供前端历史任务界面显示）
scheduled_tasks: dict = {}
MAX_SCHEDULED_TASKS = 10


def get_scheduler() -> AsyncIOScheduler | None:
    """获取调度器（不自动创建）"""
    return _scheduler


def get_or_create_scheduler() -> AsyncIOScheduler:
    """获取或创建调度器（仅用于 start_scheduler）"""
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
    return _scheduler


async def daily_scrape_and_push():
    """
    每日定时任务：
    1. 批量爬取昨天数据（yesterday 模式）
    2. 等待爬取完成
    3. 推送匹配订阅词的采购公告到云之家
    """
    print(f"🕐 [{time.strftime('%Y-%m-%d %H:%M:%S')}] 定时任务 daily_scrape_and_push 被触发")
    # 立即创建任务记录，确保前端可见
    task_id = f"scheduled_{int(time.time() * 1000)}"
    scheduled_tasks[task_id] = {
        'task_id': task_id,
        'type': 'scheduled_scrape',
        'status': 'running',
        'description': '定时爬取+推送',
        'created_at': time.time(),
        'started_at': time.time(),
        'finished_at': None,
        'details': {'success_sites': 0, 'failed_sites': 0, 'pushed': 0},
        'job_id': 'daily_scrape_and_push',
    }
    if len(scheduled_tasks) > MAX_SCHEDULED_TASKS:
        oldest = min(scheduled_tasks, key=lambda k: scheduled_tasks[k]['created_at'])
        del scheduled_tasks[oldest]

    try:
        from services.batch_task import (
            create_batch_task,
            run_batch_scrape,
            get_latest_batch_task,
        )
        from services.subscription import get_all_subscription_keywords

        logger.info("=" * 50)
        logger.info("🕐 定时任务启动：开始爬取昨日数据")
        logger.info("=" * 50)

        # 检查是否有正在运行的批量任务
        existing = get_latest_batch_task()
        if existing and existing.status == "running":
            logger.warning("⚠️ 已有批量任务正在运行，跳过本次定时任务")
            scheduled_tasks[task_id]['status'] = 'skipped'
            scheduled_tasks[task_id]['finished_at'] = time.time()
            scheduled_tasks[task_id]['details']['error'] = '已有任务运行中'
            return

        # 获取所有可见站点
        active_sites = await site_repo.list_sites(include_hidden=False)
        if not active_sites:
            logger.warning("⚠️ 没有可爬取的网站（所有网站已隐藏）")
            scheduled_tasks[task_id]['status'] = 'skipped'
            scheduled_tasks[task_id]['finished_at'] = time.time()
            scheduled_tasks[task_id]['details']['error'] = '无可爬取站点'
            return

        # 创建并执行批量爬取任务
        task = create_batch_task("yesterday")
        logger.info(f"🚀 开始批量爬取，共 {len(active_sites)} 个站点")

        try:
            await run_batch_scrape(task, active_sites)
        except Exception as e:
            logger.error(f"❌ 批量爬取异常: {e}")
            scheduled_tasks[task_id]['status'] = 'failed'
            scheduled_tasks[task_id]['finished_at'] = time.time()
            scheduled_tasks[task_id]['details']['error'] = str(e)
            return

        # 统计爬取结果
        success_sites = sum(1 for st in task.site_tasks if st.status == "completed")
        failed_sites = sum(1 for st in task.site_tasks if st.status == "failed")
        logger.info(f"📊 爬取完成: 成功 {success_sites}, 失败 {failed_sites}")
        scheduled_tasks[task_id]['details']['success_sites'] = success_sites
        scheduled_tasks[task_id]['details']['failed_sites'] = failed_sites

        if task.cancelled:
            logger.warning("⚠️ 任务被取消，跳过推送")
            scheduled_tasks[task_id]['status'] = 'cancelled'
            scheduled_tasks[task_id]['finished_at'] = time.time()
            return

        # 开始推送
        logger.info("📤 开始推送匹配数据到云之家")
        pushed_count = await _push_yesterday_data()
        scheduled_tasks[task_id]['details']['pushed'] = pushed_count
        scheduled_tasks[task_id]['status'] = 'completed'
        scheduled_tasks[task_id]['finished_at'] = time.time()

    except Exception as e:
        logger.error(f"❌ 定时任务异常: {e}", exc_info=True)
        if task_id in scheduled_tasks:
            scheduled_tasks[task_id]['status'] = 'failed'
            scheduled_tasks[task_id]['finished_at'] = time.time()
            scheduled_tasks[task_id]['details']['error'] = str(e)


async def _push_yesterday_data():
    """推送昨天的采购公告到云之家（内部函数，供定时任务调用）"""
    from services.subscription import get_all_subscription_keywords

    webhook_url = os.getenv("YZJ_WEBHOOK_URL", "").strip()
    if not webhook_url:
        logger.warning("⚠️ 未配置 YZJ_WEBHOOK_URL，跳过推送")
        return

    yesterday = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")

    # 获取所有订阅词
    keywords = await get_all_subscription_keywords()
    if not keywords:
        logger.warning("⚠️ 当前没有订阅词，跳过推送")
        return

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # 查询昨天的采购公告
            await cur.execute(
                "SELECT id, title, source, url, purchaser, budget, "
                "service_category, bid_time, publish_time, service_location "
                "FROM bids WHERE publish_date = %s AND notice_type = '采购公告'",
                (yesterday,)
            )
            rows = await cur.fetchall()

    if not rows:
        logger.info(f"ℹ️ 昨天({yesterday})没有采购公告数据，跳过推送")
        return

    # 构建 bid_id -> 订阅词匹配 的映射
    bid_matches = {}
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            for kw_id, kw_word in keywords:
                sub_table = f"sub_{kw_id}"
                try:
                    await cur.execute(
                        f"SELECT bid_id FROM `{sub_table}` WHERE bid_id IN ({','.join(['%s'] * len(rows))})",
                        tuple(r[0] for r in rows)
                    )
                    matched_rows = await cur.fetchall()
                    for mr in matched_rows:
                        bid_id = mr[0]
                        if bid_id not in bid_matches:
                            bid_matches[bid_id] = []
                        bid_matches[bid_id].append(kw_word)
                except Exception:
                    pass  # 子表不存在则跳过

    if not bid_matches:
        logger.info(f"ℹ️ 昨天({yesterday})的数据没有匹配到任何订阅词，跳过推送")
        return

    # 构建 bid_id -> row 的索引
    bid_row_map = {r[0]: r for r in rows}

    # 一条一条推送到 webhook
    pushed = 0
    failed = 0
    async with httpx.AsyncClient(timeout=10.0) as client:
        for bid_id, matched_words in bid_matches.items():
            bid_row = bid_row_map.get(bid_id)
            if not bid_row:
                continue
            (_, title, source, url, purchaser, budget,
             service_category, bid_time, publish_time, service_location) = bid_row

            budget_str = f"{budget:,.2f}元" if budget else "未公开"
            content = f"""【订阅词】{'、'.join(matched_words)}
【标题】{title or ''}
【采购人】{purchaser or ''}
【预算金额】{budget_str}
【服务类型】{service_category or ''}
【招标时间】{bid_time or ''}
【发布时间】{publish_time or ''}
【服务地址】{service_location or ''}
【来源】{source or ''}
【链接】{url or ''}"""
            payload = {"content": content}

            try:
                resp = await client.post(
                    webhook_url,
                    json=payload,
                    headers={"Content-Type": "application/json;charset=utf-8"}
                )
                if resp.status_code == 200:
                    pushed += 1
                else:
                    failed += 1
            except Exception:
                failed += 1

    logger.info(f"📤 推送完成: 成功 {pushed}, 失败 {failed} (共 {len(bid_matches)} 条)")
    return pushed


async def daily_cleanup():
    """每日清理任务：删除 7 天前的 bids 数据及关联子表记录"""
    task_id = f"cleanup_{int(time.time() * 1000)}"
    scheduled_tasks[task_id] = {
        'task_id': task_id,
        'type': 'cleanup',
        'status': 'running',
        'description': '清理过期数据',
        'created_at': time.time(),
        'started_at': time.time(),
        'finished_at': None,
        'details': {'deleted_bids': 0, 'deleted_sub': 0},
        'job_id': 'daily_cleanup',
    }
    # 保留最近的任务记录
    if len(scheduled_tasks) > MAX_SCHEDULED_TASKS:
        oldest = min(scheduled_tasks, key=lambda k: scheduled_tasks[k]['created_at'])
        del scheduled_tasks[oldest]

    logger.info("🧹 定时清理任务启动：删除 7 天前的数据")

    pool = await get_pool()
    cutoff_date = (date.today() - timedelta(days=6)).strftime("%Y-%m-%d")

    try:
        # 1. 查出要删除的 bid_id
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT id FROM bids WHERE publish_date < %s",
                    (cutoff_date,)
                )
                rows = await cur.fetchall()

        if not rows:
            scheduled_tasks[task_id]['status'] = 'completed'
            scheduled_tasks[task_id]['finished_at'] = time.time()
            logger.info(f"ℹ️ 没有需要清理的数据（截止线: {cutoff_date}）")
            return

        bid_ids = [r[0] for r in rows]
        logger.info(f"📋 待清理 {len(bid_ids)} 条记录（publish_date < {cutoff_date}）")

        placeholders = ",".join(["%s"] * len(bid_ids))

        # 2. 清理所有订阅词子表中的关联记录
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT id FROM keywords")
                kw_rows = await cur.fetchall()

        sub_cleaned = 0
        for kw_row in kw_rows:
            sub_table = f"sub_{kw_row[0]}"
            try:
                async with pool.acquire() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(
                            f"DELETE FROM `{sub_table}` WHERE bid_id IN ({placeholders})",
                            tuple(bid_ids),
                        )
                        sub_cleaned += cur.rowcount
            except Exception:
                pass  # 子表不存在则跳过

        # 3. 删除 bids 主表记录
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    f"DELETE FROM bids WHERE id IN ({placeholders})",
                    tuple(bid_ids),
                )

        scheduled_tasks[task_id]['status'] = 'completed'
        scheduled_tasks[task_id]['finished_at'] = time.time()
        scheduled_tasks[task_id]['details'] = {'deleted_bids': len(bid_ids), 'deleted_sub': sub_cleaned}
        logger.info(f"🧹 清理完成: 删除 {len(bid_ids)} 条 bids, {sub_cleaned} 条子表记录")

    except Exception as e:
        scheduled_tasks[task_id]['status'] = 'failed'
        scheduled_tasks[task_id]['finished_at'] = time.time()
        scheduled_tasks[task_id]['details']['error'] = str(e)
        logger.error(f"❌ 清理任务异常: {e}")


def start_scheduler():
    """启动调度器，添加定时任务"""
    scheduler = get_or_create_scheduler()

    # 从环境变量读取执行时间，默认 7:00
    schedule_time = os.getenv("SCHEDULE_TIME", "07:00")
    hour, minute = map(int, schedule_time.split(":"))

    # 添加每日定时任务
    scheduler.add_job(
        daily_scrape_and_push,
        trigger=CronTrigger(hour=hour, minute=minute, timezone=ZoneInfo("Asia/Shanghai")),
        id="daily_scrape_and_push",
        name="每日爬取+推送",
        replace_existing=True,
    )

    # 添加每日清理任务（0:00 执行）
    scheduler.add_job(
        daily_cleanup,
        trigger=CronTrigger(hour=0, minute=0, timezone=ZoneInfo("Asia/Shanghai")),
        id="daily_cleanup",
        name="每日数据清理",
        replace_existing=True,
    )

    scheduler.start()
    msg = f"⏰ 定时任务已启动，每日 {schedule_time} 爬取+推送，00:00 清理过期数据"
    logger.info(msg)
    print(msg)  # 确保控制台可见

    # 打印所有已注册的 job 及下次触发时间
    for job in scheduler.get_jobs():
        job_msg = f"   📋 Job: {job.name} | ID: {job.id} | 下次触发: {job.next_run_time}"
        logger.info(job_msg)
        print(job_msg)  # 确保控制台可见

    # 监听 APScheduler 事件，捕获 job 执行异常
    def on_job_error(event):
        job_id = getattr(event, 'job_id', None)
        logger.error(f"⚠️ 定时任务执行异常: job_id={job_id}, code={event.code}")
        if getattr(event, 'exception', None):
            logger.error(f"   异常详情: {event.exception}", exc_info=getattr(event, 'traceback', None))

    def on_job_executed(event):
        job_id = getattr(event, 'job_id', None)
        logger.info(f"✅ 定时任务已触发: job_id={job_id}")

    scheduler.add_listener(on_job_error, 0x400)  # EVENT_JOB_ERROR
    scheduler.add_listener(on_job_executed, 0x2)  # EVENT_JOB_EXECUTED


def stop_scheduler():
    """停止调度器"""
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("⏰ 定时任务已停止")
