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
                except Exception:
                    pass
            categories.append({
                "name": cat,
                "fileCount": len(json_files),
                "totalRecords": total_records,
                "latestExtractedAt": latest_time
            })
    return {"categories": categories}


@router.get("/data/{category}")
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
        except Exception:
            pass

    return {
        "category": category,
        "totalRecords": len(all_records),
        "records": all_records
    }
