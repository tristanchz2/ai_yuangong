#!/usr/bin/env python3
"""
公告字段提取器 - 使用 LLM JSON Schema 模式从 raw_data 中提取结构化字段

用法：
  python extract_fields.py                    # 处理所有 raw_data 文件
  python extract_fields.py --source ccb       # 只处理 ccb_data.json
  python extract_fields.py --source icbc,ccgp # 处理多个源
  python extract_fields.py --concurrency 3    # 设置并发数
  python extract_fields.py --batch-size 5     # 每次 LLM 调用处理的条数

输出：extracted_data/ 目录下的 JSON 文件
"""

import asyncio
import json
import os
import sys
import glob
import argparse
import signal
import time
import fcntl
from pathlib import Path
from typing import Optional, List, Literal
from pydantic import BaseModel, Field

from dotenv import load_dotenv
from openai import AsyncOpenAI

# ──────────────────────────────────────────────
# 加载环境变量
# ──────────────────────────────────────────────
load_dotenv(Path(__file__).parent / ".env")

# ──────────────────────────────────────────────
# 省份枚举（复用于多个字段）
# ──────────────────────────────────────────────
_PROVINCE_LIST = (
    "北京", "天津", "上海", "重庆",
    "河北", "山西", "辽宁", "吉林", "黑龙江",
    "江苏", "浙江", "安徽", "福建", "江西", "山东",
    "河南", "湖北", "湖南", "广东", "海南",
    "四川", "贵州", "云南", "陕西", "甘肃",
    "青海", "台湾",
    "内蒙古", "广西", "西藏", "宁夏", "新疆",
    "香港", "澳门", "其他",
)
Province = Literal[_PROVINCE_LIST]  # type: ignore

# ──────────────────────────────────────────────
# ★★★ 在这里编辑你要提取的字段 ★★★
#
# 修改 ExtractedFields 类即可：
#   - 增删字段
#   - 修改 description 来指导 LLM 如何提取
#   - 字段类型支持 str / Optional[str] / List[str] / Literal 等
# ──────────────────────────────────────────────

class ExtractedFields(BaseModel):
    """从招标公告/采购公告中提取的结构化字段"""

    title: str = Field(
        description="公告标题/项目名称"
    )
    notice_type: Optional[int] = Field(
        default=None,
        description="公告类型分类：0=采购/招标类公告（招标公告、采购公告、竞争性磋商、单一来源、征集、更正等），1=结果类公告（中标公告、成交公告、结果公告、评标结果等），2=其他/无法判断"
    )
    publish_time: Optional[str] = Field(
        default=None,
        description="公告发布日期，格式：YYYY-MM-DD，例如 2026-07-09"
    )
    bid_time: Optional[str] = Field(
        default=None,
        description="投标截止/开标时间，格式：YYYY-MM-DD，例如 2026-07-31"
    )
    summary: Optional[str] = Field(
        default=None,
        description="项目摘要，30字左右，简明扼要概括采购内容"
    )
    keywords: Optional[List[str]] = Field(
        default=None,
        description="关键词，2个左右，最多不超过4个。要求：不要包含地区/省份（如北京、江苏）、产品类别（如服务类、工程类）等重复信息，每个关键词应是具体的业务关键词"
    )
    budget: Optional[float] = Field(
        default=None,
        description="预算金额，纯数字，单位：元。例如 400000。如果是万元请换算成元"
    )
    purchaser: Optional[str] = Field(
        default=None,
        description="采购人/招标人名称（个人或单位名称）"
    )
    purchaser_region: Optional[Province] = Field(
        default=None,
        description="采购人所在省份（只能从枚举值中选择）"
    )
    service_category: Optional[str] = Field(
        default=None,
        description="服务类别，用一个词语概括，如：软件开发、装修工程、安保服务、设备采购等"
    )
    service_province: Optional[Province] = Field(
        default=None,
        description="服务所在地/项目实施地所在省份（只能从枚举值中选择）"
    )
    service_location: Optional[str] = Field(
        default=None,
        description="服务所在地具体地址，如：青岛市崂山区深圳路222号"
    )
    remarks: Optional[str] = Field(
        default=None,
        description="备注信息，包括联系人及联系方式、项目编号等需要备注的内容。没有则留空"
    )

