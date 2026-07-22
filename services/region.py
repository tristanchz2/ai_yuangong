"""服务地区解析与规范化"""

from typing import Optional

from config.constants import PROVINCE_CITY_MAP, PROVINCE_LIST


def parse_service_region(raw: str | None) -> tuple:
    """
    校验并分离 "xx省xx市" 字符串（兼容 广东深圳 / 广东省深圳市 / 广东深圳
    等多种写法）。
    返回 (province, city)；省市对不上或无法识别则返回 (None, None)。
    """
    if not raw:
        return (None, None)
    s = raw.strip()
    if not s:
        return (None, None)

    def _clean_city(c: str) -> str:
        for suffix in ("市", "地区", "自治州", "盟"):
            if c.endswith(suffix) and len(c) > len(suffix):
                return c[:-len(suffix)]
        return c

    # 按已知省份前缀匹配（优先匹配较长的省名，如 黑龙江 > 河北）
    for province in sorted(PROVINCE_CITY_MAP.keys(), key=len, reverse=True):
        if not s.startswith(province):
            continue
        rest = s[len(province):]
        # 去掉省/自治区后缀
        for suffix in ("壮族自治区", "回族自治区", "维吾尔自治区", "自治区", "特别行政区", "省"):
            if rest.startswith(suffix):
                rest = rest[len(suffix):]
                break
        city = _clean_city(rest.strip())
        # 直辖市：省=市
        if province in ("北京", "天津", "上海", "重庆"):
            if city in (province, ""):
                return (province, province)
            continue
        cities = PROVINCE_CITY_MAP[province]
        if city in cities:
            return (province, city)
        # 模糊匹配：如 "深圳特区" → "深圳"
        for c in cities:
            if city and (city.startswith(c) or c.startswith(city)):
                return (province, c)
        # 省匹配上了但市对不上
        return (None, None)
    return (None, None)


# ──────────────────────────────────────────────
# 省份后处理：LLM 可能输出 "福建省"/"北京市" 等，统一修正为枚举值
# ──────────────────────────────────────────────
_PROVINCE_SUFFIXES = ("省", "市", "自治区", "壮族自治区", "回族自治区", "维吾尔自治区", "特别行政区")


def normalize_province(value: Optional[str]) -> Optional[str]:
    """将 LLM 输出的省份名称修正为枚举值，如 '福建省' -> '福建'，'北京市' -> '北京'"""
    if not value:
        return value
    v = value.strip()
    if v in PROVINCE_LIST:
        return v
    for suffix in _PROVINCE_SUFFIXES:
        if v.endswith(suffix):
            candidate = v[: -len(suffix)]
            if candidate in PROVINCE_LIST:
                return candidate
    return v  # 无法匹配，原样返回
