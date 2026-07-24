"""所有 Pydantic 模型定义"""

from typing import Optional, List

from pydantic import BaseModel, Field

from config.constants import Province


# ──────────────────────────────────────────────
# LLM 提取字段模型
# ──────────────────────────────────────────────

class ExtractedFields(BaseModel):
    """从招标公告/采购公告中提取的结构化字段"""

    title: str = Field(
        description="公告标题/项目名称"
    )
    notice_type: Optional[int] = Field(
        default=None,
        description=(
            "公告类型分类："
            "0=采购公告（招标、采购、竞争性磋商、竞争性谈判、询价、单一来源、资格预审、邀请招标、"
            "变更公告、更正公告、补充公告、延期公告、澄清公告、重发公告等采购流程中的活跃公告），"
            "1=结果公告（中标、成交、结果、评标结果、中选、入围结果等），"
            "2=其他（废标、流标、终止、失败、撤销等采购失败/取消类公告，"
            "以及新闻、制度、通知、供应商征集等非具体招标采购项目的文档）。"
            "注意：变更/更正/延期/澄清属于采购公告(0)，废标/终止/流标/失败/撤销属于其他(2)"
        )
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
    service_region: Optional[str] = Field(
        default=None,
        description="服务所在地/项目实施地，格式为'省+市'拼接，如'广东深圳'、'江苏省南京市'、'北京北京'（直辖市省和市相同）。要求：省和市必须真实匹配（如深圳必须配广东）；若无法确定具体省市则留空"
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
# 管理员路由模型
# ──────────────────────────────────────────────

class LoginRequest(BaseModel):
    password: str


class LoginResponse(BaseModel):
    token: str
    message: str


class SiteCreate(BaseModel):
    name: str = Field(min_length=1, max_length=15, description="网站名称，最多15个字")
    url: str = Field(max_length=500)
    scraper_name: Optional[str] = Field(default=None, max_length=50, pattern=r'^[a-zA-Z0-9_]+$', description="爬虫名称，仅允许英文、数字、下划线")
    description: Optional[str] = Field(default=None, max_length=100)
    aliases: Optional[List[str]] = Field(default=None, description="搜索别名列表，用于模糊搜索（如官方名/简称）")
    reference_urls: Optional[list[str]] = None


class SiteUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=15, description="网站名称，最多15个字")
    description: Optional[str] = Field(default=None, max_length=100)
    aliases: Optional[List[str]] = Field(default=None, description="搜索别名列表，用于模糊搜索（如官方名/简称）")


class KeywordCreate(BaseModel):
    word: str


# ──────────────────────────────────────────────
# 爬虫生成路由模型
# ──────────────────────────────────────────────

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