# ──────────────────────────────────────────────
# ★★★ 字段定义结束 ★★★
# ──────────────────────────────────────────────


# ──────────────────────────────────────────────
# ★★★ 并发数配置 ★★★
# ──────────────────────────────────────────────
DEFAULT_CONCURRENCY = 3  # 默认并发数（文件级别），可通过 --concurrency 参数调整
REQUEST_INTERVAL = 1.0  # 每次请求之间的最小间隔（秒）
BATCH_SIZE = 5  # 每次 LLM 调用处理的公告条数

# 生成 JSON Schema 供 prompt 中使用
EXTRACTION_SCHEMA = ExtractedFields.model_json_schema()

PROJECT_ROOT = Path(__file__).parent
RAW_DATA_DIR = PROJECT_ROOT / "raw_data"
OUTPUT_DIR = PROJECT_ROOT / "extracted_data"

# ──────────────────────────────────────────────
# 文件锁工具：带超时 + 确保释放
# ──────────────────────────────────────────────
import contextlib


@contextlib.contextmanager
def file_lock(lock_path: Path, timeout: float = 30.0):
    """带超时的文件锁上下文管理器。
    - 使用 LOCK_NB 非阻塞尝试 + 轮询，避免无限等待
    - 无论正常退出、异常、SIGTERM，都确保锁被释放
    """
    lock_file = open(lock_path, "w")
    acquired = False
    try:
        deadline = time.time() + timeout
        while True:
            try:
                fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except (IOError, OSError):
                if time.time() >= deadline:
                    raise TimeoutError(f"获取文件锁超时: {lock_path}")
                time.sleep(0.2)
        yield lock_file
    finally:
        if acquired:
            try:
                fcntl.flock(lock_file, fcntl.LOCK_UN)
            except Exception:
                pass
        lock_file.close()

# ──────────────────────────────────────────────
# 省份后处理：LLM 可能输出 "福建省"/"北京市" 等，统一修正为枚举值
# ──────────────────────────────────────────────
_PROVINCE_SUFFIXES = ("省", "市", "自治区", "壮族自治区", "回族自治区", "维吾尔自治区", "特别行政区")

def normalize_province(value: Optional[str]) -> Optional[str]:
    """将 LLM 输出的省份名称修正为枚举值，如 '福建省' -> '福建'，'北京市' -> '北京'"""
    if not value:
        return value
    v = value.strip()
    if v in _PROVINCE_LIST:
        return v
    for suffix in _PROVINCE_SUFFIXES:
        if v.endswith(suffix):
            candidate = v[: -len(suffix)]
            if candidate in _PROVINCE_LIST:
                return candidate
    return v  # 无法匹配，原样返回


