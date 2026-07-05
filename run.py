"""
爬虫统一入口 - 单文件版
Usage:
    python3 run.py cfcpn --list 5         # 爬5页列表
    python3 run.py cfcpn --list all       # 爬全部列表
    python3 run.py cfcpn --resume         # 断点续爬
    python3 run.py list                   # 列出所有爬虫
"""

import argparse
import os
import subprocess
import sys
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# ---- 爬虫注册表 ----

SCRAPERS = {}


def register(name, description, add_args_fn=None, run_fn=None):
    """注册一个爬虫"""
    SCRAPERS[name] = {
        'description': description,
        'add_args': add_args_fn,
        'run': run_fn,
    }


# ---- Node 查找 ----

def find_node():
    for p in ['/opt/homebrew/bin/node', '/usr/local/bin/node']:
        if os.path.isfile(p):
            return p
    return 'node'


# ---- cfcpn 金采网 ----

def cfcpn_add_args(parser):
    parser.add_argument('--list', nargs='?', const='5', metavar='N',
                        help='先爬 N 页列表（默认5页，传 all 爬全部）')
    parser.add_argument('--resume', action='store_true', help='断点续爬')
    parser.add_argument('--begin-date', metavar='DATE', help='开始日期，格式 yyyy-MM-dd')
    parser.add_argument('--end-date', metavar='DATE', help='结束日期，格式 yyyy-MM-dd')
    parser.add_argument('--yesterday', action='store_true', help='快捷方式：爬昨天一整天的数据')


def cfcpn_run(args):
    script_dir = os.path.join(BASE_DIR, 'scrapers')
    script_path = os.path.join(script_dir, 'scrape_cfcpn.js')
    cmd = [find_node(), script_path]

    if getattr(args, 'list', None):
        cmd += ['--list', args.list]
    if args.resume:
        cmd.append('resume')
    if args.yesterday:
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        cmd += ['--begin-date', yesterday, '--end-date', yesterday]
    if args.begin_date:
        cmd += ['--begin-date', args.begin_date]
    if args.end_date:
        cmd += ['--end-date', args.end_date]

    print(f'运行: {" ".join(cmd)}\n')
    sys.exit(subprocess.run(cmd, cwd=script_dir).returncode)


register('cfcpn', '金采网 (CFCPN) 采购公告爬虫', cfcpn_add_args, cfcpn_run)


# ---- 新增爬虫在此处添加 ----
# register('newsite', '新网站爬虫', newsite_add_args, newsite_run)


# ---- CLI 入口 ----

def main():
    parser = argparse.ArgumentParser(description='爬虫统一入口')
    subparsers = parser.add_subparsers(dest='scraper', help='选择爬虫')

    subparsers.add_parser('list', help='列出所有可用爬虫')

    for name, info in SCRAPERS.items():
        sub = subparsers.add_parser(name, help=info['description'])
        if info['add_args']:
            info['add_args'](sub)

    args, _ = parser.parse_known_args()

    if args.scraper in (None, 'list'):
        print('可用爬虫:')
        for name, info in SCRAPERS.items():
            print(f'  {name:15s} - {info["description"]}')
        return

    info = SCRAPERS.get(args.scraper)
    if not info:
        print(f'未知爬虫: {args.scraper}')
        sys.exit(1)

    info['run'](args)


if __name__ == '__main__':
    main()
