"""
爬虫统一入口（内层）
Usage:
    python3 run.py list                  # 列出所有爬虫
    python3 run.py cfcpn --latest 5      # 爬最新5条（测试）
    python3 run.py ccgp --yesterday      # 爬昨天的数据（生产）
    python3 run.py all --latest 5        # 全部爬虫，各爬最新5条
    python3 run.py all --yesterday       # 全部爬虫，各爬昨天数据
"""

import argparse
import os
import subprocess
import sys
from datetime import datetime, timedelta

SCRAPERS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'scrapers')


# ---- 爬虫注册表 ----

SCRAPERS = {}


def register(name, description, run_fn=None):
    """注册一个爬虫"""
    SCRAPERS[name] = {
        'description': description,
        'run': run_fn,
    }


# ---- Node 查找 ----

def find_node():
    # macOS / Linux / Windows common paths
    for p in [
        '/opt/homebrew/bin/node',
        '/usr/local/bin/node',
        r'C:\Program Files\nodejs\node.exe',
        r'C:\Program Files (x86)\nodejs\node.exe',
    ]:
        if os.path.isfile(p):
            return p
    return 'node'


def build_node_cmd(script_name):
    """构造 node 命令前缀"""
    return [find_node(), os.path.join(SCRAPERS_DIR, script_name)]


def run_script(cmd, label):
    """运行一个爬虫脚本，打印结果"""
    print(f'[{label}] 运行: {" ".join(cmd)}\n')
    result = subprocess.run(cmd, cwd=SCRAPERS_DIR)
    print(f'[{label}] 退出码: {result.returncode}\n')
    return result.returncode


# ---- cfcpn 金采网 ----
# JS 参数: --list N (页数), --begin-date, --end-date, resume

def cfcpn_run(args):
    cmd = build_node_cmd('scrape_cfcpn.js')
    if args.yesterday:
        y = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        cmd += ['--begin-date', y, '--end-date', y]
    else:
        cmd += ['--list', '1']
    run_script(cmd, 'cfcpn')


register('cfcpn', '金采网 (CFCPN) 采购公告爬虫', cfcpn_run)


# ---- ccgp 中国政府采购网 ----
# JS 参数: --list N (页数), --limit N, --begin-date, --end-date, --yesterday

def ccgp_run(args):
    cmd = build_node_cmd('scrape_ccgp.js')
    if args.yesterday:
        cmd.append('--yesterday')
    else:
        cmd += ['--list', '1', '--limit', str(args.latest)]
    run_script(cmd, 'ccgp')


register('ccgp', '中国政府采购网 (CCGP) 金融标书爬虫', ccgp_run)


# ---- boc_pcm 中银智采 ----
# JS 参数: --latest N, --yesterday, --date

def boc_pcm_run(args):
    cmd = build_node_cmd('scrape_boc_pcm.js')
    if args.yesterday:
        cmd.append('--yesterday')
    else:
        cmd += ['--latest', str(args.latest)]
    run_script(cmd, 'boc_pcm')


register('boc_pcm', '中银智采 (BOC PCM) 采购公告爬虫', boc_pcm_run)


# ---- abc_puc 农银e采 ----
# JS 参数: --latest N, --yesterday, --date

def abc_puc_run(args):
    cmd = build_node_cmd('scrape_abc_puc.js')
    if args.yesterday:
        cmd.append('--yesterday')
    else:
        cmd += ['--latest', str(args.latest)]
    run_script(cmd, 'abc_puc')


register('abc_puc', '农银e采 (ABC PUC) 招标公告爬虫', abc_puc_run)


# ---- icbc 工银集采 ----
# JS 参数: --latest N, --yesterday, --date

def icbc_run(args):
    cmd = build_node_cmd('scrape_icbc.js')
    if args.yesterday:
        cmd.append('--yesterday')
    else:
        cmd += ['--latest', str(args.latest)]
    run_script(cmd, 'icbc')


