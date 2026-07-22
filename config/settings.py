"""全局配置 - 环境变量加载 + 路径常量"""

import os
from pathlib import Path

# 项目根目录（config/ 的上一级）
PROJECT_ROOT = Path(__file__).parent.parent

# 常用目录
STATIC_DIR = PROJECT_ROOT / "static"
SCRAPERS_DIR = PROJECT_ROOT / "scrapers"
RAW_DATA_DIR = PROJECT_ROOT / "raw_data"
OUTPUT_DIR = PROJECT_ROOT / "extracted_data"
LOGS_DIR = PROJECT_ROOT / "logs"
EXTRACT_SCRIPT = PROJECT_ROOT / "scripts" / "extract_fields.py"


def load_env():
    """加载 .env 文件到 os.environ（仅设置尚未存在的变量）"""
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, val = line.split('=', 1)
                    os.environ.setdefault(key.strip(), val.strip())


# 模块导入时自动加载环境变量
load_env()
