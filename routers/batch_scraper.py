"""批量爬虫任务管理 - 支持实时进度追踪"""

import asyncio
import json
import subprocess
import time
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta

PROJECT_ROOT = Path(__file__).parent.parent
SCRAPERS_DIR = PROJECT_ROOT / "scrapers"
RAW_DATA_DIR = PROJECT_ROOT / "raw_data"
LOGS_DIR = PROJECT_ROOT / "logs"


class BatchScraperTask:
    """批量爬取任务"""

    def __init__(self, task_id: str, mode: str = "yesterday"):
        self.task_id = task_id
        self.mode = mode  # yesterday, latest, date
        self.status = "pending"  # pending, running, completed, failed
        self.created_at = time.time()
        self.started_at: Optional[float] = None
        self.finished_at: Optional[float] = None

        # 进度信息
        self.total_sites = 0
        self.current_index = 0
        self.current_site: Optional[str] = None
        self.current_step: Optional[str] = None  # scraping, llm_validation, completed

        # 每个站点的结果
        self.results: List[Dict] = []

        # 实时日志
        self.logs: List[str] = []

    def add_log(self, message: str):
        """添加日志"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] {message}"
        self.logs.append(log_entry)

    def to_dict(self) -> Dict:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "mode": self.mode,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration": (self.finished_at or time.time()) - (self.started_at or self.created_at),
            "total_sites": self.total_sites,
            "current_index": self.current_index,
            "current_site": self.current_site,
            "current_step": self.current_step,
            "progress_percent": int((self.current_index / self.total_sites * 100)) if self.total_sites > 0 else 0,
            "results": self.results,
            "logs": self.logs[-100:],  # 只返回最后100条日志
        }


# 全局任务存储
batch_tasks: Dict[str, BatchScraperTask] = {}


def get_yesterday_date() -> str:
    """获取昨天日期"""
    return (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")


async def run_single_scraper(
    task: BatchScraperTask,
    site: Dict,
    mode_args: List[str]
) -> Dict:
    """运行单个爬虫并返回结果"""
    scraper_name = site["scraper_name"]
    scraper_path = SCRAPERS_DIR / f"scrape_{scraper_name}.js"
    output_json = RAW_DATA_DIR / f"{scraper_name}_data.json"

    result = {
        "site_id": site["id"],
        "site_name": site["name"],
        "scraper_name": scraper_name,
        "status": "pending",
        "rows": 0,
        "llm_valid": None,
        "llm_reason": "",
        "duration": 0,
        "logs": []
    }

    start_time = time.time()

    try:
        # 检查爬虫文件是否存在
        if not scraper_path.exists():
            result["status"] = "failed"
            result["error"] = f"爬虫文件不存在: {scraper_path.name}"
            result["duration"] = time.time() - start_time
            return result

        # 步骤1: 运行爬虫
        task.current_step = "scraping"
        task.add_log(f"▶ 开始爬取: {site['name']} ({scraper_name})")

        cmd = ["node", str(scraper_path)] + mode_args
        log_file = LOGS_DIR / f"batch_{task.task_id}_{scraper_name}.log"

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(SCRAPERS_DIR),
        )

        # 实时读取输出
        output_lines = []
        while True:
            try:
                line = await asyncio.wait_for(process.stdout.readline(), timeout=300.0)
                if not line:
                    if process.returncode is not None:
                        break
                    continue
                decoded = line.decode('utf-8', errors='replace').strip()
                output_lines.append(decoded)
                task.add_log(f"  [{scraper_name}] {decoded[:100]}")
            except asyncio.TimeoutError:
                process.kill()
                result["status"] = "failed"
                result["error"] = "爬虫执行超时 (>5分钟)"
                result["duration"] = time.time() - start_time
                return result
            except Exception:
                if process.returncode is not None:
                    break
                continue

        await process.wait()

        if process.returncode != 0:
            result["status"] = "failed"
            result["error"] = f"爬虫退出码: {process.returncode}"
            result["logs"] = output_lines[-10:]
            result["duration"] = time.time() - start_time
            return result

        # 检查输出文件
        if not output_json.exists():
            result["status"] = "failed"
            result["error"] = "输出文件未生成"
            result["duration"] = time.time() - start_time
            return result

        # 读取数据
        with open(output_json, "r", encoding="utf-8") as f:
            data = json.load(f)

        rows = data.get("rows", [])
        result["rows"] = len(rows)

        if len(rows) == 0:
            result["status"] = "failed"
            result["error"] = "爬取数据为空"
            result["duration"] = time.time() - start_time
            return result

        task.add_log(f"  ✓ 爬取完成，共 {len(rows)} 条数据")

        # 步骤2: LLM 验证
        task.current_step = "llm_validation"
        task.add_log(f"  🤖 正在进行 LLM 数据质量验证...")

        llm_valid, llm_reason = await validate_data_quality(data, site["url"])
        result["llm_valid"] = llm_valid
        result["llm_reason"] = llm_reason

        if llm_valid:
            result["status"] = "success"
            task.add_log(f"  ✓ LLM 验证通过: {llm_reason}")
        else:
            result["status"] = "warning"
            task.add_log(f"  ⚠ LLM 验证未通过: {llm_reason}")

        result["duration"] = time.time() - start_time
        return result

    except Exception as e:
        result["status"] = "failed"
        result["error"] = str(e)
        result["duration"] = time.time() - start_time
        task.add_log(f"  ✗ 异常: {str(e)}")
        return result


async def validate_data_quality(data: Dict, source_url: str) -> tuple:
    """LLM 验证数据质量"""
    import os

    api_key = os.environ.get('OPENAI_API_KEY')
    base_url = os.environ.get('OPENAI_BASE_URL', 'https://api.openai.com/v1')
    model = os.environ.get('OPENAI_MODEL', 'gpt-4o-mini')

    if not api_key:
        return fallback_check(data)

    try:
        rows_sample = data['rows'][:3]
        summary = json.dumps({
            'total_rows': len(data['rows']),
            'sample_rows': rows_sample,
            'fields': list(data['rows'][0].keys()) if data['rows'] else []
        }, ensure_ascii=False, indent=2)

        prompt = f"""你是一个爬虫数据质量审核员。请判断以下爬虫数据是否有效。

