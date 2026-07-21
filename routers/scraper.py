"""爬虫生成路由 - 生成爬虫、任务状态、日志"""

import asyncio
import json
import time
from pathlib import Path
from typing import Optional, Dict, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(tags=["爬虫生成"])

PROJECT_ROOT = Path(__file__).parent.parent
SCRAPERS_DIR = PROJECT_ROOT / "scrapers"

# 任务状态存储（内存存储，生产环境应换 Redis/DB）
tasks: Dict[str, dict] = {}
MAX_GENERATE_TASKS = 5  # 保留最近5个爬虫生成任务


class GenerateRequest(BaseModel):
    url: str
    name: Optional[str] = None
    reference_urls: Optional[list[str]] = None


class GenerateResponse(BaseModel):
    task_id: str
    status: str
    message: str


class TaskStatus(BaseModel):
    task_id: str
    status: str
    url: str
    scraper_name: Optional[str] = None
    scraper_path: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    duration: Optional[float] = None


def derive_scraper_name(url: str) -> str:
    """从 URL 推导爬虫名称"""
    from urllib.parse import urlparse
    import re

    parsed = urlparse(url)
    domain = parsed.netloc.replace('www.', '')
    parts = domain.split('.')

    tld_second_levels = {'com', 'net', 'org', 'edu', 'gov', 'co', 'ac'}
    if len(parts) >= 3 and parts[-2] in tld_second_levels:
        name = parts[-3]
    elif len(parts) >= 2:
        name = parts[-2]
    else:
        name = parts[0]

    name = re.sub(r'[^a-zA-Z0-9]', '_', name).lower()
    name = re.sub(r'_+', '_', name).strip('_')
    return name or 'unknown'


def validate_data_quality_with_llm(data: Dict[str, Any], source_url: str) -> tuple:
    """用 LLM 验证爬虫数据质量"""
    import os
    api_key = os.environ.get('OPENAI_API_KEY')
    base_url = os.environ.get('OPENAI_BASE_URL', 'https://api.openai.com/v1')
    model = os.environ.get('OPENAI_MODEL', 'gpt-4o-mini')

    if not api_key:
        return fallback_quality_check(data)

    try:
        rows_sample = data['rows'][:3]
        data_summary = json.dumps({
            'total_rows': len(data['rows']),
            'sample_rows': rows_sample,
            'fields': list(data['rows'][0].keys()) if data['rows'] else []
        }, ensure_ascii=False, indent=2)

        prompt = f"""你是一个爬虫数据质量审核员。请判断以下爬虫数据是否有效。

源网站: {source_url}

数据摘要:
{data_summary}

判断标准:
1. content 字段不能为空或只有标题
2. 数据内容要有实际价值
3. 字段结构合理
4. content 应该包含正文内容

请回复 JSON 格式: {{"valid": true/false, "reason": "原因"}}
只回复 JSON，不要其他内容。"""

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
            return fallback_quality_check(data)

        result = json.loads(result_text.strip())
        return (result.get('valid', False), result.get('reason', '未知原因'))

    except Exception as e:
        print(f"LLM 验证失败，降级到基础检查: {e}")
        return fallback_quality_check(data)


def fallback_quality_check(data: Dict[str, Any]) -> tuple:
    """降级的基础质量检查"""
    if not data.get('rows'):
        return False, "数据为空"

    first_row = data['rows'][0]
    content = first_row.get('content', '')
    title = first_row.get('title', '')

    if not content or len(content) < 10:
        return False, "content 字段为空或过短"

    if content.strip() == title.strip():
        return False, "content 等于标题"

    if len(content) < 50:
        return False, f"content 过短（{len(content)} 字符）"

    return True, "基础检查通过"


async def _cleanup_scraper_files(scraper_name: str):
    """清理爬虫可能生成的残留文件"""
    if not scraper_name:
        return
    scraper_path = SCRAPERS_DIR / f"scrape_{scraper_name}.js"
    output_json = PROJECT_ROOT / "raw_data" / f"{scraper_name}_data.json"
    for f in [scraper_path, output_json]:
        if f.exists():
            f.unlink()


