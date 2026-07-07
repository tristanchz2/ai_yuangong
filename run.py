"""
爬虫启动层（外层入口）
将所有命令行参数原封不动地转发给 agent_workspace/scrapers/run.py
"""

import os
import subprocess
import sys


def main():
    inner_run = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'agent_workspace', 'run.py')
    result = subprocess.run([sys.executable, inner_run] + sys.argv[1:])
    sys.exit(result.returncode)


if __name__ == '__main__':
    main()
