"""批量爬虫任务管理 - 并行爬虫(5) + LLM提取(3) + 每站点状态追踪"""

import asyncio
import json
import time
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent
SCRAPERS_DIR = PROJECT_ROOT / "scrapers"
RAW_DATA_DIR = PROJECT_ROOT / "raw_data"
LOGS_DIR = PROJECT_ROOT / "logs"
EXTRACT_SCRIPT = PROJECT_ROOT / "extract_fields.py"

MAX_SCRAPER_CONCURRENCY = 5
MAX_LLM_CONCURRENCY = 3


class SiteTask:
    """单个站点的任务状态"""

    def __init__(self, site: Dict):
        self.site = site
        self.status = "idle"
        # idle -> scraping -> llm_waiting -> llm_extracting -> completed/failed
        self.logs: List[str] = []
        self.rows = 0
        self.extracted_rows = 0
        self.error = ""
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None

    def add_log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.logs.append(f"[{ts}] {msg}")

    def to_dict(self) -> Dict:
        return {
            "site_id": self.site["id"],
            "site_name": self.site["name"],
            "scraper_name": self.site.get("scraper_name", ""),
            "status": self.status,
            "rows": self.rows,
            "extracted_rows": self.extracted_rows,
            "error": self.error,
            "duration": round((self.end_time or time.time()) - (self.start_time or time.time()), 1) if self.start_time else 0,
            "logs": self.logs[-200:],
        }


class BatchScraperTask:
    """批量爬取任务"""

    def __init__(self, task_id: str, mode: str = "yesterday"):
        self.task_id = task_id
        self.mode = mode
        self.status = "pending"  # pending, running, completed, failed
        self.created_at = time.time()
        self.started_at: Optional[float] = None
        self.finished_at: Optional[float] = None
        self.site_tasks: List[SiteTask] = []
        self.logs: List[str] = []

    def add_log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.logs.append(f"[{ts}] {msg}")

    def to_dict(self) -> Dict:
        total = len(self.site_tasks)
        completed = sum(1 for st in self.site_tasks if st.status in ("completed", "failed"))
        success = sum(1 for st in self.site_tasks if st.status == "completed")
        warning = sum(1 for st in self.site_tasks if st.status == "completed" and st.extracted_rows == 0)
        failed = sum(1 for st in self.site_tasks if st.status == "failed")
        running = sum(1 for st in self.site_tasks if st.status in ("scraping", "llm_extracting"))

        return {
            "task_id": self.task_id,
            "status": self.status,
            "mode": self.mode,
            "total_sites": total,
            "completed_sites": completed,
            "success_count": success,
            "warning_count": warning,
            "failed_count": failed,
            "running_count": running,
            "progress_percent": int(completed / total * 100) if total > 0 else 0,
            "duration": round((self.finished_at or time.time()) - (self.started_at or self.created_at), 1),
            "sites": [st.to_dict() for st in self.site_tasks],
            "logs": self.logs[-100:],
        }


# 全局任务存储
batch_tasks: Dict[str, BatchScraperTask] = {}


async def run_batch_scrape(task: BatchScraperTask, sites: List[Dict]):
    """执行批量爬取 - 并行模式"""
    task.status = "running"
    task.started_at = time.time()

    scraper_sem = asyncio.Semaphore(MAX_SCRAPER_CONCURRENCY)
    llm_sem = asyncio.Semaphore(MAX_LLM_CONCURRENCY)

    # 构建模式参数
    if task.mode == "yesterday":
        mode_args = ["--yesterday"]
    elif task.mode == "latest":
        mode_args = ["--latest", "10"]
    else:
        mode_args = ["--latest", "5"]

    # 初始化所有站点任务
    task.site_tasks = [SiteTask(site) for site in sites]

    task.add_log(f"🚀 开始批量爬取，模式: {task.mode}，共 {len(sites)} 个站点")
    task.add_log(f"⚡ 爬虫并发: {MAX_SCRAPER_CONCURRENCY}, LLM提取并发: {MAX_LLM_CONCURRENCY}")

    # 并行执行所有站点
    coros = [
        _run_site_pipeline(task, st, scraper_sem, llm_sem, mode_args)
        for st in task.site_tasks
    ]
    await asyncio.gather(*coros)

    # 完成
    task.finished_at = time.time()
    task.status = "completed"

    success = sum(1 for st in task.site_tasks if st.status == "completed")
    failed = sum(1 for st in task.site_tasks if st.status == "failed")
    task.add_log("")
    task.add_log("=" * 50)
    task.add_log(f"📊 批量爬取完成! 成功: {success}, 失败: {failed}")
    task.add_log(f"⏱️  总耗时: {task.finished_at - task.started_at:.1f}秒")
    task.add_log("=" * 50)


async def _run_site_pipeline(
    task: BatchScraperTask,
    st: SiteTask,
    scraper_sem: asyncio.Semaphore,
    llm_sem: asyncio.Semaphore,
    mode_args: List[str],
):
    """单个站点的完整流水线：爬虫 → LLM提取"""
    st.start_time = time.time()

    # ── 阶段1: 爬虫执行 ──
    st.status = "scraping"
    st.add_log(f"▶ 开始爬取: {st.site['name']}")

    async with scraper_sem:
        scraper_ok = await _run_scraper_process(st, mode_args)

    if not scraper_ok:
        st.status = "failed"
        st.end_time = time.time()
        return

    st.add_log(f"✓ 爬取完成，共 {st.rows} 条数据")

    # ── 阶段2: LLM 字段提取 ──
    st.status = "llm_waiting"
    st.add_log("⏳ 等待 LLM 提取...")

    st.status = "llm_extracting"
    st.add_log(f"🤖 开始 LLM 字段提取: {st.site.get('scraper_name', '')}")

    async with llm_sem:
        extract_ok = await _run_field_extraction(st)

    if extract_ok:
        st.status = "completed"
        st.add_log(f"✓ LLM 提取完成，输出 {st.extracted_rows} 条记录")
    else:
        st.status = "failed"

    st.end_time = time.time()


