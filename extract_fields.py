#!/usr/bin/env python3
"""
公告字段提取器 - 兼容性入口，实际逻辑已迁移至 scripts/extract_fields.py

用法不变：
  python extract_fields.py --source ccb
  python extract_fields.py --concurrency 3
"""

import sys
import os
from pathlib import Path

# 确保项目根目录在 sys.path 中
_PROJECT_ROOT = Path(__file__).parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# 委托给 scripts/extract_fields.py
from scripts.extract_fields import async_main

if __name__ == "__main__":
    import asyncio
    asyncio.run(async_main())