def normalize_budget(value) -> Optional[float]:
    """将 LLM 输出的预算值转为纯数字（元），如 '2935.32万' -> 29353200.0"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace(",", "").replace(" ", "")
    if not s:
        return None
    multiplier = 1
    if s.endswith("万"):
        multiplier = 10000
        s = s[:-1]
    elif s.endswith("亿"):
        multiplier = 100000000
        s = s[:-1]
    elif s.endswith("元"):
        s = s[:-1]
    try:
        return float(s) * multiplier
    except ValueError:
        return None


def infer_notice_type(title: str) -> str:
    """从标题关键词推断公告类型，不需要 LLM"""
    if not title:
        return "其他"
    # 结果类关键词（优先匹配）
    for kw in ("中标", "结果", "成交", "中选", "入围结果", "评标结果"):
        if kw in title:
            return "结果公告"
    # 采购类关键词
    for kw in ("招标", "采购", "磋商", "单一来源", "征集", "更正", "谈判", "询价", "竞谈"):
        if kw in title:
            return "采购公告"
    return "其他"


def _map_notice_code(code) -> str:
    """将 LLM 输出的数字分类映射为严格 enum"""
    try:
        c = int(code)
    except (ValueError, TypeError):
        return "其他"
    return {0: "采购公告", 1: "结果公告"}.get(c, "其他")


def _map_raw_noticeType(raw: str) -> str:
    """将 raw_data 中已有的 noticeType/bidType 映射为严格 enum"""
    s = str(raw).strip()
    # 结果类
    for kw in ("结果", "中标", "成交", "中选"):
        if kw in s:
            return "结果公告"
    # 采购类
    for kw in ("招标", "采购", "磋商", "谈判", "征集", "更正", "询价", "竞谈", "单一来源"):
        if kw in s:
            return "采购公告"
    return "其他"


def get_client() -> AsyncOpenAI:
    """创建异步 OpenAI 客户端"""
    api_key = os.environ.get("OPENAI_API_KEY")
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    if not api_key:
        raise RuntimeError("未设置 OPENAI_API_KEY，请在 .env 中配置")
    return AsyncOpenAI(api_key=api_key, base_url=base_url)


def build_schema_description() -> str:
    """从 Pydantic model 生成人类可读的字段说明，嵌入 prompt"""
    lines = []
    for name, field_info in ExtractedFields.model_fields.items():
        desc = field_info.description or ""
        required = field_info.is_required()
        type_str = "必填" if required else "可选，找不到填null"
        lines.append(f"  - {name}: {desc} ({type_str})")
    return "\n".join(lines)


# ──────────────────────────────────────────────
# 全局取消机制：SIGTERM 信号 + 取消信号文件
# ──────────────────────────────────────────────
_cancelled = False
_cancel_file_path: Optional[Path] = None


def _handle_sigterm(signum, frame):
    """收到 SIGTERM 信号时优雅退出"""
    global _cancelled
    _cancelled = True
    print("\n🛑 收到终止信号(SIGTERM)，立即停止...")
    sys.exit(1)


def _is_cancelled() -> bool:
    """检查是否已被取消（全局标志 + 取消信号文件）"""
    global _cancelled
    if _cancelled:
        return True
    if _cancel_file_path and _cancel_file_path.exists():
        _cancelled = True
        return True
    return False


# 注册 SIGTERM 处理（batch_scraper.py 会先发 SIGTERM 再 kill）
signal.signal(signal.SIGTERM, _handle_sigterm)

# 全局限流器：控制请求发送速率，避免触发 API 限流
_rate_limiter_lock = asyncio.Lock()
_last_request_time = 0.0


async def _rate_limit():
    """确保两次请求之间至少有 REQUEST_INTERVAL 秒的间隔"""
    global _last_request_time
    async with _rate_limiter_lock:
        now = asyncio.get_event_loop().time()
        wait = REQUEST_INTERVAL - (now - _last_request_time)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_request_time = asyncio.get_event_loop().time()


async def extract_batch(
    client: AsyncOpenAI,
    batch: list,  # [(index, row, content), ...]
    source: str,
    semaphore: asyncio.Semaphore,
    batch_label: str,
    max_retries: int = 3,
) -> list:
    """
    批量提取：将多条公告打包成一次 LLM 调用，返回 [(index, extracted_dict), ...]。
    支持 429 限流自动重试。
    """
    # ★ 每次 LLM 调用前检查取消信号
    if _is_cancelled():
        print(f"  🛑 {batch_label}: 已取消，跳过 LLM 调用")
        return [(i, None) for i, _, _ in batch]

    model = os.environ.get("OPENAI_MODEL", "qwen3.7-plus")
    schema_desc = build_schema_description()

    # 构建批量 prompt
    prompt_parts = [
        f"以下是 {len(batch)} 条招标/采购公告，请逐条提取结构化信息。",
        f"\n需要提取的字段及说明：\n{schema_desc}",
        "\n输出格式：JSON 对象，包含一个 'results' 数组，每个元素对应一条公告，顺序必须与输入一致。",
        "如果某字段找不到，填 null。只输出 JSON，不要输出其他内容。",
    ]

    for idx, (i, row, content) in enumerate(batch):
        meta = {k: v for k, v in row.items() if k != "content" and v}
        meta_str = f"\n  元数据：{json.dumps(meta, ensure_ascii=False)}" if meta else ""
        prompt_parts.append(f"\n--- 第 {idx+1} 条（共 {len(batch)} 条）---{meta_str}")
        prompt_parts.append(f"公告正文：\n{content[:4000]}")  # 批量模式每条截断更短

    prompt = "\n".join(prompt_parts)

    async with semaphore:
        for attempt in range(1, max_retries + 1):
            # ★ 重试前也检查取消信号
            if _is_cancelled():
                print(f"  🛑 {batch_label}: 已取消，中止重试")
                return [(i, None) for i, _, _ in batch]
            await _rate_limit()
            try:
                response = await client.chat.completions.create(
                    model=model,
                    messages=[
                        {
                            "role": "system",
                            "content": "你是一个专业的招标公告信息提取助手。请严格按照要求的 JSON 格式输出提取结果。只输出 JSON，不要输出其他内容。",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0,
                )

                result_text = response.choices[0].message.content
                result_data = json.loads(result_text)

                # 兼容处理：LLM 可能返回 {"results": [...]} 或直接 [...]
                if isinstance(result_data, dict):
                    # 找到第一个 list 类型的值
                    for v in result_data.values():
                        if isinstance(v, list):
                            result_data = v
                            break
                    else:
                        result_data = [result_data]

                # 按顺序配对
                results = []
                for idx, (i, row, content) in enumerate(batch):
                    if idx < len(result_data):
                        extracted = result_data[idx]
                        title_preview = extracted.get("title", "N/A")[:30]
                        print(f"  ✅ 第{i+1}条: 完成 (标题: {title_preview})")
                        results.append((i, extracted))
                    else:
                        print(f"  ⚠️ 第{i+1}条: LLM 返回数量不足，跳过")
                        results.append((i, None))

                print(f"  📦 {batch_label}: 批量完成 {len(batch)} 条")
                return results

            except Exception as e:
                err_str = str(e)
                if "429" in err_str and attempt < max_retries:
                    wait_secs = 3 * attempt
                    print(f"  ⏳ {batch_label}: 限流(429)，{wait_secs}s 后重试 ({attempt}/{max_retries})...")
                    await asyncio.sleep(wait_secs)
                    continue
                print(f"  ❌ {batch_label}: 失败 - {e}")
                return [(i, None) for i, _, _ in batch]

    return [(i, None) for i, _, _ in batch]


async def process_file(
    client: AsyncOpenAI,
    file_path: Path,
    semaphore: asyncio.Semaphore,
    batch_size: int = BATCH_SIZE,
) -> list:
    """处理单个 raw_data 文件，批量提取所有条目"""
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    source = data.get("source", file_path.stem)
    scrape_time = data.get("scrapeTime", "")
    rows = data.get("rows", [])

    print(f"\n📂 处理文件: {file_path.name} (来源: {source}, 共 {len(rows)} 条)")

    # 过滤掉内容过短的条目
    valid_items = []
    for i, row in enumerate(rows):
        content = row.get("content", "")
        if not content or len(content.strip()) < 20:
            print(f"  ⏭️  第 {i+1} 条: 内容过短，跳过")
            continue
        valid_items.append((i, row, content))

    if not valid_items:
        return []

    # 分批
    batches = []
    for start in range(0, len(valid_items), batch_size):
        batch = valid_items[start:start + batch_size]
        batch_label = f"{file_path.stem}[{start+1}-{start+len(batch)}]"
        batches.append((batch, batch_label))

    # 并发执行所有批次
    batch_coros = [
        extract_batch(client, batch, source, semaphore, label)
        for batch, label in batches
    ]
    batch_results = await asyncio.gather(*batch_coros)

    # 展平结果
    all_extracted = {}  # index -> extracted_dict
    for results in batch_results:
        for i, extracted in results:
            if extracted is not None:
                all_extracted[i] = extracted

    # 组装结果：LLM 提取字段 + 从 raw_data 平移的字段
    results = []
    for i, row, content in valid_items:
        extracted = all_extracted.get(i)
        if extracted is None:
            continue
        # 修正省份字段（LLM 可能输出 "福建省" → "福建"）
        extracted["purchaser_region"] = normalize_province(extracted.get("purchaser_region"))
        extracted["service_province"] = normalize_province(extracted.get("service_province"))
        # 预算转纯数字
        extracted["budget"] = normalize_budget(extracted.get("budget"))
        # 公告类型：优先用 raw_data 已有的 noticeType，否则用 LLM 输出的数字映射，最后 fallback 到标题推断
        raw_notice = row.get("noticeType") or row.get("bidType") or row.get("method")
        if raw_notice:
            extracted["notice_type"] = _map_raw_noticeType(raw_notice)
        elif extracted.get("notice_type") is not None:
            extracted["notice_type"] = _map_notice_code(extracted["notice_type"])
        else:
            extracted["notice_type"] = infer_notice_type(extracted.get("title", ""))
        # 从 raw_data 平移 url 和 content
        url = row.get("url") or row.get("sourceUrl") or None
        content_raw = row.get("content", "")
        # 保留原始发布日期（publishTime），用于按日期分组输出
        raw_publish_time = row.get("publishTime") or row.get("publish_time") or row.get("date") or ""
        result = {
            "source": source,
            "scrape_time": scrape_time,
            "raw_publish_time": raw_publish_time,
            "url": url,
            "content": content_raw,
            **extracted,
        }
        results.append(result)

    return results


async def async_main():
    parser = argparse.ArgumentParser(description="从 raw_data 中提取公告字段")
    parser.add_argument(
        "--source",
        type=str,
        default=None,
        help="指定要处理的源名称（逗号分隔），如 ccb,icbc。不指定则处理所有文件。",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="输出文件名（默认: extracted_all.json）",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=DEFAULT_CONCURRENCY,
        help=f"并发数（默认 {DEFAULT_CONCURRENCY}）",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=BATCH_SIZE,
        help=f"每次 LLM 调用处理的公告条数（默认 {BATCH_SIZE}）",
    )
    parser.add_argument(
        "--suffix",
        type=str,
        default=None,
        help="输出文件名后缀（如 abc_puc_1234），用于区分不同运行。不加后缀则按日期覆盖。",
    )
    parser.add_argument(
        "--cancel-file",
        type=str,
        default=None,
        help="取消信号文件路径。如果该文件存在，则跳过写入。",
    )
    args = parser.parse_args()

    # ★ 设置全局取消信号文件路径，供 _is_cancelled() 检查
    global _cancel_file_path
    if args.cancel_file:
        _cancel_file_path = Path(args.cancel_file)

    # 确定要处理的文件
    if args.source:
        sources = [s.strip() for s in args.source.split(",")]
        files = []
        for src in sources:
            pattern = RAW_DATA_DIR / f"{src}_data.json"
            matched = glob.glob(str(pattern))
            if matched:
                files.append(Path(matched[0]))
            else:
                print(f"⚠️  未找到匹配文件: {pattern}")
    else:
        files = sorted(RAW_DATA_DIR.glob("*_data.json"))

    if not files:
        print("❌ 没有要处理的文件")
        return

    # 统计总条目数
    total_items = 0
    for fp in files:
        with open(fp) as f:
            d = json.load(f)
            total_items += len(d.get("rows", []))

    print(f"🚀 共 {len(files)} 个文件, {total_items} 条记录待处理")
    print(f"⚡ 并发数: {args.concurrency}, 批次大小: {args.batch_size}")

    # 创建输出目录
    OUTPUT_DIR.mkdir(exist_ok=True)

    client = get_client()
    semaphore = asyncio.Semaphore(args.concurrency)

    start_time = time.time()

    # 所有文件的所有条目并发处理（跨文件也并发）
    all_file_coros = [process_file(client, fp, semaphore, batch_size=args.batch_size) for fp in files]
    all_file_results = await asyncio.gather(*all_file_coros)

    # ★ LLM 完成后立即检查取消信号，避免已取消的任务还写入数据
    if _is_cancelled():
        print(f"\n🛑 LLM 提取完成后检测到取消信号，跳过数据写入")
        return

    all_results = []
    for results in all_file_results:
        all_results.extend(results)

    elapsed = time.time() - start_time

    # 按 notice_type 分组保存到不同文件夹
    folders = {
        "采购公告": OUTPUT_DIR / "采购公告",
        "结果公告": OUTPUT_DIR / "结果公告",
        "其他": OUTPUT_DIR / "其他",
    }
    for folder in folders.values():
        folder.mkdir(parents=True, exist_ok=True)

    # 按数据的发布日期（publishTime）分组，而不是爬虫运行时间
    date_groups = {}  # {date_str: {notice_type: [records]}}
    for r in all_results:
        # 优先用 raw_publish_time（数据实际发布日期），fallback 到 scrape_time
        raw_pt = (r.get("raw_publish_time") or "")[:10]
        if raw_pt and len(raw_pt) == 10 and raw_pt[0] == "2":
            data_date = raw_pt
        else:
            data_date = (r.get("scrape_time") or "")[:10]
        if not data_date or len(data_date) < 10:
            data_date = "unknown"
        nt = r.get("notice_type", "其他")
        if nt not in ("采购公告", "结果公告", "其他"):
            nt = "其他"
        if data_date not in date_groups:
            date_groups[data_date] = {"采购公告": [], "结果公告": [], "其他": []}
        date_groups[data_date][nt].append(r)

    # 保存到对应文件夹，按日期合并（同一天同一类型合并，不同天保留）
    folders = {
        "采购公告": OUTPUT_DIR / "采购公告",
        "结果公告": OUTPUT_DIR / "结果公告",
        "其他": OUTPUT_DIR / "其他",
    }
    for folder in folders.values():
        folder.mkdir(parents=True, exist_ok=True)

    # ── 写入前检查取消信号（统一用 _is_cancelled）──
    if _is_cancelled():
        print(f"\n🛑 检测到取消信号，跳过数据写入")
        return

    saved_count = 0
    for date_str, type_groups in date_groups.items():
        for notice_type, new_records in type_groups.items():
            if not new_records:
                continue
            # 每个文件写入前都检查取消信号
            if _is_cancelled():
                print(f"\n🛑 检测到取消信号，停止写入（已保存 {saved_count} 条）")
                break
            folder = folders[notice_type]
            output_path = folder / f"{date_str}.json"

            # 用文件锁保证并发安全（带超时 + 确保释放）
            lock_path = folder / f".{date_str}_{notice_type}.lock"
            try:
                with file_lock(lock_path, timeout=30.0):
                    # 读取已有数据
                    existing_records = []
                    if output_path.exists():
                        try:
                            with open(output_path, "r", encoding="utf-8") as f:
                                old_data = json.load(f)
                                existing_records = old_data.get("records", [])
                        except Exception:
                            existing_records = []

                    # 提取本次新数据的源列表
                    new_sources = set(r.get("source", "") for r in new_records)

                    # 保留来自不同源的旧数据，替换同源旧数据
                    kept_old = [r for r in existing_records if r.get("source", "") not in new_sources]
                    merged = kept_old + new_records

                    with open(output_path, "w", encoding="utf-8") as f:
                        json.dump(
                            {
                                "extractedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                "scrapeDate": date_str,
                                "noticeType": notice_type,
                                "totalRecords": len(merged),
                                "records": merged,
                            },
                            f,
                            ensure_ascii=False,
                            indent=2,
                        )
                    saved_count += len(new_records)
                    print(f"  📁 {notice_type} ({date_str}): 新增 {len(new_records)} 条，合并后共 {len(merged)} 条 -> {output_path.name}")
            except TimeoutError as e:
                print(f"  ⚠️ {notice_type} ({date_str}): {e}，跳过写入")
            except Exception as e:
                print(f"  ❌ {notice_type} ({date_str}): 写入失败 - {e}")

    print(f"\n✅ 提取完成！共 {saved_count} 条记录")
    print(f"📂 输出目录: {OUTPUT_DIR}")
    print(f"⏱️  耗时: {elapsed:.1f}s")


if __name__ == "__main__":
    asyncio.run(async_main())
