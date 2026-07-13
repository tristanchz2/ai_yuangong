"""数据展示路由 - 分类列表 & 分类数据"""

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api", tags=["数据展示"])

# 从 config 导入
PROJECT_ROOT = Path(__file__).parent.parent
EXTRACTED_DATA_DIR = PROJECT_ROOT / "extracted_data"
DATA_CATEGORIES = ["采购公告", "结果公告", "其他"]


@router.get("/categories")
async def get_categories():
    """返回所有数据分类及其记录数"""
    categories = []
    for cat in DATA_CATEGORIES:
        cat_dir = EXTRACTED_DATA_DIR / cat
        if cat_dir.exists() and cat_dir.is_dir():
            # 递归扫描所有源子目录下的 JSON 文件
            json_files = list(cat_dir.rglob("*.json"))
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
                except Exception:
                    pass
            # 统计源数量（子目录数 + 根目录下的文件）
            source_count = len([d for d in cat_dir.iterdir() if d.is_dir() and not d.name.startswith('.')])
            if source_count == 0:
                # 兼容旧结构：没有子目录，按文件数算
                source_count = len([f for f in cat_dir.glob("*.json")])
            categories.append({
                "name": cat,
                "fileCount": source_count,
                "totalRecords": total_records,
                "latestExtractedAt": latest_time
            })
    return {"categories": categories}


@router.get("/data/{category}")
async def get_category_data(category: str):
    """读取指定分类的所有 JSON 数据（递归扫描所有源子目录）"""
    if category not in DATA_CATEGORIES:
        raise HTTPException(status_code=404, detail=f"分类不存在: {category}")
    cat_dir = EXTRACTED_DATA_DIR / category
    if not cat_dir.exists():
        raise HTTPException(status_code=404, detail="分类目录不存在")

    all_records = []
    # 递归扫描所有源子目录下的 JSON 文件
    for jf in sorted(cat_dir.rglob("*.json")):
        try:
            with open(jf, "r", encoding="utf-8") as f:
                data = json.load(f)
                records = data.get("records", [])
                all_records.extend(records)
        except Exception:
            pass

    return {
        "category": category,
        "totalRecords": len(all_records),
        "records": all_records
    }
