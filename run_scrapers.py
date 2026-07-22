#!/usr/bin/env python3
"""
爬虫运行入口 - 兼容性入口，实际逻辑已迁移至 scripts/run_scrapers.py

用法不变：
  python run_scrapers.py --all --yesterday
  python run_scrapers.py --run cgbchina
  python run_scrapers.py --list
"""

import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
_PROJECT_ROOT = Path(__file__).parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# 委托给 scripts/run_scrapers.py
from scripts.run_scrapers import main

if __name__ == "__main__":
    main()
