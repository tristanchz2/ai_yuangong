"""通用工具函数"""

import re
import time
import fcntl
import contextlib
from pathlib import Path
from typing import Optional


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
        # 锁释放后清理锁文件，避免残留
        try:
            lock_path.unlink(missing_ok=True)
        except Exception:
            pass


def parse_date_str(value) -> Optional[str]:
    """将 LLM 输出的日期字符串解析为 YYYY-MM-DD 格式，无法解析则返回 None"""
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None
    # 已经是 YYYY-MM-DD
    m = re.match(r'^(\d{4})-(\d{1,2})-(\d{1,2})$', s)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    # YYYY/MM/DD
    m = re.match(r'^(\d{4})/(\d{1,2})/(\d{1,2})$', s)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    # YYYY年MM月DD日
    m = re.match(r'^(\d{4})年(\d{1,2})月(\d{1,2})日?$', s)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return None


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
    # 失败/取消类（优先匹配，避免被“招标”等词误判为采购公告）
    for kw in ("废标", "流标", "终止", "失败", "撤销", "取消"):
        if kw in title:
            return "其他"
    # 结果类关键词
    for kw in ("中标", "结果", "成交", "中选", "入围结果", "评标结果"):
        if kw in title:
            return "结果公告"
    # 采购类关键词（含变更/更正/延期/澄清等采购流程中的活跃公告）
    for kw in ("招标", "采购", "磋商", "单一来源", "征集", "更正", "谈判", "询价", "竞谈",
               "变更", "补充", "延期", "澄清", "重发", "资格预审", "邀请"):
        if kw in title:
            return "采购公告"
    return "其他"


def map_notice_code(code) -> str:
    """将 LLM 输出的数字分类映射为严格 enum"""
    try:
        c = int(code)
    except (ValueError, TypeError):
        return "其他"
    return {0: "采购公告", 1: "结果公告"}.get(c, "其他")


def map_raw_notice_type(raw: str) -> str:
    """将 raw_data 中已有的 noticeType/bidType 映射为严格 enum"""
    s = str(raw).strip()
    # 失败/取消类（优先匹配）
    for kw in ("废标", "流标", "终止", "失败", "撤销", "取消"):
        if kw in s:
            return "其他"
    # 结果类
    for kw in ("结果", "中标", "成交", "中选"):
        if kw in s:
            return "结果公告"
    # 采购类（含变更/更正/延期/澄清）
    for kw in ("招标", "采购", "磋商", "谈判", "征集", "更正", "询价", "竞谈", "单一来源",
               "变更", "补充", "延期", "澄清", "重发", "资格预审", "邀请"):
        if kw in s:
            return "采购公告"
    return "其他"
