/**
 * 浦发银行采购供应商门户 (spdb)
 * 使用 Playwright 提取 SPA 动态数据
 *
 * Usage:
 *   node scrape_spdb.js --info
 *   node scrape_spdb.js --latest 5
 *   node scrape_spdb.js --yesterday
 *   node scrape_spdb.js --date YYYY-MM-DD
 */

const { chromium } = require('playwright');
const path = require('path');
const { JsonWriter } = require('./utility/JsonWriter');

const OUTPUT_JSON = path.join(__dirname, '..', 'raw_data', 'spdb_data.json');

// ===================== 日期工具 =====================
function formatDate(d) {
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}
function getYesterday() {
  const d = new Date(); d.setDate(d.getDate() - 1); return formatDate(d);
}
function formatScrapeTime() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}`;
}

let browser = null;
async function initBrowser() {
  if (!browser) browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  return browser;
}
async function closeBrowser() { if (browser) { await browser.close(); browser = null; } }

const sleep = (ms) => new Promise(r => setTimeout(r, ms));

async function withRetry(fn, label, maxAttempts = 5) {
  for (let a = 1; a <= maxAttempts; a++) {
    try { return await fn(); }
    catch (e) {
      if (a < maxAttempts) {
        const delay = a * 3000;
        console.log(`    ⚠ ${label} (${a}/${maxAttempts}): ${e.message}，等待 ${delay/1000}s...`);
        await sleep(delay);
      } else { console.log(`    ✗ ${label}: ${e.message}`); throw e; }
    }
  }
}

// ===================== 列表提取 =====================
async function extractListItems(page) {
  return await withRetry(async () => {
    await page.waitForSelector('.list-item', { timeout: 30000 });
    return await page.evaluate(() => {
      const results = [];
      document.querySelectorAll('.list-item').forEach(item => {
        const typeEls = item.querySelectorAll('.type');
        const titleEl = item.querySelector('.title');
        const dateEl = item.querySelector('.date');
        const title = titleEl?.textContent?.trim() || '';
        if (title) {
          results.push({
            title,
            publishTime: dateEl?.textContent?.trim() || '',
            noticeType: typeEls[0]?.textContent?.trim() || '',
            orgType: typeEls[1]?.textContent?.trim() || ''
          });
        }
      });
      return results;
    });
  }, '列表提取');
}

// ===================== 点击+详情提取 =====================
async function clickAndExtract(page, index) {
  return await withRetry(async () => {
    const items = await page.$$('.list-item');
    if (index >= items.length) throw new Error(`索引越界 ${index}/${items.length}`);

    await items[index].click();
    await page.waitForURL(/noticeDetail/, { timeout: 15000 });
    await sleep(2000);
    await page.waitForSelector('.manual-content', { timeout: 15000 });

    const detail = await page.evaluate(() => {
      const titleEl = document.querySelector('.manual-title');
      const title = titleEl?.textContent?.trim() || '';

      const timeEl = document.querySelector('.time-style');
      let publishTime = '';
      if (timeEl) {
        const m = timeEl.textContent.match(/(\d{4}-\d{2}-\d{2})/);
        if (m) publishTime = m[1];
      }

      const contentEl = document.querySelector('.manual-content');
      let content = contentEl?.innerText || '';

      if (content.length < 200) {
        const p = Array.from(document.querySelectorAll('p.MsoNormal'))
          .map(p => p.innerText?.trim()).filter(t => t.length > 10);
        content = p.join('\n\n');
      }
      if (content.length < 200) {
        const p = Array.from(document.querySelectorAll('p'))
          .map(p => p.innerText?.trim()).filter(t => t.length > 20);
        content = p.join('\n\n');
      }
      return { title, content, publishTime };
    });

    let noticeType = '';
    if (detail.title.includes('结果公告') || detail.title.includes('中标') || detail.title.includes('结果公示'))
      noticeType = '结果公告';
    else if (detail.title.includes('采购公告') || detail.title.includes('招标'))
      noticeType = '采购公告';
    else if (detail.title.includes('变更') || detail.title.includes('更正'))
      noticeType = '变更公告';
    else if (detail.title.includes('流标'))
      noticeType = '流标公告';

    return { ...detail, url: page.url(), noticeType };
  }, '详情提取');
}

// ===================== 翻页 =====================
async function goToNextPage(page) {
  const btn = await page.$('.arco-pagination-item-next:not([aria-disabled="true"])');
  if (!btn) return false;
  await btn.click();
  await sleep(2500);
  await page.waitForSelector('.list-item', { timeout: 10000 }).catch(() => {});
  return true;
}

// ===================== 主流程 =====================
async function main() {
  const args = process.argv.slice(2);

  if (args.includes('--info')) {
    console.log(JSON.stringify({
      name: 'spdb',
      description: '浦发银行采购供应商门户 (Playwright)',
      modes: ['latest', 'yesterday', 'date'],
      outputFile: 'raw_data/spdb_data.json',
    }));
    return;
  }

  let mode = 'latest', count = 5, targetDate = null;
  const yi = args.indexOf('--yesterday'), li = args.indexOf('--latest'), di = args.indexOf('--date');
  if (yi >= 0) { mode = 'date'; targetDate = getYesterday(); }
  else if (di >= 0) { mode = 'date'; targetDate = args[di + 1]; }
  else if (li >= 0) { count = parseInt(args[li + 1]) || 5; }

  const writer = new JsonWriter(OUTPUT_JSON, { source: '浦发银行采购供应商门户', scrapeTime: formatScrapeTime() });

  try {
    await initBrowser();
    const context = await browser.newContext({
      userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
      viewport: { width: 1920, height: 1080 }
    });
    const page = await context.newPage();

    console.log(`🚀 开始爬取浦发银行采购供应商门户 (${mode}模式)...`);

    await page.goto('https://ebuy.spdb.com.cn/#/notice', { waitUntil: 'networkidle', timeout: 30000 });
    await sleep(3000);

    let allItems = [];
    let currentPage = 1;
    const MAX_PAGES = 20;

    while (currentPage <= MAX_PAGES) {
      const pageItems = await extractListItems(page);
      if (pageItems.length === 0) { console.log(`  第 ${currentPage} 页: 无数据`); break; }

      allItems = allItems.concat(pageItems.map((item, idx) => ({ ...item, pageIndex: currentPage, itemIndex: idx })));
      console.log(`  第 ${currentPage} 页: ${pageItems.length} 条`);

      if (mode === 'date' && targetDate) {
        const last = pageItems[pageItems.length - 1].publishTime;
        if (last && last < targetDate) { console.log(`  ✓ 最早 ${last} < ${targetDate}，停止翻页`); break; }
      }
      if (mode === 'latest' && allItems.length >= count) break;

      if (!(await goToNextPage(page))) break;
      currentPage++;
    }

    if (mode === 'date' && targetDate) {
      allItems = allItems.filter(item => item.publishTime === targetDate);
      console.log(`📅 日期过滤后: ${allItems.length} 条 (${targetDate})`);
    }
    if (mode === 'latest') allItems = allItems.slice(0, count);

    console.log(`📋 共 ${allItems.length} 条待处理`);

    for (let i = 0; i < allItems.length; i++) {
      const item = allItems[i];
      console.log(`[${i + 1}/${allItems.length}] ${item.title.substring(0, 50)}...`);

      try {
        if (i > 0) {
          await page.goto('https://ebuy.spdb.com.cn/#/notice', { waitUntil: 'networkidle', timeout: 30000 });
          await sleep(2500);
          // 确保列表加载完成
          await page.waitForSelector('.list-item', { timeout: 15000 });
          for (let p = 1; p < item.pageIndex; p++) await goToNextPage(page);
          // 翻页后也要确保列表重新加载
          await page.waitForSelector('.list-item', { timeout: 10000 });
          await sleep(500);
        }

        const detail = await clickAndExtract(page, item.itemIndex);
        if (!detail.content || detail.content.length < 200)
          console.log(`    ⚠ 内容过短 (${detail.content?.length || 0} 字符)`);

        writer.addRow({
          title: detail.title || item.title,
          content: detail.content || item.title,
          publishTime: detail.publishTime || item.publishTime,
          url: detail.url,
          noticeType: detail.noticeType || item.noticeType || ''
        });
        console.log(`    ✓ ${detail.content?.length || 0} 字符`);

        if (i < allItems.length - 1) await sleep(2000 + Math.random() * 1000);
      } catch (e) {
        console.log(`    ✗ 失败: ${e.message}`);
        writer.addRow({ title: item.title, content: item.title, publishTime: item.publishTime, url: '', noticeType: item.noticeType });
        try { await page.goto('https://ebuy.spdb.com.cn/#/notice', { waitUntil: 'networkidle', timeout: 15000 }); await sleep(2000); } catch (_) {}
      }
    }

    console.log(`\n✅ 爬取完成，共 ${writer.count} 条记录`);
    await page.close();
    await context.close();
  } finally {
    await closeBrowser();
  }
}

main().catch(e => { console.error('失败:', e.message); process.exit(1); });