async def _run_hermes_generate_step(task_id: str, url: str, custom_name: Optional[str], reference_urls: Optional[list[str]], skill_name: str):
    """单步执行：用指定 skill 调用 Hermes 生成爬虫。返回 True 表示成功，False 表示失败。"""
    task = tasks[task_id]
    log_file = PROJECT_ROOT / "logs" / f"{task_id}_{skill_name}.log"
    log_file.parent.mkdir(exist_ok=True)
    log_file.touch()
    task['log_file'] = str(log_file)

    process = None
    scraper_name = custom_name or derive_scraper_name(url)
    scraper_path = SCRAPERS_DIR / f"scrape_{scraper_name}.js"
    output_json = PROJECT_ROOT / "raw_data" / f"{scraper_name}_data.json"

    try:
        if scraper_path.exists():
            # 如果文件已存在（可能是上一步残留），先清理
            await _cleanup_scraper_files(scraper_name)

        # 拼接 prompt
        prompt = f"帮我爬这个网站：{url}，爬虫名称用 {scraper_name}。不要问我任何问题，所有决策你自己做，遇到错误自己修复。"

        if reference_urls and len(reference_urls) > 0:
            refs_text = "\n".join([f"- {ref_url}" for ref_url in reference_urls])
            prompt += f"\n\n参考以下详情页 URL，学习页面结构和选择器：\n{refs_text}\n\n优先从这些参考页面分析 HTML 结构和数据提取规则。"

        cmd = ['hermes', 'chat', '-q', prompt, '-s', skill_name, '--yolo']

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(PROJECT_ROOT),
        )
        assert process.stdout is not None

        # 超时设置
        ABSOLUTE_TIMEOUT = 1800  # 30 分钟
        IDLE_TIMEOUT = 300  # 5 分钟无输出
        last_output_time = time.time()
        step_started_at = time.time()

        with open(log_file, 'w', encoding='utf-8') as f:
            while True:
                elapsed = time.time() - step_started_at
                if elapsed > ABSOLUTE_TIMEOUT:
                    task['error'] = f'{skill_name} 执行超时（{elapsed:.0f}s > {ABSOLUTE_TIMEOUT}s）'
                    process.kill()
                    await process.wait()
                    return False

                idle_elapsed = time.time() - last_output_time
                remaining_idle = IDLE_TIMEOUT - idle_elapsed
                read_timeout = max(min(remaining_idle, 60.0), 5.0)

                try:
                    line = await asyncio.wait_for(process.stdout.readline(), timeout=read_timeout)
                    if not line:
                        break
                    f.write(line.decode('utf-8', errors='replace'))
                    f.flush()
                    last_output_time = time.time()
                except asyncio.TimeoutError:
                    if time.time() - last_output_time >= IDLE_TIMEOUT:
                        task['error'] = f'{skill_name} 进程无新输出超过 {IDLE_TIMEOUT}s，疑似 hang'
                        process.kill()
                        await process.wait()
                        return False
                    if process.returncode is not None:
                        break
                    continue
                except Exception:
                    if process.returncode is not None:
                        break
                    continue

        try:
            await asyncio.wait_for(process.wait(), timeout=10)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()

        if process.returncode != 0:
            with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
                log_content = f.read()
            task['error'] = log_content[-2000:] or f'{skill_name} 退出码 {process.returncode}'
            return False

        if not scraper_path.exists():
            with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
                log_content = f.read()
            task['error'] = f'{skill_name} 爬虫文件未生成: {scraper_path}'
            task['log_preview'] = log_content[-1000:] if log_content else ''
            return False

        # 测试爬虫
        test_passed = False
        test_output = ''

        try:
            info_result = await asyncio.create_subprocess_exec(
                'node', str(scraper_path), '--info',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(SCRAPERS_DIR),
            )
            info_stdout, _ = await asyncio.wait_for(info_result.communicate(), timeout=30)
            info_output = info_stdout.decode('utf-8', errors='replace')

            if info_result.returncode != 0:
                test_output += f'--info 测试失败:\n{info_output}\n'
                raise Exception('--info 测试失败')

            try:
                info_data = json.loads(info_output.strip())
                if 'name' not in info_data or 'modes' not in info_data:
                    raise Exception('--info JSON 格式错误')
            except json.JSONDecodeError:
                test_output += f'--info 输出不是合法 JSON:\n{info_output}\n'
                raise Exception('--info JSON 格式错误')

            latest_result = await asyncio.create_subprocess_exec(
                'node', str(scraper_path), '--latest', '1',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(SCRAPERS_DIR),
            )
            latest_stdout, _ = await asyncio.wait_for(latest_result.communicate(), timeout=120)
            latest_output = latest_stdout.decode('utf-8', errors='replace')

            if latest_result.returncode != 0:
                test_output += f'--latest 1 测试失败:\n{latest_output}\n'
                raise Exception('--latest 1 测试失败')

            if not output_json.exists():
                test_output += f'输出文件未生成: {output_json}\n'
                raise Exception('输出文件未生成')

            with open(output_json, 'r', encoding='utf-8') as f:
                data = json.load(f)

            if 'rows' not in data or len(data['rows']) == 0:
                test_output += '输出文件为空\n'
                raise Exception('输出文件为空')

            loop = asyncio.get_event_loop()
            quality_ok, quality_reason = await loop.run_in_executor(
                None,
                lambda: validate_data_quality_with_llm(data, url)
            )

            if not quality_ok:
                test_output += f'数据质量验证失败: {quality_reason}\n'
                raise Exception(f'数据质量验证失败: {quality_reason}')

            test_passed = True

        except Exception as e:
            test_passed = False

        if test_passed:
            task['status'] = 'success'
            task['scraper_name'] = scraper_name
            task['scraper_path'] = str(scraper_path)
            with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
                log_content = f.read()
            task['log_preview'] = log_content[-1000:] if log_content else ''
            return True
        else:
            task['error'] = f'{skill_name} 爬虫测试失败:\n{test_output}'
            with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
                log_content = f.read()
            task['log_preview'] = log_content[-1000:] if log_content else ''
            # 清理失败的爬虫文件
            if scraper_path.exists():
                scraper_path.unlink()
            if output_json.exists():
                output_json.unlink()
            return False

    except Exception as e:
        task['error'] = str(e)
        return False


