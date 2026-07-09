#!/usr/bin/env python3
"""
爬虫运行入口 - 方便快速测试所有爬虫

用法:
  python run_scrapers.py                        # 交互式选择
  python run_scrapers.py --all                  # 运行所有爬虫 (latest 5, 并行)
  python run_scrapers.py --all -s               # 运行所有爬虫 (串行)
  python run_scrapers.py --run cgbchina         # 运行指定爬虫
  python run_scrapers.py --run cgbchina icbc    # 运行多个爬虫 (并行)
  python run_scrapers.py --all --yesterday      # 所有爬虫爬昨天数据
  python run_scrapers.py --all --date 2026-07-01  # 所有爬虫爬指定日期
  python run_scrapers.py --all --latest 10      # 所有爬虫爬最新10条
  python run_scrapers.py --list                 # 列出所有可用爬虫
"""

import argparse
import json
import subprocess
import sys
import os
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

SCRAPERS_DIR = Path(__file__).parent / "scrapers"
RAW_DATA_DIR = Path(__file__).parent / "raw_data"
LOGS_DIR = Path(__file__).parent / "logs"


def find_scrapers():
    """扫描 scrapers 目录，返回所有爬虫信息"""
    scrapers = []
    for f in sorted(SCRAPERS_DIR.glob("scrape_*.js")):
        name = f.stem.replace("scrape_", "")
        scrapers.append({"name": name, "path": str(f)})
    return scrapers


def get_scraper_info(scraper_path):
    """获取爬虫元信息"""
    try:
        result = subprocess.run(
            ["node", scraper_path, "--info"],
            capture_output=True, text=True, timeout=15,
            cwd=str(SCRAPERS_DIR),
        )
        if result.returncode == 0:
            return json.loads(result.stdout.strip())
    except Exception as e:
        return {"error": str(e)}
    return None


def list_scrapers():
    """列出所有可用爬虫及信息"""
    scrapers = find_scrapers()
    if not scrapers:
        print("❌ 没有找到任何爬虫文件")
        return

    print(f"\n📋 共 {len(scrapers)} 个爬虫:\n")
    print(f"{'名称':<20} {'描述':<40} {'模式'}")
    print("-" * 80)

    for s in scrapers:
        info = get_scraper_info(s["path"])
        if info and "error" not in info:
            desc = info.get("description", "-")[:38]
            modes = ", ".join(info.get("modes", []))
            print(f"{s['name']:<20} {desc:<40} {modes}")
        else:
            print(f"{s['name']:<20} {'(无法获取信息)':<40} -")

    print()


def run_scraper(name, mode_args, parallel=False):
    """运行单个爬虫。parallel=True 时捕获输出写日志文件，最后打印摘要"""
    scraper_path = SCRAPERS_DIR / f"scrape_{name}.js"
    if not scraper_path.exists():
        print(f"❌ 爬虫不存在: {scraper_path}")
        return {"name": name, "success": False}

    cmd = ["node", str(scraper_path)] + mode_args

    if parallel:
        # 并行模式：输出写日志文件，避免终端混乱
        LOGS_DIR.mkdir(exist_ok=True)
        log_file = LOGS_DIR / f"run_{name}_{int(time.time())}.log"
        print(f"🚀 [{name}] 启动 (日志: {log_file.name})")
        start = time.time()
        try:
            with open(log_file, "w", encoding="utf-8") as f:
                f.write(f"$ {' '.join(cmd)}\n\n")
                result = subprocess.run(
                    cmd, cwd=str(SCRAPERS_DIR),
                    stdout=f, stderr=subprocess.STDOUT,
                )
            elapsed = time.time() - start
            ok = result.returncode == 0
            # 读最后几行作为摘要
            tail = ""
            try:
                lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
                tail = "\n".join(lines[-5:]) if len(lines) > 5 else "\n".join(lines)
            except Exception:
                pass
            if ok:
                row_count = _count_rows(name)
                extra = f", {row_count} 条数据" if row_count is not None else ""
                print(f"✅ [{name}] 成功 ({elapsed:.1f}s{extra})")
            else:
                print(f"❌ [{name}] 失败 (退出码 {result.returncode}, {elapsed:.1f}s)")
                print(f"   日志尾部:\n{tail}")
            return {"name": name, "success": ok, "elapsed": elapsed, "log_file": str(log_file)}
        except Exception as e:
            print(f"❌ [{name}] 异常: {e}")
            return {"name": name, "success": False, "elapsed": time.time() - start}
    else:
        # 串行模式：直接输出到终端
        print(f"\n{'='*60}")
        print(f"🚀 运行爬虫: {name}")
        print(f"   命令: {' '.join(cmd)}")
        print(f"{'='*60}\n")
        start = time.time()
        try:
            result = subprocess.run(cmd, cwd=str(SCRAPERS_DIR))
            elapsed = time.time() - start
            if result.returncode == 0:
                row_count = _count_rows(name)
                extra = f", {row_count} 条数据" if row_count is not None else ""
                print(f"\n✅ {name} 运行成功 ({elapsed:.1f}s{extra})")
                return {"name": name, "success": True, "elapsed": elapsed}
            else:
                print(f"\n❌ {name} 运行失败 (退出码 {result.returncode})")
                return {"name": name, "success": False, "elapsed": elapsed}
        except Exception as e:
            print(f"\n❌ {name} 运行异常: {e}")
            return {"name": name, "success": False, "elapsed": time.time() - start}


