/**
 * 爬虫模板 — 列表页模式
 * 
 * 适用场景：目标网站有列表页，每条记录包含标题、链接、日期等基本信息
 * 需要点击进入详情页获取完整内容
 * 
 * 使用方法：
 * 1. 复制此文件为 scrape_<site_name>.js
 * 2. 修改 CONFIG 中的选择器和 URL
 * 3. 调整 extractItem() 函数提取字段
 * 4. 运行测试：node scrape_<site_name>.js --latest 5
 */

const playwright = require('playwright');
const fs = require('fs');
const path = require('path');

// ==================== 配置区（需要修改）====================
const CONFIG = {
    // 列表页 URL（支持分页占位符 {page}）
    listUrl: 'https://example.com/list?page={page}',
    
    // 列表项选择器（每条记录的容器）
    itemSelector: '.news-item',
    
    // 各字段选择器（相对于 itemSelector）
    fields: {
        title: '.title a',           // 标题
        link: '.title a',            // 链接（href 属性）
        date: '.date',               // 发布日期
        summary: '.summary',         // 摘要（可选）
    },
    
    // 分页按钮选择器（可选，用于自动翻页）
    nextButton: '.pagination .next',
    
    // 输出文件路径
    outputFile: '../raw_data/example_data.json',
};
// =========================================================

async function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

async function extractItem(page, element) {
    /**
     * 从单个列表项中提取数据
     * @param {Page} page - Playwright 页面对象
     * @param {ElementHandle} element - 列表项元素
     * @returns {Object|null} 提取的数据对象，如果提取失败返回 null
     */
    try {
        const data = {};
        
        // 提取标题
        if (CONFIG.fields.title) {
            data.title = await element.$eval(CONFIG.fields.title, el => el.textContent.trim()).catch(() => '');
        }
        
        // 提取链接
        if (CONFIG.fields.link) {
            data.link = await element.$eval(CONFIG.fields.link, el => el.href).catch(() => '');
        }
        
        // 提取日期
        if (CONFIG.fields.date) {
            data.date = await element.$eval(CONFIG.fields.date, el => el.textContent.trim()).catch(() => '');
        }
        
        // 提取摘要
        if (CONFIG.fields.summary) {
            data.summary = await element.$eval(CONFIG.fields.summary, el => el.textContent.trim()).catch(() => '');
        }
        
        // 过滤空数据
        if (!data.title && !data.link) {
            return null;
        }
        
        return data;
    } catch (error) {
        console.error('提取单条数据失败:', error.message);
        return null;
    }
}

async function scrapeListPage(browser, pageNum, limit = null) {
    /**
     * 爬取单个列表页
     * @param {Browser} browser - Playwright 浏览器实例
     * @param {number} pageNum - 页码（从 1 开始）
     * @param {number|null} limit - 最多爬取条数（null 表示不限制）
     * @returns {Array} 提取的数据数组
     */
    const page = await browser.newPage();
    const url = CONFIG.listUrl.replace('{page}', pageNum);
    
    console.log(`  📄 正在爬取第 ${pageNum} 页: ${url}`);
    
    try {
        await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
        await sleep(2000); // 等待动态内容加载
        
        const items = await page.$$(CONFIG.itemSelector);
        console.log(`  找到 ${items.length} 条记录`);
        
        const results = [];
        for (let i = 0; i < items.length; i++) {
            if (limit && results.length >= limit) break;
            
            const data = await extractItem(page, items[i]);
            if (data) {
                results.push(data);
            }
        }
        
        console.log(`  ✅ 成功提取 ${results.length} 条数据`);
        return results;
    } catch (error) {
        console.error(`  ❌ 第 ${pageNum} 页爬取失败:`, error.message);
        return [];
    } finally {
        await page.close();
    }
}

async function main() {
    const args = process.argv.slice(2);
    const isLatest = args.includes('--latest');
    const latestCount = isLatest ? parseInt(args[args.indexOf('--latest') + 1]) || 5 : null;
    const isYesterday = args.includes('--yesterday');
    
    console.log('🚀 启动爬虫...');
    console.log(`   模式: ${isYesterday ? '昨天数据' : (latestCount ? `最新 ${latestCount} 条` : '全量')}`);
    
    const browser = await playwright.chromium.launch({
        headless: true,
        args: ['--no-sandbox', '--disable-setuid-sandbox'],
    });
    
    try {
        let allResults = [];
        let pageNum = 1;
        let hasMore = true;
        
        while (hasMore) {
            const results = await scrapeListPage(browser, pageNum, latestCount);
            allResults = allResults.concat(results);
            
            // 检查是否达到限制
            if (latestCount && allResults.length >= latestCount) {
                allResults = allResults.slice(0, latestCount);
                console.log(`\n✅ 已达到限制 (${latestCount} 条)，停止爬取`);
                break;
            }
            
            // 检查是否有下一页
            if (results.length === 0 || results.length < 10) {
                hasMore = false;
                console.log('\n✅ 没有更多数据');
            } else {
                pageNum++;
                // 简单延迟，避免请求过快
                await sleep(1000);
            }
        }
        
        // 保存结果
        const outputDir = path.dirname(CONFIG.outputFile);
        if (!fs.existsSync(outputDir)) {
            fs.mkdirSync(outputDir, { recursive: true });
        }
        
        fs.writeFileSync(CONFIG.outputFile, JSON.stringify(allResults, null, 2), 'utf-8');
        console.log(`\n💾 数据已保存到: ${CONFIG.outputFile}`);
        console.log(`   共 ${allResults.length} 条记录`);
        
    } catch (error) {
        console.error('❌ 爬虫执行失败:', error);
        process.exit(1);
    } finally {
        await browser.close();
    }
}

main().catch(console.error);
