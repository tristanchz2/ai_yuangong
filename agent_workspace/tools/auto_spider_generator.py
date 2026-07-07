#!/usr/bin/env python3
"""
智能爬虫生成器 - 自动化工作流

功能：
1. 使用浏览器工具侦察目标网站
2. 分析页面结构和 API
3. 生成爬虫代码
4. 自动测试验证
5. 失败时自动修正（最多 3 轮）
6. 最终失败时请求人工介入

使用方法：
    python auto_spider_generator.py <target_url> [output_file]
    
示例：
    python auto_spider_generator.py https://example.com/news
    python auto_spider_generator.py https://example.com/news scrapers/scrape_example.js
"""

import sys
import os
import subprocess
import time
import json
from pathlib import Path
from urllib.parse import urlparse

# 配置
MAX_RETRY_ROUNDS = 3  # 最大自动修正轮数
BROWSER_MCP_URL = "http://localhost:8765/sse"
AIDER_VENV = "venv-aider/bin/activate"
PROJECT_ROOT = "/Users/tristcz/project/ai_yuangong"


def run_command(cmd, cwd=None, timeout=300):
    """执行命令并返回输出"""
    print(f"\n🔧 执行命令: {cmd[:100]}...")
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=cwd or PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return result.returncode == 0, result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return False, f"命令超时 ({timeout}s)"
    except Exception as e:
        return False, str(e)


def check_browser_mcp():
    """检查浏览器 MCP 服务器是否运行"""
    print("\n🔍 检查浏览器 MCP 服务器...")
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(2)
    try:
        result = sock.connect_ex(('localhost', 8765))
        sock.close()
        if result == 0:
            print("✅ 浏览器 MCP 服务器正在运行 (端口 8765)")
            return True
        else:
            print("❌ 浏览器 MCP 服务器未运行")
            print("   请先启动: python3 agent_workspace/tools/browser_mcp_server.py --sse --port 8765 &")
            return False
    except Exception as e:
        sock.close()
        print(f"❌ 检查失败: {e}")
        return False


def reconnaissance(target_url):
    """阶段 1: 侦察页面结构"""
    print("\n" + "="*60)
    print("📊 阶段 1: 侦察页面结构")
    print("="*60)
    
    recon_prompt = f"""
请帮我侦察以下网站的页面结构和 API：

目标 URL: {target_url}

请按以下步骤执行：

1. 启动请求拦截器（捕获 XHR/Fetch 请求）
2. 导航到目标页面
3. 等待页面加载完成
4. 滚动页面触发懒加载
5. 查看捕获的网络请求
6. 获取页面文本内容
7. 截图保存

侦察完成后，请总结：
- 页面是否有反爬机制
- 有哪些 API 端点被调用
- 数据结构是什么样的
- 推荐用什么方式爬取（浏览器自动化 vs 直接 API 调用）

请使用 browser-use MCP 工具完成上述步骤。
"""
    
    print("\n🤖 Aider 正在侦察页面...")
    success, output = run_command(
        f'source {AIDER_VENV} && aider --no-show-model-warnings --no-auto-commits '
        f'--message "{recon_prompt}"',
        timeout=600
    )
    
    if success:
        print("✅ 侦察完成")
        # 提取关键信息
        return extract_recon_info(output)
    else:
        print("❌ 侦察失败")
        print(output[:500])
        return None


def extract_recon_info(output):
    """从侦察输出中提取关键信息"""
    info = {
        "has_anti_bot": "瑞数" in output or "WAF" in output or "challenge" in output.lower(),
        "api_endpoints": [],
        "data_structure": "",
        "recommended_approach": "browser" if "browser" in output.lower() else "api"
    }
    
    # 简单提取 API 端点
    lines = output.split('\n')
    for line in lines:
        if 'https://' in line and ('api' in line.lower() or 'xhr' in line.lower()):
            info["api_endpoints"].append(line.strip())
    
    return info


def generate_spider_code(target_url, output_file, recon_info):
    """阶段 2: 生成爬虫代码"""
    print("\n" + "="*60)
    print("💻 阶段 2: 生成爬虫代码")
    print("="*60)
    
    approach = recon_info.get("recommended_approach", "browser")
    
    spider_prompt = f"""
请为我编写一个完整的爬虫，爬取 {target_url}

侦察信息：
- 推荐方式: {approach}
- 有反爬机制: {recon_info.get('has_anti_bot', False)}
- API 端点: {recon_info.get('api_endpoints', [])}

要求：
1. 保存到文件: {output_file}
2. 使用 Node.js + Playwright 技术栈
3. 支持命令行参数: --latest N (只抓取最近 N 条)
4. 输出 JSON 格式到 raw_data/ 目录
5. 包含错误处理和重试机制
6. 代码要有详细注释

请参考 templates/scrape_template_list_page.js 或 templates/scrape_template_api_direct.js 的模板风格。

请直接生成完整的、可运行的代码。
"""
    
    print(f"\n🤖 Aider 正在生成爬虫代码（{approach} 模式）...")
    success, output = run_command(
        f'source {AIDER_VENV} && aider --no-show-model-warnings --no-auto-commits '
        f'{output_file} --message "{spider_prompt}"',
        timeout=600
    )
    
    if success and os.path.exists(output_file):
        print(f"✅ 爬虫代码已生成: {output_file}")
        return True
    else:
        print("❌ 代码生成失败")
        return False


