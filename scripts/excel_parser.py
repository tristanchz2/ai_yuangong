#!/usr/bin/env python3
"""Excel 导出工具 - 从 extracted_data 导出采购公告到 Excel"""

import os
import sys
import json
import glob
from pathlib import Path
from datetime import datetime

import pandas as pd

# 确保项目根目录在 sys.path 中
_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config.settings import OUTPUT_DIR

DATA_DIR = str(OUTPUT_DIR)
OUTPUT_FILE = f'采购公告_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
CATEGORIES = ['采购公告']

# 需要展平的字段及列顺序
COLUMNS = [
    'source', 'title', 'notice_type', 'publish_time', 'bid_time',
    'budget', 'purchaser', 'purchaser_region',
    'service_category', 'service_province', 'service_location',
    'keywords', 'summary', 'remarks',
    'url', 'scrape_time', 'content',
]

# 中文列名映射
COLUMN_NAMES = {
    'source': '来源',
    'title': '标题',
    'notice_type': '公告类型',
    'publish_time': '发布时间',
    'bid_time': '开标时间',
    'budget': '预算金额',
    'purchaser': '采购人',
    'purchaser_region': '采购区域',
    'service_category': '服务类别',
    'service_province': '服务省份',
    'service_location': '服务地点',
    'keywords': '关键词',
    'summary': '摘要',
    'remarks': '备注',
    'url': '链接',
    'scrape_time': '爬取时间',
    'content': '正文内容',
}


def load_json_files(category_dir):
    """加载某个分类目录下所有 JSON 文件的 records"""
    records = []
    for fp in sorted(glob.glob(os.path.join(category_dir, '**', '*.json'), recursive=True)):
        with open(fp, 'r', encoding='utf-8') as f:
            data = json.load(f)
        for rec in data.get('records', []):
            # 展平 keywords 数组为逗号分隔字符串
            if 'keywords' in rec and isinstance(rec['keywords'], list):
                rec['keywords'] = '、'.join(rec['keywords'])
            records.append(rec)
    return records


def records_to_df(records):
    """records 列表转 DataFrame，确保列顺序和缺失列处理"""
    df = pd.DataFrame(records)
    # 只保留 COLUMNS 中定义的列，缺失的补空
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = None
    df = df[COLUMNS]
    df.rename(columns=COLUMN_NAMES, inplace=True)
    return df


def main():
    with pd.ExcelWriter(OUTPUT_FILE, engine='openpyxl') as writer:
        has_data = False
        for category in CATEGORIES:
            cat_dir = os.path.join(DATA_DIR, category)
            if not os.path.isdir(cat_dir):
                print(f'目录不存在: {cat_dir}')
                continue
            records = load_json_files(cat_dir)
            if not records:
                continue
            df = records_to_df(records)
            # sheet 名最长 31 字符
            sheet_name = category[:31]
            df.to_excel(writer, sheet_name=sheet_name, index=False)
            has_data = True
            print(f'[{category}] {len(records)} 条记录')

    if has_data:
        print(f'\n已导出到: {os.path.abspath(OUTPUT_FILE)}')
    else:
        print('未找到任何数据')


if __name__ == '__main__':
    main()
