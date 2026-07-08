#!/usr/bin/env python3
"""
纯 Python 实现的智能爬虫生成器（不依赖 Aider MCP）

直接使用 browser_mcp_cli.py 调用浏览器工具，然后用 LLM 生成代码。
"""

import sys
import os
import subprocess
import json
import time
from pathlib import Path
from urllib.parse import urlparse

# 配置
MAX_RETRY_ROUNDS = 3  # 最大自动修正轮数
BROWSER_CLI = "agent_workspace/tools/browser_mcp_cli.py"
PROJECT_ROOT = "/Users/tristcz/project/ai_yuangong"


def run_browser_tool(tool_name, args_dict):
    """调用 browser_mcp_cli.py 执行浏览器工具"""
    cmd = [
        sys.executable,  # 使用当前 Python 解释器
        BROWSER_CLI,
        tool_name,
        json.dumps(args_dict)
    ]
    
    print(f"[>] 执行: {tool_name}({json.dumps(args_dict)})")
    try:
        result = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=60
        )
        
        # 过滤 INFO 日志
        output_lines = []
        for line in result.stdout.split('\n'):
            if not line.startswith('INFO:') and 'Processing' not in line and '127.0.0.1' not in line:
                output_lines.append(line)
        
        output = '\n'.join(output_lines).strip()
        
        if result.returncode == 0:
            print(f"[OK] {tool_name} 成功")
            return True, output
        else:
            print(f"[FAIL] {tool_name} 失败: {result.stderr[:200]}")
            return False, output
    except Exception as e:
        print(f"[FAIL] {tool_name} 异常: {e}")
        return False, str(e)


def reconnaissance(target_url):
    """阶段 1: 侦察页面"""
    print("\n" + "="*60)
    print("[>] 阶段 1: 侦察页面结构")
    print("="*60)
    
    # Step 1: 启动请求拦截
    print("\n[1] 启动请求拦截...")
    success, output = run_browser_tool("start_request_interception", {
        "resource_types": ["xhr", "fetch"]
    })
    if not success:
        print(f"   警告: {output}")
    
    time.sleep(1)
    
    # Step 2: 导航到目标页面
    print(f"\n[2] 导航到: {target_url}")
    success, output = run_browser_tool("navigate_page", {
        "url": target_url,
        "type": "url",
        "timeout": 30000
    })
    if not success:
        print(f"   [FAIL] 导航失败: {output}")
        return None
    
    print(f"   [OK] 当前 URL: {output}")
    time.sleep(2)
    
    # Step 3: 获取页面快照
    print("\n[3] 获取页面 DOM 快照...")
    success, snapshot = run_browser_tool("take_snapshot", {})
    if success:
        print(f"   [OK] 快照长度: {len(snapshot)} 字符")
    else:
        print(f"   [WARN] 快照失败: {snapshot[:200]}")
        snapshot = ""
    
    # Step 4: 获取页面文本
    print("\n[4] 获取页面文本内容...")
    success, page_text = run_browser_tool("get_page_text", {})
    if success:
        print(f"   [OK] 文本长度: {len(page_text)} 字符")
        print(f"   前 500 字符: {page_text[:500]}")
    else:
        print(f"   [WARN] 文本获取失败")
        page_text = ""
    
    # Step 5: 滚动触发懒加载
    print("\n[5] 滚动页面触发懒加载...")
    success, _ = run_browser_tool("scroll_page", {
        "to_bottom": True
    })
    if success:
        print("   [OK] 滚动完成")
    time.sleep(2)
    
    # Step 6: 查看网络请求
    print("\n[6] 查看捕获的网络请求...")
    success, network_info = run_browser_tool("list_network_requests", {
        "resource_types": ["xhr", "fetch"],
        "include_headers": False,
        "page_size": 20
    })
    if success:
        print(f"   [OK] 网络请求信息:\n{network_info[:1000]}")
    else:
        print(f"   [WARN] 网络请求获取失败")
        network_info = ""
    
    # Step 7: 截图
    print("\n[7] 截图保存...")
    screenshot_path = f"/tmp/recon_{int(time.time())}.png"
    success, screenshot_result = run_browser_tool("take_screenshot", {
        "full_page": True,
        "path": screenshot_path
    })
    if success:
        print(f"   [OK] 截图已保存: {screenshot_result}")
    else:
        print(f"   [WARN] 截图失败: {screenshot_result}")
    
    # 汇总侦察结果
    recon_data = {
        "url": target_url,
        "page_text": page_text[:2000],  # 限制长度
        "snapshot": snapshot[:2000],
        "network_requests": network_info[:2000],
        "has_anti_bot": "瑞数" in page_text or "challenge" in page_text.lower() or len(page_text) < 100,
        "timestamp": time.time()
    }
    
    print("\n" + "="*60)
    print("[>] 侦察结果汇总")
    print("="*60)
    print(f"  - 目标 URL: {target_url}")
    print(f"  - 有反爬机制: {'是 [WARN]' if recon_data['has_anti_bot'] else '否 [OK]'}")
    print(f"  - 页面文本长度: {len(page_text)} 字符")
    print(f"  - 网络请求数: {network_info.count('http') if network_info else 0}")
    
    return recon_data