async def _run_scraper_process(st: SiteTask, mode_args: List[str]) -> bool:
    """运行爬虫 Node.js 进程"""
    scraper_name = st.site.get("scraper_name", "")
    scraper_path = SCRAPERS_DIR / f"scrape_{scraper_name}.js"
    output_json = RAW_DATA_DIR / f"{scraper_name}_data.json"

    if not scraper_path.exists():
        st.error = f"爬虫文件不存在: {scraper_path.name}"
        st.add_log(f"✗ {st.error}")
        return False

    cmd = ["node", str(scraper_path)] + mode_args

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(SCRAPERS_DIR),
        )

        while True:
            try:
                line = await asyncio.wait_for(process.stdout.readline(), timeout=300.0)
                if not line:
                    if process.returncode is not None:
                        break
                    continue
                decoded = line.decode('utf-8', errors='replace').strip()
                if decoded:
                    st.add_log(decoded[:120])
            except asyncio.TimeoutError:
                process.kill()
                st.error = "爬虫执行超时 (>5分钟)"
                st.add_log(f"✗ {st.error}")
                return False
            except Exception:
                if process.returncode is not None:
                    break
                continue

        await process.wait()

        if process.returncode != 0:
            st.error = f"爬虫退出码: {process.returncode}"
            st.add_log(f"✗ {st.error}")
            return False

        # 检查输出
        if not output_json.exists():
            st.error = "输出文件未生成"
            st.add_log(f"✗ {st.error}")
            return False

        with open(output_json, "r", encoding="utf-8") as f:
            data = json.load(f)

        rows = data.get("rows", [])
        st.rows = len(rows)

        if len(rows) == 0:
            st.error = "爬取数据为空"
            st.add_log(f"✗ {st.error}")
            return False

        return True

    except Exception as e:
        st.error = str(e)
        st.add_log(f"✗ 异常: {str(e)}")
        return False


async def _run_field_extraction(st: SiteTask) -> bool:
    """运行 extract_fields.py 进行字段提取，输出到 extracted_data/{notice_type}/"""
    source = st.site.get("scraper_name", "")
    # 生成唯一后缀，避免并发运行时输出文件互相覆盖
    run_suffix = f"{source}_{int(time.time())}"
    st.add_log(f"📂 输出文件后缀: {run_suffix}")

    cmd = [
        "python3", str(EXTRACT_SCRIPT),
        "--source", source,
        "--concurrency", "1",
        "--suffix", run_suffix,
    ]

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(PROJECT_ROOT),
        )

        while True:
            try:
                line = await asyncio.wait_for(process.stdout.readline(), timeout=600.0)
                if not line:
                    if process.returncode is not None:
                        break
                    continue
                decoded = line.decode('utf-8', errors='replace').strip()
                if decoded:
                    st.add_log(f"[LLM] {decoded[:120]}")
            except asyncio.TimeoutError:
                process.kill()
                st.error = "LLM 提取超时 (>10分钟)"
                st.add_log(f"✗ {st.error}")
                return False
            except Exception:
                if process.returncode is not None:
                    break
                continue

        await process.wait()

        if process.returncode != 0:
            st.error = f"LLM 提取退出码: {process.returncode}"
            st.add_log(f"✗ {st.error}")
            return False

        # 统计本次提取生成的记录数
        st.extracted_rows = _count_extracted_records(run_suffix)
        return True

    except FileNotFoundError:
        st.error = "extract_fields.py 不存在"
        st.add_log(f"✗ {st.error}")
        return False
    except Exception as e:
        st.error = str(e)
        st.add_log(f"✗ 异常: {str(e)}")
        return False


def _count_extracted_records(suffix: str) -> int:
    """统计指定 suffix 的提取记录数"""
    try:
        extracted_dir = PROJECT_ROOT / "extracted_data"
        total = 0
        for folder in ["采购公告", "结果公告", "其他"]:
            folder_path = extracted_dir / folder
            if folder_path.exists():
                # 查找包含该 suffix 的文件（如 2026-07-09_abc_puc_1234.json）
                for f in folder_path.glob(f"*_{suffix}.json"):
                    with open(f, "r", encoding="utf-8") as fh:
                        data = json.load(fh)
                        total += len(data.get("records", []))
        return total
    except Exception:
        return 0


def create_batch_task(mode: str = "yesterday") -> BatchScraperTask:
    task_id = f"batch_{int(time.time() * 1000)}"
    task = BatchScraperTask(task_id, mode)
    batch_tasks[task_id] = task
    return task


def get_batch_task(task_id: str) -> Optional[BatchScraperTask]:
    return batch_tasks.get(task_id)


def get_latest_batch_task() -> Optional[BatchScraperTask]:
    if not batch_tasks:
        return None
    return max(batch_tasks.values(), key=lambda t: t.created_at)
