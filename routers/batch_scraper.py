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
        self.status = "pending"  # pending, running, completed, failed, cancelled
        self.created_at = time.time()
        self.started_at: Optional[float] = None
        self.finished_at: Optional[float] = None
        self.site_tasks: List[SiteTask] = []
        self.logs: List[str] = []
        self.cancelled = False
        self._running_processes: List[asyncio.subprocess.Process] = []
        # 取消信号文件：传给 extract_fields.py 子进程
        self._cancel_file = PROJECT_ROOT / f".cancel_{task_id}"


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
            "cancelled": self.cancelled,
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

    def request_cancel(self):
        """标记任务为取消状态，并终止所有正在运行的子进程"""
        self.cancelled = True
        self.status = "cancelled"
        self.add_log("🛑 收到终止指令，正在停止所有运行中的任务...")

        # ① 立即创建取消信号文件（extract_fields.py 会在 LLM 调用和写入前检查）
        try:
            self._cancel_file.write_text(str(time.time()))
        except Exception:
            pass

        killed = 0
        # ② 先 SIGTERM 所有子进程，给 Python 子进程一个优雅退出的机会
        for proc in list(self._running_processes):
            try:
                if proc.returncode is None:
                    proc.terminate()
                    killed += 1
            except Exception:
                pass
        # 兜底：终止 SiteTask 上残留的进程
        for st in self.site_tasks:
            proc = getattr(st, '_current_process', None)
            if proc and proc.returncode is None:
                try:
                    proc.terminate()
                    killed += 1
                except Exception:
                    pass

        # ③ 短暂等待后强制 kill 仍然存活的进程
        time.sleep(0.3)
        for proc in list(self._running_processes):
            try:
                if proc.returncode is None:
                    proc.kill()
            except Exception:
                pass
        for st in self.site_tasks:
            proc = getattr(st, '_current_process', None)
            if proc and proc.returncode is None:
                try:
                    proc.kill()
                except Exception:
                    pass

        self._running_processes.clear()
        self.add_log(f"🛑 已终止 {killed} 个子进程")
        # 将所有站点标记为失败
        for st in self.site_tasks:
            if st.status in ("scraping", "llm_waiting", "llm_extracting"):
                st.status = "failed"
                st.error = "用户终止了任务"
                st.add_log("🛑 任务被用户终止")
                st.end_time = time.time()
        self.finished_at = time.time()


# 全局任务存储（保留最近5个）
batch_tasks: Dict[str, BatchScraperTask] = {}
MAX_BATCH_TASKS = 5


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
    try:
        await asyncio.gather(*coros)
    except asyncio.CancelledError:
        task.add_log("🛑 主协程被取消")

    # 完成后确保所有残留进程被清理
    for proc in list(task._running_processes):
        try:
            if proc.returncode is None:
                proc.kill()
        except Exception:
            pass
    task._running_processes.clear()

    # 清理取消信号文件
    try:
        if task._cancel_file.exists():
            task._cancel_file.unlink()
    except Exception:
        pass

    # 完成
    task.finished_at = time.time()
    if task.cancelled:
        task.add_log("")
        task.add_log("=" * 50)
        task.add_log("🛑 任务已被终止")
        success = sum(1 for st in task.site_tasks if st.status == "completed")
        failed = sum(1 for st in task.site_tasks if st.status == "failed")
        task.add_log(f"📊 终止时进度: 成功 {success}, 失败 {failed}")
        task.add_log("=" * 50)
    else:
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

    # 检查任务是否已被取消
    if task.cancelled:
        st.status = "failed"
        st.error = "任务已被终止"
        st.add_log("🛑 任务已被终止，跳过")
        st.end_time = time.time()
        return

    # ── 阶段1: 爬虫执行 ──
    st.status = "scraping"
    st.add_log(f"▶ 开始爬取: {st.site['name']}")

    async with scraper_sem:
        scraper_ok = await _run_scraper_process(task, st, mode_args)

    # 爬虫完成后立即检查取消
    if task.cancelled:
        st.status = "failed"
        st.error = "任务已被终止"
        st.add_log("🛑 爬虫阶段后被终止")
        st.end_time = time.time()
        return

    if not scraper_ok:
        st.status = "failed"
        st.end_time = time.time()
        return

    st.add_log(f"✓ 爬取完成，共 {st.rows} 条数据")

    # ── 阶段2: LLM 字段提取 ──
    st.status = "llm_waiting"
    st.add_log("⏳ 等待 LLM 提取...")

    # LLM 提取前再次检查取消
    if task.cancelled:
        st.status = "failed"
        st.error = "任务已被终止"
        st.add_log("🛑 任务已被终止，跳过 LLM 提取")
        st.end_time = time.time()
        return

    st.status = "llm_extracting"
    st.add_log(f"🤖 开始 LLM 字段提取: {st.site.get('scraper_name', '')}")

    async with llm_sem:
        # 进入 LLM 前再做一次检查（可能在等信号量期间被取消）
        if task.cancelled:
            st.status = "failed"
            st.error = "任务已被终止"
            st.add_log("🛑 等待 LLM 信号量时被终止")
            st.end_time = time.time()
            return
        extract_ok = await _run_field_extraction(task, st)

    # 最终检查
    if task.cancelled:
        st.status = "failed"
        st.error = "任务已被终止"
        st.add_log("🛑 LLM 阶段后被终止")
        st.end_time = time.time()
        return

    if extract_ok:
        st.status = "completed"
        st.add_log(f"✓ LLM 提取完成，输出 {st.extracted_rows} 条记录")
    else:
        st.status = "failed"

    st.end_time = time.time()


