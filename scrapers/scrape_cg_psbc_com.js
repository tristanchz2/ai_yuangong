/**
 * 爬虫名称: Auto-generated Spider
 * 目标网站: https://cg.psbc.com/cms/default/webfile/1ywgg2/index.html
 * 生成时间: 2026-07-07 17:51:07
 * 技术方案: Node.js + Playwright
 * 反爬处理: 启用 Stealth
 */

const playwright = require('playwright');
const fs = require('fs');
const path = require('path');

// ==================== 配置区 ====================
const CONFIG = {
    targetUrl: 'https://cg.psbc.com/cms/default/webfile/1ywgg2/index.html',
    outputDir: 'raw_data',
    outputFile: 'scrape_cg_psbc_com.json',
    headless: true,  // 是否无头模式
    maxRetries: 3,   // 最大重试次数
};

// ==================== 主函数 ====================
async function main() {
    console.log('🚀 启动爬虫...');
    console.log('目标:', CONFIG.targetUrl);
    
    // 解析命令行参数
    const args = process.argv.slice(2);
    let latestCount = null;
    
    for (let i = 0; i < args.length; i++) {
        if (args[i] === '--latest' && i + 1 < args.length) {
            latestCount = parseInt(args[i + 1]);
        }
    }
    
    if (latestCount) {
        console.log(`📊 只抓取最近 ${latestCount} 条`);
    }
    
    // 启动浏览器
    const browser = await playwright.chromium.launch({
        headless: CONFIG.headless,
        args: [
            '--disable-blink-features=AutomationControlled',
            '--no-sandbox',
        ],
    });
    
    const context = await browser.newContext({
        userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        viewport: { width: 1920, height: 1080 },
    });
    
    // 注入 stealth 脚本（反爬）
    await context.addInitScript(() => {
        Object.defineProperty(navigator, 'webdriver', {{ get: () => undefined }});
        Object.defineProperty(navigator, 'plugins', {{ get: () => [1, 2, 3, 4, 5] }});
        window.chrome = {{ runtime: {{}} }};
    });
    
    const page = await context.newPage();
    
    try {
        // 导航到目标页面
        console.log('📄 导航到目标页面...');
        await page.goto(CONFIG.targetUrl, { 
            waitUntil: 'domcontentloaded',
            timeout: 30000 
        });
        
        // 等待页面加载
        await page.waitForTimeout(2000);
        
        // TODO: 根据实际页面结构调整选择器
        console.log('🔍 提取数据...');
        
        const items = await page.evaluate(() => {
            const results = [];
            
            // TODO: 修改这里的选择器以匹配目标网站
            const elements = document.querySelectorAll('.item, .news-item, .article, li');
            
            elements.forEach((el, index) => {
                const titleEl = el.querySelector('.title, h2, h3, a');
                const linkEl = el.querySelector('a');
                const dateEl = el.querySelector('.date, time, .publish-date');
                
                if (titleEl || linkEl) {
                    results.push({
                        title: titleEl ? titleEl.textContent.trim() : '',
                        link: linkEl ? linkEl.href : '',
                        date: dateEl ? dateEl.textContent.trim() : '',
                        index: index,
                    });
                }
            });
            
            return results;
        });
        
        console.log(`✅ 提取到 ${items.length} 条数据`);
        
        // 限制数量
        const limitedItems = latestCount ? items.slice(0, latestCount) : items;
        
        // 保存数据
        const outputPath = path.join(CONFIG.outputDir, CONFIG.outputFile);
        fs.mkdirSync(CONFIG.outputDir, { recursive: true });
        fs.writeFileSync(outputPath, JSON.stringify(limitedItems, null, 2), 'utf-8');
        
        console.log(`💾 数据已保存: ${outputPath}`);
        console.log(`📊 共 ${limitedItems.length} 条记录`);
        
        if (limitedItems.length > 0) {
            console.log('\n第一条数据示例:');
            console.log(JSON.stringify(limitedItems[0], null, 2));
        }
        
    } catch (error) {
        console.error('❌ 爬虫出错:', error.message);
        throw error;
    } finally {
        await browser.close();
        console.log('👋 浏览器已关闭');
    }
}

// 运行
main().catch(err => {
    console.error('Fatal error:', err);
    process.exit(1);
});
