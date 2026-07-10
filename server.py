#!/usr/bin/env python3
"""
爬虫生成服务 - 接收 URL，调用 Hermes 自动生成爬虫

启动：
  uvicorn server:app --reload --port 8000

API：
  POST /generate
  Body: {"url": "https://example.com"}
  
  GET /status
  查看任务状态
"""

import asyncio
import json
import subprocess
import time
import os
from pathlib import Path
from typing import Optional, Dict, Any

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

app = FastAPI(title="爬虫生成服务")

# 项目根目录
PROJECT_ROOT = Path(__file__).parent
STATIC_DIR = PROJECT_ROOT / "static"
EXTRACTED_DATA_DIR = PROJECT_ROOT / "extracted_data"
SCRAPERS_DIR = PROJECT_ROOT / "scrapers"

# 数据分类
DATA_CATEGORIES = ["采购公告", "结果公告", "其他"]

# 加载 .env
def _load_env():
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, val = line.split('=', 1)
                    os.environ.setdefault(key.strip(), val.strip())

_load_env()

def validate_data_quality_with_llm(data: Dict[str, Any], source_url: str) -> tuple[bool, str]:
    """
    用 LLM 验证爬虫数据质量（同步函数）
    返回 (是否通过, 原因)
    """
    api_key = os.environ.get('OPENAI_API_KEY')
    base_url = os.environ.get('OPENAI_BASE_URL', 'https://api.openai.com/v1')
    model = os.environ.get('OPENAI_MODEL', 'gpt-4o-mini')
    
    if not api_key:
        # 如果没有 API key，降级到基础检查
        return fallback_quality_check(data)
    
    try:
        # 构建验证 prompt
        rows_sample = data['rows'][:3]  # 只取前 3 条作为样本
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
2. 数据内容要有实际价值（不是乱码或无意义内容）
3. 字段结构合理（有 title, url, date 等基本信息）
4. 如果是公告/文章类，content 应该包含正文内容，不能只是重复标题

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
        
        result_text = result_text.strip()
        result = json.loads(result_text)
        is_valid = result.get('valid', False)
        reason = result.get('reason', '未知原因')
        return (is_valid, reason)
            
    except Exception as e:
        # LLM 调用失败，降级到基础检查
        print(f"LLM 验证失败，降级到基础检查: {e}")
        return fallback_quality_check(data)


def fallback_quality_check(data: Dict[str, Any]) -> tuple[bool, str]:
    """降级的基础质量检查"""
    if not data.get('rows'):
        return False, "数据为空"
    
    first_row = data['rows'][0]
    content = first_row.get('content', '')
    title = first_row.get('title', '')
    
    # 基础检查
    if not content or len(content) < 10:
        return False, "content 字段为空或过短"
    
    if content.strip() == title.strip():
        return False, "content 等于标题"
    
    # 检查是否有实质性内容（至少有一些长度）
    if len(content) < 50:
        return False, f"content 过短（{len(content)} 字符）"
    
    return True, "基础检查通过"

# 任务状态存储（简单内存存储，生产环境应换 Redis/DB）
tasks = {}


class GenerateRequest(BaseModel):
    url: str
    name: Optional[str] = None  # 可选，指定爬虫名称


class GenerateResponse(BaseModel):
    task_id: str
    status: str
    message: str


class TaskStatus(BaseModel):
    task_id: str
    status: str  # pending, running, success, failed
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
    
    # Handle two-part TLDs like .com.cn, .co.uk, .org.au
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