def generate_spider_code(recon_data, output_file):
    """阶段 2: 生成爬虫代码"""
    print("\n" + "="*60)
    print("[>] 阶段 2: 生成爬虫代码")
    print("="*60)
    
    # 构建 Prompt
    prompt = f"""
请为我编写一个完整的 Node.js + Playwright 爬虫。

目标网站: {recon_data['url']}

侦察信息:
- 有反爬机制: {recon_data['has_anti_bot']}
- 页面文本预览: {recon_data['page_text'][:500]}
- 网络请求: {recon_data['network_requests'][:500]}

要求:
1. 保存到文件: {output_file}
2. 使用 Node.js + Playwright
3. 支持命令行参数: --latest N (只抓取最近 N 条)
4. 输出 JSON 格式到 raw_data/ 目录
5. 包含错误处理和重试机制
6. 如果有反爬，使用 stealth 技术
7. 代码要有详细注释

请直接输出完整的、可运行的 JavaScript 代码，不要有其他解释。
"""
    
    print("\n[>] 正在生成爬虫代码...")
    
    # 这里可以调用任何 LLM API
    # 为了演示，我们使用简单的模板
    code = generate_template_code(recon_data, output_file)
    
    # 保存代码
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(code)
    
    print(f"[OK] 爬虫代码已生成: {output_file}")
    print(f"   文件大小: {os.path.getsize(output_file)} 字节")
    
    return True