源网站: {source_url}

数据摘要:
{summary}

判断标准:
1. content 字段不能为空或只有标题
2. 数据内容要有实际价值
3. 字段结构合理
4. content 应该包含正文内容

请回复 JSON 格式: {{"valid": true/false, "reason": "原因"}}
只回复 JSON。"""

        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url=base_url)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "你是数据质量审核员。只返回 JSON。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0,
        )

        result_text = response.choices[0].message.content
        if not result_text:
            return fallback_check(data)

        result = json.loads(result_text.strip())
        return (result.get('valid', False), result.get('reason', '未知原因'))

    except Exception as e:
        return fallback_check(data)


def fallback_check(data: Dict) -> tuple:
    """基础质量检查"""
    if not data.get('rows'):
        return False, "数据为空"

    first_row = data['rows'][0]
    content = first_row.get('content', '')

    if not content or len(content) < 50:
        return False, f"content 过短 ({len(content)} 字符)"

    return True, "基础检查通过"


async def run_batch_scrape(
    task: BatchScraperTask,
    sites: List[Dict]
):
    """执行批量爬取"""
    task.status = "running"
    task.started_at = time.time()
    task.total_sites = len(sites)

    # 构建模式参数
    if task.mode == "yesterday":
        mode_args = ["--yesterday"]
    elif task.mode == "latest":
        mode_args = ["--latest", "10"]
    else:
        mode_args = ["--latest", "5"]

    task.add_log(f"🚀 开始批量爬取，模式: {task.mode}，共 {len(sites)} 个站点")

    for i, site in enumerate(sites):
        task.current_index = i
        task.current_site = site["name"]

        result = await run_single_scraper(task, site, mode_args)
        task.results.append(result)

    # 完成
    task.current_index = len(sites)
    task.current_site = None
    task.current_step = "completed"
    task.status = "completed"
    task.finished_at = time.time()

    # 统计
    success_count = sum(1 for r in task.results if r["status"] == "success")
    warning_count = sum(1 for r in task.results if r["status"] == "warning")
    failed_count = sum(1 for r in task.results if r["status"] == "failed")

    task.add_log(f"")
    task.add_log(f"{'='*50}")
    task.add_log(f"📊 批量爬取完成!")
    task.add_log(f"   成功: {success_count}, 警告: {warning_count}, 失败: {failed_count}")
    task.add_log(f"   总耗时: {task.finished_at - task.started_at:.1f}秒")
    task.add_log(f"{'='*50}")


def create_batch_task(mode: str = "yesterday") -> BatchScraperTask:
    """创建新的批量任务"""
    task_id = f"batch_{int(time.time() * 1000)}"
    task = BatchScraperTask(task_id, mode)
    batch_tasks[task_id] = task
    return task


def get_batch_task(task_id: str) -> Optional[BatchScraperTask]:
    """获取任务"""
    return batch_tasks.get(task_id)


def get_latest_batch_task() -> Optional[BatchScraperTask]:
    """获取最新的任务"""
    if not batch_tasks:
        return None
    return max(batch_tasks.values(), key=lambda t: t.created_at)
