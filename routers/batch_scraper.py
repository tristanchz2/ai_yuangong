"""批量爬取路由入口 - 委托 services/batch_task.py"""

# 此模块保留为兼容入口，实际逻辑已迁移至 services/batch_task.py
# 批量爬取相关路由已整合到 routers/admin.py 中

from services.batch_task import (
    SiteTask,
    BatchScraperTask,
    batch_tasks,
    create_batch_task,
    get_batch_task,
    get_latest_batch_task,
    run_batch_scrape,
)