def _count_rows(name):
    """读取输出 JSON 的 rows 数量"""
    output = RAW_DATA_DIR / f"{name}_data.json"
    if not output.exists():
        return None
    try:
        data = json.loads(output.read_text(encoding="utf-8"))
        return len(data.get("rows", []))
    except Exception:
        return None


def run_batch(names, mode_args, parallel=True):
    """批量运行爬虫，返回结果列表"""
    results = []
    total = len(names)
    start = time.time()

    if parallel and total > 1:
        print(f"\n⚡ 并行运行 {total} 个爬虫...\n")
        with ThreadPoolExecutor(max_workers=total) as pool:
            futures = {
                pool.submit(run_scraper, name, mode_args, True): name
                for name in names
            }
            for future in as_completed(futures):
                results.append(future.result())
    else:
        for name in names:
            r = run_scraper(name, mode_args, parallel=False)
            results.append(r)

    # 汇总
    elapsed = time.time() - start
    ok = sum(1 for r in results if r["success"])
    print(f"\n{'='*60}")
    print(f"📊 结果: {ok}/{total} 成功, 总耗时 {elapsed:.1f}s")
    if parallel and total > 1:
        print(f"{'='*60}")
        for r in sorted(results, key=lambda x: x.get("elapsed", 0)):
            status = "✅" if r["success"] else "❌"
            e = r.get('elapsed', 0)
            print(f"  {status} {r['name']:<20} {e:.1f}s")
    print()
    return results


def interactive_mode():
    """交互式选择爬虫"""
    scrapers = find_scrapers()
    if not scrapers:
        print("❌ 没有找到任何爬虫文件")
        return

    print("\n📋 可用爬虫:\n")
    for i, s in enumerate(scrapers, 1):
        print(f"  {i}. {s['name']}")
    print(f"  0. 运行全部")

    choice = input("\n请选择 (输入编号，多个用空格分隔): ").strip()

    if not choice:
        return

    if choice == "0":
        names = [s["name"] for s in scrapers]
    else:
        names = []
        for idx in choice.split():
            i = int(idx) - 1
            if 0 <= i < len(scrapers):
                names.append(scrapers[i]["name"])
            else:
                print(f"⚠ 无效编号: {idx}")

    if not names:
        return

    mode = input("模式 (latest/yesterday/date) [latest]: ").strip() or "latest"
    count = input("数量 (latest模式) [5]: ").strip() or "5"
    mode_args = build_mode_args(mode, count)
    parallel = input("并行运行? (y/n) [y]: ").strip().lower() != "n"

    run_batch(names, mode_args, parallel=parallel)


def build_mode_args(mode, count="5", date=None):
    """构建命令行参数"""
    if mode == "yesterday":
        return ["--yesterday"]
    elif mode == "date" and date:
        return ["--date", date]
    else:
        return ["--latest", str(count)]


def main():
    parser = argparse.ArgumentParser(
        description="爬虫运行入口",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python run_scrapers.py --list                  # 列出所有爬虫
  python run_scrapers.py --run cgbchina          # 运行单个爬虫
  python run_scrapers.py --all --yesterday       # 全部爬昨天
  python run_scrapers.py --all --latest 10       # 全部爬最新10条
  python run_scrapers.py                         # 交互式选择
        """,
    )
    parser.add_argument("--list", action="store_true", help="列出所有可用爬虫")
    parser.add_argument("--all", action="store_true", help="运行所有爬虫")
    parser.add_argument("--run", nargs="+", metavar="NAME", help="运行指定爬虫")
    parser.add_argument("--latest", type=int, default=None, help="爬取最新N条")
    parser.add_argument("--yesterday", action="store_true", help="爬取昨天数据")
    parser.add_argument("--date", type=str, default=None, help="爬取指定日期 (YYYY-MM-DD)")
    parser.add_argument("-s", "--serial", action="store_true", help="串行运行 (默认并行)")

    args = parser.parse_args()

    # 构建模式参数
    mode_args = []
    if args.yesterday:
        mode_args = ["--yesterday"]
    elif args.date:
        mode_args = ["--date", args.date]
    elif args.latest:
        mode_args = ["--latest", str(args.latest)]
    else:
        mode_args = ["--latest", "5"]

    parallel = not args.serial

    if args.list:
        list_scrapers()
    elif args.run:
        run_batch(args.run, mode_args, parallel=parallel)
    elif args.all:
        scrapers = find_scrapers()
        names = [s["name"] for s in scrapers]
        run_batch(names, mode_args, parallel=parallel)
    else:
        interactive_mode()


if __name__ == "__main__":
    main()