async def run_hermes_generate(task_id: str, url: str, custom_name: Optional[str] = None):
    """后台任务：调用 Hermes 生成爬虫，测试通过才算成功"""
    task = tasks[task_id]
    task['status'] = 'running'
    task['started_at'] = time.time()
    
    # 创建日志文件
    log_file = PROJECT_ROOT / "logs" / f"{task_id}.log"
    log_file.parent.mkdir(exist_ok=True)
    task['log_file'] = str(log_file)
    
    process = None
    scraper_name = custom_name or derive_scraper_name(url)
    scraper_path = SCRAPERS_DIR / f"scrape_{scraper_name}.js"
    output_json = PROJECT_ROOT / "raw_data" / f"{scraper_name}_data.json"
    
    try:
        # 检查爬虫是否已存在
        if scraper_path.exists():
            task['status'] = 'failed'
            task['error'] = f'爬虫已存在: {scraper_path}'
            task['finished_at'] = time.time()
            task['duration'] = task['finished_at'] - task['started_at']
            return
        
        # 构建 Hermes 命令
        prompt = f"帮我爬这个网站：{url}，爬虫名称用 {scraper_name}"
        
        cmd = [
            'hermes', 'chat',
            '-q', prompt,
            '-s', 'gen-scraper',
        ]
        
        # 用 Popen 实时读取日志
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(PROJECT_ROOT),
        )
        assert process.stdout is not None, "stdout pipe failed"
        
        # 实时写日志文件
        with open(log_file, 'w', encoding='utf-8') as f:
            while True:
                try:
                    # 超时 900 秒（15 分钟）
                    line = await asyncio.wait_for(process.stdout.readline(), timeout=900.0)
                    if not line:
                        if process.returncode is not None:
                            break
                        continue
                    decoded = line.decode('utf-8', errors='replace')
                    f.write(decoded)
                    f.flush()
                except asyncio.TimeoutError:
                    # 15 分钟超时
                    task['status'] = 'failed'
                    task['error'] = 'Hermes 执行超时（>15分钟）'
                    task['finished_at'] = time.time()
                    task['duration'] = task['finished_at'] - task['started_at']
                    process.kill()
                    await process.wait()
                    return
                except Exception as e:
                    # readline 返回 EOF 或其他错误
                    if process.returncode is not None:
                        break
                    continue
        
        # 等待进程结束
        try:
            await asyncio.wait_for(process.wait(), timeout=10)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
        
        task['finished_at'] = time.time()
        task['duration'] = task['finished_at'] - task['started_at']
        
        # 读取日志
        with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
            log_content = f.read()
        
        if process.returncode != 0:
            task['status'] = 'failed'
            task['error'] = log_content[-2000:] or f'Hermes 退出码 {process.returncode}'
            return
        
        # 检查是否生成了爬虫文件
        if not scraper_path.exists():
            task['status'] = 'failed'
            task['error'] = f'爬虫文件未生成: {scraper_path}'
            task['log_preview'] = log_content[-1000:] if log_content else ''
            return
        
        # 运行测试：--info 和 --latest 1
        test_passed = False
        test_output = ''
        
        try:
            # 测试 1: --info
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
            
            # 验证 JSON 格式
            try:
                info_data = json.loads(info_output.strip())
                if 'name' not in info_data or 'modes' not in info_data:
                    raise Exception('--info JSON 格式错误')
            except json.JSONDecodeError:
                test_output += f'--info 输出不是合法 JSON:\n{info_output}\n'
                raise Exception('--info JSON 格式错误')
            
            # 测试 2: --latest 1
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
            
            # 检查输出文件是否生成
            if not output_json.exists():
                test_output += f'输出文件未生成: {output_json}\n'
                raise Exception('输出文件未生成')
            
            # 用 LLM 验证数据质量
            with open(output_json, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if 'rows' not in data or len(data['rows']) == 0:
                test_output += '输出文件为空\n'
                raise Exception('输出文件为空')
            
            # 调用 LLM 验证数据质量
            loop = asyncio.get_event_loop()
            quality_ok, quality_reason = await loop.run_in_executor(
                None, 
                lambda: validate_data_quality_with_llm(data, url)
            )
            
            if not quality_ok:
                test_output += f'数据质量验证失败: {quality_reason}\n'
                raise Exception(f'数据质量验证失败: {quality_reason}')
            
            # 所有测试通过
            test_passed = True
            
        except Exception as e:
            test_passed = False
        
        # 判断结果
        if test_passed:
            task['status'] = 'success'
            task['scraper_name'] = scraper_name
            task['scraper_path'] = str(scraper_path)
            task['log_preview'] = log_content[-1000:] if log_content else ''
        else:
            # 测试失败，清理文件
            task['status'] = 'failed'
            task['error'] = f'爬虫测试失败:\n{test_output}'
            task['log_preview'] = log_content[-1000:] if log_content else ''
            
            # 删除生成的文件
            if scraper_path.exists():
                scraper_path.unlink()
            if output_json.exists():
                output_json.unlink()
            
    except Exception as e:
        task['status'] = 'failed'
        task['error'] = str(e)
        task['finished_at'] = time.time()
        task['duration'] = task['finished_at'] - task['started_at']


@app.post("/generate", response_model=GenerateResponse)
async def generate_scraper(req: GenerateRequest):
    """
    生成爬虫
    
    接收 URL，启动后台任务调用 Hermes 生成爬虫代码。
    返回 task_id，用 /status/{task_id} 查询进度。
    """
    # 验证 URL 格式
    from urllib.parse import urlparse
    parsed = urlparse(req.url)
    if not parsed.scheme or not parsed.netloc:
        raise HTTPException(status_code=400, detail=f"URL 格式错误: {req.url}")
    
    # 清洗 URL（去掉重复的 scheme）
    clean_url = req.url
    if '://' in req.url:
        idx = req.url.index('://')
        prefix = req.url[:idx]
        if ':' in prefix:
            # 前面有多余内容，例如 https:https://... 
            # 保留第一个 scheme，从 :// 之后开始
            first_colon = prefix.index(':')
            scheme = prefix[:first_colon]
            rest = req.url[idx+3:]
            clean_url = f"{scheme}://{rest}"
    else:
        # 没有 ://，可能是 https:... 格式
        if req.url.startswith('https:'):
            clean_url = 'https://' + req.url[6:]
        elif req.url.startswith('http:'):
            clean_url = 'http://' + req.url[5:]
    
    # 生成任务 ID
    task_id = f"task_{int(time.time() * 1000)}"
    
    # 创建任务记录
    tasks[task_id] = {
        'task_id': task_id,
        'status': 'pending',
        'url': clean_url,
        'scraper_name': None,
        'scraper_path': None,
        'error': None,
        'started_at': None,
        'finished_at': None,
        'duration': None,
        'hermes_output': '',
    }
    
    # 启动后台任务
    asyncio.create_task(run_hermes_generate(task_id, clean_url, req.name))
    
    return GenerateResponse(
        task_id=task_id,
        status='pending',
        message=f'任务已创建，正在生成爬虫。用 GET /status/{task_id} 查询进度。'
    )


@app.get("/status/{task_id}", response_model=TaskStatus)
async def get_status(task_id: str):
    """查询任务状态"""
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    task = tasks[task_id]
    return TaskStatus(**task)


@app.get("/status")
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


@app.get("/logs/{task_id}")
async def get_logs(task_id: str):
    """读取任务日志（实时）"""
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


@app.get("/api/categories")
async def get_categories():
    """返回所有数据分类及其记录数"""
    categories = []
    for cat in DATA_CATEGORIES:
        cat_dir = EXTRACTED_DATA_DIR / cat
        if cat_dir.exists() and cat_dir.is_dir():
            json_files = list(cat_dir.glob("*.json"))
            total_records = 0
            latest_time = None
            for jf in json_files:
                try:
                    with open(jf, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        total_records += data.get("totalRecords", 0)
                        ext_time = data.get("extractedAt")
                        if ext_time and (not latest_time or ext_time > latest_time):
                            latest_time = ext_time
                except:
                    pass
            categories.append({
                "name": cat,
                "fileCount": len(json_files),
                "totalRecords": total_records,
                "latestExtractedAt": latest_time
            })
    return {"categories": categories}


@app.get("/api/data/{category}")
async def get_category_data(category: str):
    """读取指定分类的所有 JSON 数据"""
    if category not in DATA_CATEGORIES:
        raise HTTPException(status_code=404, detail=f"分类不存在: {category}")
    cat_dir = EXTRACTED_DATA_DIR / category
    if not cat_dir.exists():
        raise HTTPException(status_code=404, detail="分类目录不存在")
    
    all_records = []
    for jf in sorted(cat_dir.glob("*.json")):
        try:
            with open(jf, "r", encoding="utf-8") as f:
                data = json.load(f)
                records = data.get("records", [])
                all_records.extend(records)
        except:
            pass
    
    return {
        "category": category,
        "totalRecords": len(all_records),
        "records": all_records
    }


@app.get("/")
async def root():
    """前端页面"""
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="前端页面不存在")
    return FileResponse(index_path, media_type="text/html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