async def run_hermes_generate(task_id: str, url: str, custom_name: Optional[str] = None, reference_urls: Optional[list[str]] = None):
    """后台任务：两步策略生成爬虫。Step 1: gen-scraper, Step 2: gen-scraper-browser (兜底)"""
    task = tasks[task_id]
    task['status'] = 'running'
    task['started_at'] = time.time()

    scraper_name = custom_name or derive_scraper_name(url)

    # ── Step 1: gen-scraper（HTTP API 方案）──
    task['message'] = '步骤1: 使用 gen-scraper（HTTP API 方案）'
    step1_ok = await _run_hermes_generate_step(task_id, url, custom_name, reference_urls, 'gen-scraper')

    if step1_ok:
        task['strategy_used'] = 'gen-scraper'
        task['finished_at'] = time.time()
        task['duration'] = task['finished_at'] - task['started_at']
        return

    # ── Step 2: gen-scraper-browser（Chrome CDP 兜底方案）──
    step1_error = task.get('error', '未知错误')
    task['step1_error'] = step1_error
    task['message'] = f'步骤2: gen-scraper 失败，切换到 gen-scraper-browser（Chrome CDP 兜底方案）'

    # 清理 Step 1 残留
    await _cleanup_scraper_files(scraper_name)

    task['status'] = 'running'
    step2_ok = await _run_hermes_generate_step(task_id, url, custom_name, reference_urls, 'gen-scraper-browser')

    task['finished_at'] = time.time()
    task['duration'] = task['finished_at'] - task['started_at']

    if step2_ok:
        task['strategy_used'] = 'gen-scraper-browser'
        task['status'] = 'success'
        task['message'] = '成功：使用 gen-scraper-browser（Chrome CDP 兜底方案）'
    else:
        task['strategy_used'] = 'both-failed'
        task['status'] = 'failed'
        task['error'] = f'两种方案均失败。\nStep1 (gen-scraper): {step1_error}\nStep2 (gen-scraper-browser): {task.get("error", "未知")}'


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
