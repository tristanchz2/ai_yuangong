"""爬虫生成路由 - 生成爬虫、任务状态、日志"""

import asyncio
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException

from config.settings import PROJECT_ROOT
from models.schemas import GenerateRequest, GenerateResponse, TaskStatus
from services.scraper_generator import (
    tasks, derive_scraper_name, run_hermes_generate, MAX_GENERATE_TASKS
)

router = APIRouter(tags=["爬虫生成"])


@router.post("/generate", response_model=GenerateResponse)
async def generate_scraper(req: GenerateRequest):
    """生成爬虫"""
    from urllib.parse import urlparse
    parsed = urlparse(req.url)
    if not parsed.scheme or not parsed.netloc:
        raise HTTPException(status_code=400, detail=f"URL 格式错误: {req.url}")

    clean_url = req.url
    if '://' in req.url:
        idx = req.url.index('://')
        prefix = req.url[:idx]
        if ':' in prefix:
            first_colon = prefix.index(':')
            scheme = prefix[:first_colon]
            rest = req.url[idx+3:]
            clean_url = f"{scheme}://{rest}"
    else:
        if req.url.startswith('https:'):
            clean_url = 'https://' + req.url[6:]
        elif req.url.startswith('http:'):
            clean_url = 'http://' + req.url[5:]

    task_id = f"task_{int(time.time() * 1000)}"

    # 清理旧任务，保留最近5个
    if len(tasks) >= MAX_GENERATE_TASKS:
        sorted_tasks = sorted(tasks.keys(), key=lambda k: tasks[k]['created_at'])
        for old_id in sorted_tasks[:len(tasks) - MAX_GENERATE_TASKS + 1]:
            del tasks[old_id]

    tasks[task_id] = {
        'task_id': task_id,
        'task_type': 'generate',
        'status': 'pending',
        'url': clean_url,
        'scraper_name': None,
        'scraper_path': None,
        'error': None,
        'started_at': None,
        'finished_at': None,
        'duration': None,
        'hermes_output': '',
        'created_at': time.time(),
    }

    asyncio.create_task(run_hermes_generate(task_id, clean_url, req.name, req.reference_urls))

    return GenerateResponse(
        task_id=task_id,
        status='pending',
        message=f'任务已创建，正在生成爬虫。用 GET /status/{task_id} 查询进度。'
    )


@router.get("/status/{task_id}", response_model=TaskStatus)
async def get_status(task_id: str):
    """查询任务状态"""
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="任务不存在")
    task = tasks[task_id]
    return TaskStatus(**task)


@router.get("/status")
async def list_tasks():
    """列出所有任务"""
    return {
        'total': len(tasks),
        'tasks': [
            {
                'task_id': t['task_id'],
                'status': t['status'],
                'url': t['url'],
                'scraper_name': t.get('scraper_name'),
                'duration': t.get('duration'),
            }
            for t in tasks.values()
        ]
    }


@router.get("/logs/{task_id}")
async def get_logs(task_id: str):
    """读取任务日志"""
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="任务不存在")

    task = tasks[task_id]
    log_file = task.get('log_file')

    if not log_file:
        return {'task_id': task_id, 'status': task['status'], 'log': '任务尚未开始'}

    log_path = Path(log_file)
    if not log_path.exists():
        return {'task_id': task_id, 'status': task['status'], 'log': '日志文件不存在'}

    with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()

    return {
        'task_id': task_id,
        'status': task['status'],
        'log': content,
        'log_file': log_file,
    }


@router.get("/generate-tasks")
async def list_generate_tasks():
    """列出所有爬虫生成任务"""
    # 按创建时间倒序
    sorted_tasks = sorted(
        tasks.values(),
        key=lambda t: t.get('created_at', 0),
        reverse=True
    )
    return {
        'total': len(sorted_tasks),
        'tasks': [
            {
                'task_id': t['task_id'],
                'type': 'generate_scraper',
                'status': t['status'],
                'url': t['url'],
                'scraper_name': t.get('scraper_name'),
                'duration': t.get('duration'),
                'started_at': t.get('started_at'),
                'created_at': t.get('created_at'),
            }
            for t in sorted_tasks
        ]
    }