async def _run_scraper_process(task: BatchScraperTask, st: SiteTask, mode_args: List[str]) -> bool:
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
        # 注册进程到 task 和 st，以便终止
        st._current_process = process
        task._running_processes.append(process)

        while True:
            try:
                # 每读一行都检查取消状态
                if task.cancelled:
                    process.kill()
                    st.add_log("🛑 爬虫进程因任务取消被终止")
                    return False
                line = await asyncio.wait_for(process.stdout.readline(), timeout=10.0)
                if not line:
                    if process.returncode is not None:
                        break
                    continue
                decoded = line.decode('utf-8', errors='replace').strip()
                if decoded:
                    st.add_log(decoded[:120])
            except asyncio.TimeoutError:
                if task.cancelled:
                    process.kill()
                    st.add_log("🛑 爬虫进程因任务取消被终止")
                    return False
                continue
            except asyncio.CancelledError:
                process.kill()
                st.add_log("🛑 爬虫进程被终止")
                return False
            except Exception:
                if process.returncode is not None:
                    break
                continue

        await process.wait()

        # 从注册表中移除
        if process in task._running_processes:
            task._running_processes.remove(process)
        st._current_process = None

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
        # 清理
        if process in task._running_processes:
            task._running_processes.remove(process)
        return False


async def _run_field_extraction(task: BatchScraperTask, st: SiteTask) -> bool:
    """运行 extract_fields.py 进行字段提取，合并写入 extracted_data/{notice_type}/{date}.json"""
    source = st.site.get("scraper_name", "")

    cmd = [
        "python3", str(EXTRACT_SCRIPT),
        "--source", source,
        "--concurrency", str(MAX_LLM_CONCURRENCY),
        "--cancel-file", str(task._cancel_file),
    ]

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(PROJECT_ROOT),
        )
        st._current_process = process
        task._running_processes.append(process)

        while True:
            try:
                # 每读一行都检查取消状态
                if task.cancelled:
                    process.kill()
                    st.add_log("🛑 LLM 进程因任务取消被终止")
                    # 从注册表中移除
                    if process in task._running_processes:
                        task._running_processes.remove(process)
                    st._current_process = None
                    return False
                line = await asyncio.wait_for(process.stdout.readline(), timeout=10.0)
                if not line:
                    if process.returncode is not None:
                        break
                    continue
                decoded = line.decode('utf-8', errors='replace').strip()
                if decoded:
                    st.add_log(f"[LLM] {decoded[:120]}")
            except asyncio.TimeoutError:
                if task.cancelled:
                    process.kill()
                    st.add_log("🛑 LLM 进程因任务取消被终止")
                    if process in task._running_processes:
                        task._running_processes.remove(process)
                    st._current_process = None
                    return False
                continue
            except asyncio.CancelledError:
                process.kill()
                st.add_log("🛑 LLM 进程被终止")
                if process in task._running_processes:
                    task._running_processes.remove(process)
                st._current_process = None
                return False
            except Exception:
                if process.returncode is not None:
                    break
                continue

        await process.wait()

        # 从注册表中移除
        if process in task._running_processes:
            task._running_processes.remove(process)
        st._current_process = None

        if process.returncode != 0:
            st.error = f"LLM 提取退出码: {process.returncode}"
            st.add_log(f"✗ {st.error}")
            return False

        # 统计该源在 extracted_data 中的记录数
        st.extracted_rows = _count_extracted_records(source)
        return True

    except FileNotFoundError:
        st.error = "extract_fields.py 不存在"
        st.add_log(f"✗ {st.error}")
        return False
    except Exception as e:
        st.error = str(e)
        st.add_log(f"✗ 异常: {str(e)}")
        return False


def _count_extracted_records(source: str) -> int:
    """统计指定源在 extracted_data 中的记录数"""
    try:
        extracted_dir = PROJECT_ROOT / "extracted_data"
        total = 0
        for folder in ["采购公告", "结果公告", "其他"]:
            folder_path = extracted_dir / folder
            if folder_path.exists():
                for f in folder_path.glob("*.json"):
                    with open(f, "r", encoding="utf-8") as fh:
                        data = json.load(fh)
                        records = data.get("records", [])
                        total += sum(1 for r in records if r.get("source") == source)
        return total
    except Exception:
        return 0


def create_batch_task(mode: str = "yesterday") -> BatchScraperTask:
    task_id = f"batch_{int(time.time() * 1000)}"
    task = BatchScraperTask(task_id, mode)
    batch_tasks[task_id] = task
    
    # 保留最近5个任务
    if len(batch_tasks) > MAX_BATCH_TASKS:
        oldest = min(batch_tasks, key=lambda k: batch_tasks[k].created_at)
        del batch_tasks[oldest]
    
    return task


def get_batch_task(task_id: str) -> Optional[BatchScraperTask]:
    return batch_tasks.get(task_id)


def get_latest_batch_task() -> Optional[BatchScraperTask]:
    if not batch_tasks:
        return None
    return max(batch_tasks.values(), key=lambda t: t.created_at)