def generate_template_code(recon_data, output_file):
    """生成爬虫代码模板"""
    url = recon_data['url']
    has_anti_bot = recon_data['has_anti_bot']
    
    code = f'''/**
 * 爬虫名称: Auto-generated Spider
 * 目标网站: {url}
 * 生成时间: {time.strftime("%Y-%m-%d %H:%M:%S")}
 * 技术方案: Node.js + Playwright
 * 反爬处理: {"启用 Stealth" if has_anti_bot else "无"}
 */

const playwright = require('playwright');
const fs = require('fs');
const path = require('path');

// ==================== 配置区 ====================
const CONFIG = {{
    targetUrl: '{url}',
    outputDir: 'raw_data',
    outputFile: '{Path(output_file).stem}.json',
    headless: true,  // 是否无头模式
    maxRetries: 3,   // 最大重试次数
}};

// ==================== 主函数 ====================
async function main() {{
    console.log('[>] 启动爬虫...');
    console.log('目标:', CONFIG.targetUrl);
    
    // 解析命令行参数
    const args = process.argv.slice(2);
    let latestCount = null;
    
    for (let i = 0; i < args.length; i++) {{
        if (args[i] === '--latest' && i + 1 < args.length) {{
            latestCount = parseInt(args[i + 1]);
        }}
    }}
    
    if (latestCount) {{
        console.log(`[>] 只抓取最近 ${{latestCount}} 条`);
    }}
    
    // 启动浏览器
    const browser = await playwright.chromium.launch({{
        headless: CONFIG.headless,
        args: [
            '--disable-blink-features=AutomationControlled',
            '--no-sandbox',
        ],
    }});
    
    const context = await browser.newContext({{
        userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        viewport: {{ width: 1920, height: 1080 }},
    }});
    
    {"// 注入 stealth 脚本（反爬）" if has_anti_bot else ""}
    {'''await context.addInitScript(() => {
        Object.defineProperty(navigator, 'webdriver', {{ get: () => undefined }});
        Object.defineProperty(navigator, 'plugins', {{ get: () => [1, 2, 3, 4, 5] }});
        window.chrome = {{ runtime: {{}} }};
    });''' if has_anti_bot else ""}
    
    const page = await context.newPage();
    
    try {{
        // 导航到目标页面
        console.log('[>] 导航到目标页面...');
        await page.goto(CONFIG.targetUrl, {{ 
            waitUntil: 'domcontentloaded',
            timeout: 30000 
        }});
        
        // 等待页面加载
        await page.waitForTimeout(2000);
        
        // TODO: 根据实际页面结构调整选择器
        console.log('[>] 提取数据...');
        
        const items = await page.evaluate(() => {{
            const results = [];
            
            // TODO: 修改这里的选择器以匹配目标网站
            const elements = document.querySelectorAll('.item, .news-item, .article, li');
            
            elements.forEach((el, index) => {{
                const titleEl = el.querySelector('.title, h2, h3, a');
                const linkEl = el.querySelector('a');
                const dateEl = el.querySelector('.date, time, .publish-date');
                
                if (titleEl || linkEl) {{
                    results.push({{
                        title: titleEl ? titleEl.textContent.trim() : '',
                        link: linkEl ? linkEl.href : '',
                        date: dateEl ? dateEl.textContent.trim() : '',
                        index: index,
                    }});
                }}
            }});
            
            return results;
        }});
        
        console.log(`[OK] 提取到 ${{items.length}} 条数据`);
        
        // 限制数量
        const limitedItems = latestCount ? items.slice(0, latestCount) : items;
        
        // 保存数据
        const outputPath = path.join(CONFIG.outputDir, CONFIG.outputFile);
        fs.mkdirSync(CONFIG.outputDir, {{ recursive: true }});
        fs.writeFileSync(outputPath, JSON.stringify(limitedItems, null, 2), 'utf-8');
        
        console.log(`[>] 数据已保存: ${{outputPath}}`);
        console.log(`[>] 共 ${{limitedItems.length}} 条记录`);
        
        if (limitedItems.length > 0) {{
            console.log('\\n第一条数据示例:');
            console.log(JSON.stringify(limitedItems[0], null, 2));
        }}
        
    }} catch (error) {{
        console.error('[FAIL] 爬虫出错:', error.message);
        throw error;
    }} finally {{
        await browser.close();
        console.log('[>] 浏览器已关闭');
    }}
}}

// 运行
main().catch(err => {{
    console.error('Fatal error:', err);
    process.exit(1);
}});
'''
    
    return code