def test_spider(spider_file, target_url):
    """阶段 3: 测试爬虫"""
    print("\n" + "="*60)
    print("🧪 阶段 3: 测试爬虫")
    print("="*60)
    
    # 先安装依赖
    print("\n📦 安装依赖...")
    run_command("npm install", cwd=PROJECT_ROOT)
    
    # 运行测试（只抓取 2 条）
    print("\n🚀 运行测试（抓取 2 条数据）...")
    success, output = run_command(
        f"node {spider_file} --latest 2",
        timeout=120
    )
    
    # 检查输出文件
    output_files = list(Path(PROJECT_ROOT).glob("raw_data/*.json"))
    if output_files:
        latest_file = max(output_files, key=os.path.getmtime)
        try:
            with open(latest_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list) and len(data) > 0:
                    print(f"✅ 测试成功！抓取到 {len(data)} 条数据")
                    print(f"   第一条数据: {json.dumps(data[0], ensure_ascii=False)[:200]}")
                    return True, data
        except Exception as e:
            print(f"⚠️  输出文件格式有问题: {e}")
    
    print("❌ 测试失败")
    print(f"输出:\n{output[:1000]}")
    return False, None


def fix_spider_code(spider_file, target_url, error_info, round_num):
    """阶段 4: 自动修正代码"""
    print("\n" + "="*60)
    print(f"🔧 阶段 4: 自动修正代码 (第 {round_num} 轮)")
    print("="*60)
    
    fix_prompt = f"""
爬虫测试失败了，请修复代码。

爬虫文件: {spider_file}
目标 URL: {target_url}

错误信息:
{error_info[:2000]}

请：
1. 分析错误原因
2. 修复代码
3. 确保代码可以正常运行
4. 保持原有的功能和结构

修复后我会重新测试。
"""
    
    print(f"\n🤖 Aider 正在修复代码...")
    success, output = run_command(
        f'source {AIDER_VENV} && aider --no-show-model-warnings --no-auto-commits '
        f'{spider_file} --message "{fix_prompt}"',
        timeout=600
    )
    
    return success


def main():
    """主流程"""
    if len(sys.argv) < 2:
        print("用法: python auto_spider_generator.py <target_url> [output_file]")
        print("示例: python auto_spider_generator.py https://example.com/news")
        sys.exit(1)
    
    target_url = sys.argv[1]
    # 从 URL 提取主机名生成文件名
    parsed_url = urlparse(target_url)
    hostname = parsed_url.hostname or 'unknown'
    output_file = sys.argv[2] if len(sys.argv) > 2 else f"scrapers/scrape_{hostname.replace('.', '_')}.js"
    
    print("\n" + "="*60)
    print("🕷️  智能爬虫生成器")
    print("="*60)
    print(f"目标 URL: {target_url}")
    print(f"输出文件: {output_file}")
    print(f"最大修正轮数: {MAX_RETRY_ROUNDS}")
    
    # Step 0: 检查环境
    if not check_browser_mcp():
        print("\n❌ 请先启动浏览器 MCP 服务器")
        sys.exit(1)
    
    # Step 1: 侦察
    recon_info = reconnaissance(target_url)
    if not recon_info:
        print("\n❌ 侦察失败，无法继续")
        sys.exit(1)
    
    print(f"\n📋 侦察结果:")
    print(f"  - 有反爬机制: {recon_info['has_anti_bot']}")
    print(f"  - 推荐方式: {recon_info['recommended_approach']}")
    print(f"  - API 端点: {len(recon_info['api_endpoints'])} 个")
    
    # Step 2: 生成代码
    if not generate_spider_code(target_url, output_file, recon_info):
        print("\n❌ 代码生成失败")
        sys.exit(1)
    
    # Step 3 & 4: 测试 + 自动修正循环
    for round_num in range(1, MAX_RETRY_ROUNDS + 1):
        print(f"\n{'='*60}")
        print(f"🔄 测试轮次 {round_num}/{MAX_RETRY_ROUNDS}")
        print('='*60)
        
        success, data = test_spider(output_file, target_url)
        
        if success:
            print("\n" + "="*60)
            print("🎉 爬虫生成成功！")
            print("="*60)
            print(f"文件位置: {output_file}")
            print(f"数据样例: {json.dumps(data[0] if data else {}, ensure_ascii=False)[:300]}")
            print("\n完整测试命令:")
            print(f"  node {output_file} --latest 10")
            sys.exit(0)
        else:
            if round_num < MAX_RETRY_ROUNDS:
                print(f"\n⚠️  测试失败，进入第 {round_num} 轮自动修正...")
                fix_spider_code(output_file, target_url, "测试失败，没有抓到数据", round_num)
            else:
                print(f"\n❌ 经过 {MAX_RETRY_ROUNDS} 轮自动修正仍然失败")
                print("\n📞 需要人工介入")
                print("\n建议操作：")
                print(f"1. 手动检查爬虫代码: {output_file}")
                print(f"2. 手动测试: node {output_file} --latest 5")
                print(f"3. 查看浏览器 MCP 日志: tail -f /tmp/browser_mcp.log")
                print("\n或者重新启动 Aider 进行交互式调试:")
                print(f"   source venv-aider/bin/activate")
                print(f"   aider {output_file}")
                sys.exit(1)


if __name__ == "__main__":
    main()