register('icbc', '工银集采 (ICBC) 招标公告爬虫', icbc_run)


# ---- cdb 国家开发银行采购网 ----
# JS 参数: --latest N, --yesterday, --date

def cdb_run(args):
    cmd = build_node_cmd('scrape_cdb.js')
    if args.yesterday:
        cmd.append('--yesterday')
    else:
        cmd += ['--latest', str(args.latest)]
    run_script(cmd, 'cdb')


register('cdb', '国开采购网 (CDB) 结果公告爬虫', cdb_run)


# ---- ccb 建设银行龙集采 ----
# JS 参数: --latest N, --yesterday, --date

def ccb_run(args):
    cmd = build_node_cmd('scrape_ccb.js')
    if args.yesterday:
        cmd.append('--yesterday')
    else:
        cmd += ['--latest', str(args.latest)]
    run_script(cmd, 'ccb')


register('ccb', '龙集采 (CCB) 招标公告爬虫', ccb_run)


# ---- 新增爬虫在此处添加 ----
# register('newsite', '新网站爬虫', newsite_run)


# ---- CLI 入口 ----

def add_common_args(parser):
    """为每个爬虫子命令添加统一参数"""
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--latest', nargs='?', const=5, type=int, metavar='N',
                       help='爬取最新 N 条（默认5，用于测试）')
    group.add_argument('--yesterday', action='store_true',
                       help='爬取昨天发布的数据（生产模式）')


def main():
    parser = argparse.ArgumentParser(
        description='爬虫统一入口',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 run.py list                  列出所有爬虫
  python3 run.py cfcpn --latest 5      爬金采网最新5条
  python3 run.py ccgp --yesterday      爬政府采购网昨天数据
  python3 run.py all --latest 5        全部爬虫各爬最新5条
  python3 run.py all --yesterday       全部爬虫各爬昨天数据
        """,
    )
    subparsers = parser.add_subparsers(dest='scraper', help='选择爬虫')

    # list 命令
    subparsers.add_parser('list', help='列出所有可用爬虫')

    # all 命令
    all_parser = subparsers.add_parser('all', help='运行所有爬虫')
    add_common_args(all_parser)

    # 各爬虫子命令
    for name, info in SCRAPERS.items():
        sub = subparsers.add_parser(name, help=info['description'])
        add_common_args(sub)

    args = parser.parse_args()

    # 无参数或 list：列出爬虫
    if args.scraper in (None, 'list'):
        print('可用爬虫:')
        for name, info in SCRAPERS.items():
            print(f'  {name:15s} - {info["description"]}')
        print('\n用法:')
        print('  python3 run.py <name> --latest 5      爬最新5条（测试）')
        print('  python3 run.py <name> --yesterday      爬昨天数据（生产）')
        print('  python3 run.py all --latest 5           全部爬虫各爬最新5条')
        print('  python3 run.py all --yesterday          全部爬虫各爬昨天数据')
        return

    # 设置默认模式
    if not args.yesterday and args.latest is None:
        args.latest = 5

    # all 命令：依次运行所有爬虫
    if args.scraper == 'all':
        print(f'=== 运行全部 {len(SCRAPERS)} 个爬虫 ===\n')
        mode = '昨天数据' if args.yesterday else f'最新 {args.latest} 条'
        print(f'模式: {mode}\n')
        failed = []
        for name, info in SCRAPERS.items():
            print(f'--- {name}: {info["description"]} ---\n')
            rc = info['run'](args)
            if rc != 0:
                failed.append(name)
        print(f'\n=== 完成 ===')
        if failed:
            print(f'失败: {", ".join(failed)}')
            sys.exit(1)
        else:
            print('全部成功')
        return

    # 单个爬虫
    info = SCRAPERS.get(args.scraper)
    if not info:
        print(f'未知爬虫: {args.scraper}')
        sys.exit(1)

    info['run'](args)


if __name__ == '__main__':
    main()
