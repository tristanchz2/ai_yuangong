"""LLM 字段提取核心逻辑"""

import asyncio
import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import Optional

from openai import AsyncOpenAI

from config.constants import REQUEST_INTERVAL, BATCH_SIZE
from config.settings import RAW_DATA_DIR
from models.schemas import ExtractedFields
from core.utils import normalize_budget, infer_notice_type, map_notice_code, map_raw_notice_type
from services.region import normalize_province

# 生成 JSON Schema 供 prompt 中使用
EXTRACTION_SCHEMA = ExtractedFields.model_json_schema()

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


def set_cancel_file(path: Optional[Path]):
    """设置取消信号文件路径"""
    global _cancel_file_path
    _cancel_file_path = path


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


async def extract_batch(
    client: AsyncOpenAI,
    batch: list,  # [(index, row, content), ...]
    source: str,
    semaphore: asyncio.Semaphore,
    batch_label: str,
    subscription_keywords: list = None,  # [(id, word), ...]
) -> list:
    """
    批量提取：将多条公告打包成一次 LLM 调用，返回 [(index, extracted_dict), ...]。
    遇到 429 限流直接返回失败。
    extracted_dict 中额外包含 'subscription_matches' 字段: {word: 0/1}
    """
    # ★ 每次 LLM 调用前检查取消信号
    if _is_cancelled():
        print(f"  🛑 {batch_label}: 已取消，跳过 LLM 调用")
        return [(i, None) for i, _, _ in batch]

    model = os.environ.get("OPENAI_MODEL", "qwen3.7-plus")
    schema_desc = build_schema_description()

    # 构建订阅词匹配说明
    sub_keywords = subscription_keywords or []
    sub_prompt_section = ""
    if sub_keywords:
        words_list = "、".join([w for _, w in sub_keywords])
        sub_prompt_section = (
            f"\n\n★ 订阅词匹配：以下是用户订阅的关键词列表：【{words_list}】"
            f"\n请对每条公告判断是否与这些订阅词相关。在每条结果中额外添加一个 \"subscription_matches\" 字段，"
            f"它是一个对象，key 为订阅词，value 为 1（相关）或 0（不相关）。"
            f"\n示例：\"subscription_matches\": {{\"云计算\": 1, \"装修\": 0}}"
        )

    # 构建批量 prompt
    prompt_parts = [
        f"以下是 {len(batch)} 条公告，请逐条提取结构化信息。",
        f"\n⚠️ 重要：数据来源为多个银行/机构采购平台，其中可能包含非招标采购类文档（如新闻动态、内部制度、供应商征集公告、系统通知等）。请先判断每条文档是否为具体的招标/采购/中标类公告：如果不是，notice_type 直接填 2，其余字段可填 null，无需强行提取。",
        f"\n需要提取的字段及说明：\n{schema_desc}",
        sub_prompt_section,
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
        # ★ 调用前检查取消信号
        if _is_cancelled():
            print(f"  🛑 {batch_label}: 已取消，中止 LLM 调用")
            return [(i, None) for i, _, _ in batch]
        await _rate_limit()
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": "你是一个专业的公告信息提取助手。数据来源包含多个银行/机构采购平台，其中既有招标/采购/中标类公告，也可能混有新闻、制度、通知等非招标类文档。请根据正文内容判断文档类型，非招标采购类文档的 notice_type 填 2，其余字段填 null。请严格按照要求的 JSON 格式输出。只输出 JSON，不要输出其他内容。",
                    },
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0,
                extra_body={"enable_thinking": False},
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
            if "429" in err_str:
                print(f"  ❌ {batch_label}: 失败 - API 限流(429)，请求过于频繁，请稍后重试")
                return [(i, None) for i, _, _ in batch]
            print(f"  ❌ {batch_label}: 失败 - {e}")
            return [(i, None) for i, _, _ in batch]

    return [(i, None) for i, _, _ in batch]


async def process_file(
    client: AsyncOpenAI,
    file_path: Path,
    semaphore: asyncio.Semaphore,
    batch_size: int = BATCH_SIZE,
    subscription_keywords: list = None,
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
        extract_batch(client, batch, source, semaphore, label, subscription_keywords)
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
        # 预算转纯数字
        extracted["budget"] = normalize_budget(extracted.get("budget"))
        # 公告类型：LLM 判断优先
        llm_notice = map_notice_code(extracted.get("notice_type")) if extracted.get("notice_type") is not None else None
        raw_notice = row.get("noticeType") or row.get("bidType") or row.get("method")
        if llm_notice == "其他":
            extracted["notice_type"] = "其他"
        elif raw_notice:
            extracted["notice_type"] = map_raw_notice_type(raw_notice)
        elif llm_notice:
            extracted["notice_type"] = llm_notice
        else:
            extracted["notice_type"] = infer_notice_type(extracted.get("title", ""))
        # 从 raw_data 平移 url 和 content
        url = row.get("url") or row.get("sourceUrl") or None
        content_raw = row.get("content", "")
        # 保留原始发布日期（publishTime），用于按日期分组输出
        raw_publish_time = row.get("publishTime") or row.get("publish_time") or row.get("date") or ""
        # 提取订阅词匹配结果（不写入 JSON 文件，仅用于 DB 写入）
        sub_matches = extracted.pop("subscription_matches", None)
        result = {
            "source": source,
            "scrape_time": scrape_time,
            "raw_publish_time": raw_publish_time,
            "url": url,
            "content": content_raw,
            **extracted,
        }
        # 保留 subscription_matches 供后续 DB 写入使用
        if sub_matches:
            result["subscription_matches"] = sub_matches
        results.append(result)

    return results


# 导出取消检查函数供外部使用
is_cancelled = _is_cancelled
