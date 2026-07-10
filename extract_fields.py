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
import glob
import argparse
import time
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
        description="关键词，不超过4个，每个关键词是一个简短词语"
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
        result = {
            "source": source,
            "scrape_time": scrape_time,
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
    args = parser.parse_args()

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

    all_results = []
    for results in all_file_results:
        all_results.extend(results)

    elapsed = time.time() - start_time

    # 保存结果
    output_name = args.output or "extracted_all.json"
    output_path = OUTPUT_DIR / output_name
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "extractedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "totalRecords": len(all_results),
                "records": all_results,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    print(f"\n✅ 提取完成！共 {len(all_results)} 条记录")
    print(f"📄 输出文件: {output_path}")
    print(f"⏱️  耗时: {elapsed:.1f}s")


if __name__ == "__main__":
    asyncio.run(async_main())