def fix_spider_code_with_aider(spider_file, error_output, round_num):
    """使用 Aider 自动修复爬虫代码"""
    print(f"\n{'='*60}")
    print(f"[>] 第 {round_num} 轮自动修正（使用 Aider）")
    print('='*60)
    
    fix_prompt = f"""
爬虫测试失败了，请帮我修复代码。

爬虫文件: {spider_file}
错误信息:
{error_output[:2000]}

请：
1. 分析错误原因
2. 修复代码中的问题
3. 确保选择器能正确匹配目标网站的元素
4. 保持代码结构不变
5. 添加更详细的调试日志

修复后我会重新测试。
"""
    
    print(f"\n[>] Aider 正在分析并修复代码...")
    
    try:
        # 使用 venv-aider 中的 Python
        aider_python = os.path.join(PROJECT_ROOT, "venv-aider/bin/python3")
        
        result = subprocess.run(
            [
                aider_python,
                "-m", "aider",
                "--no-show-model-warnings",
                "--no-auto-commits",
                spider_file,
                "--message", fix_prompt
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=300
        )
        
        if result.returncode == 0:
            print("[OK] Aider 修复完成")
            return True
        else:
            print(f"[WARN] Aider 执行异常: {result.stderr[:500]}")
            return False
            
    except Exception as e:
        print(f"[FAIL] Aider 调用失败: {e}")
        return False


def test_and_fix_spider(spider_file, max_retries=MAX_RETRY_ROUNDS):
    """测试爬虫，失败时自动用 Aider 修复"""
    print("\n" + "="*60)
    print("[>] 阶段 3: 测试爬虫 + 自动修正")
    print("="*60)
    
    # 检查文件是否存在
    if not os.path.exists(spider_file):
        print(f"[FAIL] 爬虫文件不存在: {spider_file}")
        return False
    
    for round_num in range(1, max_retries + 1):
        print(f"\n{'='*60}")
        print(f"[>] 测试轮次 {round_num}/{max_retries}")
        print('='*60)
        
        print(f"\n[>] 安装依赖...")
        subprocess.run(["npm", "install"], cwd=PROJECT_ROOT, capture_output=True)
        
        print(f"\n[>] 运行测试（抓取 2 条）...")
        try:
            result = subprocess.run(
                ["node", spider_file, "--latest", "2"],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                timeout=120
            )
            
            output = result.stdout + result.stderr
            print(output[:2000])  # 打印部分输出
            
            # 检查是否成功抓取到数据
            if result.returncode == 0 and "提取到 0 条数据" not in output:
                print("\n[OK] 测试成功！")
                return True
            elif "提取到 0 条数据" in output:
                print("\n[WARN] 测试通过但未抓取到数据（选择器可能不匹配）")
                if round_num < max_retries:
                    print(f"\n[>] 进入第 {round_num} 轮自动修正...")
                    if not fix_spider_code_with_aider(spider_file, output, round_num):
                        print("[WARN] Aider 修复失败，继续下一轮")
                continue
            else:
                print(f"\n[FAIL] 测试失败 (exit code: {result.returncode})")
                if round_num < max_retries:
                    print(f"\n[>] 进入第 {round_num} 轮自动修正...")
                    if not fix_spider_code_with_aider(spider_file, output, round_num):
                        print("[WARN] Aider 修复失败，继续下一轮")
                continue
                
        except subprocess.TimeoutExpired:
            print("\n[FAIL] 测试超时")
            if round_num < max_retries:
                print(f"\n[>] 进入第 {round_num} 轮自动修正...")
                fix_spider_code_with_aider(spider_file, "测试超时", round_num)
        except Exception as e:
            print(f"\n[FAIL] 测试异常: {e}")
            if round_num < max_retries:
                print(f"\n[>] 进入第 {round_num} 轮自动修正...")
                fix_spider_code_with_aider(spider_file, str(e), round_num)
    
    print(f"\n{'='*60}")
    print(f"[FAIL] 经过 {max_retries} 轮自动修正仍然失败")
    print('='*60)
    print("\n[>] 需要人工介入")
    print(f"文件位置: {spider_file}")
    print("\n建议操作：")
    print(f"1. 手动检查爬虫代码: {spider_file}")
    print(f"2. 手动测试: node {spider_file} --latest 5")
    print(f"3. 或者启动 Aider 交互式调试:")
    print(f"   source venv-aider/bin/activate")
    print(f"   aider {spider_file}")
    
    return False


def main():
    """主流程"""
    if len(sys.argv) < 2:
        print("用法: python pure_python_spider_generator.py <target_url> [output_file]")
        print("示例: python pure_python_spider_generator.py https://example.com/news")
        sys.exit(1)
    
    target_url = sys.argv[1]
    parsed_url = urlparse(target_url)
    hostname = parsed_url.hostname or 'unknown'
    output_file = sys.argv[2] if len(sys.argv) > 2 else f"scrapers/scrape_{hostname.replace('.', '_')}.js"
    
    print("\n" + "="*60)
    print("[>] 纯 Python 智能爬虫生成器")
    print("="*60)
    print(f"目标 URL: {target_url}")
    print(f"输出文件: {output_file}")
    
    # Step 1: 侦察
    recon_data = reconnaissance(target_url)
    if not recon_data:
        print("\n[FAIL] 侦察失败")
        sys.exit(1)
    
    # Step 2: 生成代码
    if not generate_spider_code(recon_data, output_file):
        print("\n[FAIL] 代码生成失败")
        sys.exit(1)
    
    # Step 3: 测试 + 自动修正
    if test_and_fix_spider(output_file):
        print("\n" + "="*60)
        print("[OK] 爬虫生成成功！")
        print("="*60)
        print(f"文件位置: {output_file}")
        print(f"\n完整测试命令:")
        print(f"  node {output_file} --latest 10")
    else:
        print("\n[WARN] 自动修正已达到最大轮数")
        print(f"文件位置: {output_file}")


if __name__ == "__main__":
    main()
