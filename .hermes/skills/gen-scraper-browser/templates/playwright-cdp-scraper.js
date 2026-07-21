/**
 * Chrome CDP 爬虫模板 - 用于反爬/WAF 场景的兜底方案
 * 
 * 适用场景：
 * - gen-scraper（HTTP API / headless Playwright）失败
 * - 网站有 WAF/反爬，headless 浏览器被拦截
 * - 需要真实 Chrome 浏览器环境（Cookie/Session/JS 指纹）
 * 
 * 原理：
 * - 启动真实 Chrome 浏览器（带 --remote-debugging-port）
 * - Playwright 通过 CDP 协议连接
 * - 对网站来说，这就是普通用户打开的 Chrome，不是自动化工具
 * 
 * Usage:
 *   node scrape_<name>.js --info              # 输出爬虫信息
 *   node scrape_<name>.js --latest 5          # 爬取最新 5 条
 *   node scrape_<name>.js --yesterday         # 爬取昨天的数据
 *   node scrape_<name>.js --date 2025-01-10   # 爬取指定日期的数据
 */

const { chromium } = require('playwright');
const { JsonWriter } = require('./utility/JsonWriter');
const { execSync, spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

// ==================== Configuration ====================
const BASE_URL = '<BASE_URL>';  // 如 https://www.cebbank.com
const LIST_URL = `${BASE_URL}<LIST_PATH>`;  // 如 /site/zhpd/zxgg35/cggg/index.html
const OUTPUT_FILE = path.join(__dirname, '..', 'raw_data', '<name>_data.json');

// ==================== Utility Functions ====================
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

function formatScrapeTime() {
  const now = new Date();
  const pad = n => String(n).padStart(2, '0');
  return `${now.getFullYear()}-${pad(now.getMonth()+1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}`;
}

function parseDate(dateStr) {
  if (!dateStr) return null;
  // 支持多种格式：2025年1月10日、2025-01-10、2025/01/10
  const m = dateStr.match(/(\d{4})年(\d{1,2})月(\d{1,2})日/);
  if (m) return `${m[1]}-${m[2].padStart(2,'0')}-${m[3].padStart(2,'0')}`;
  const m2 = dateStr.match(/(\d{4})[-\/](\d{1,2})[-\/](\d{1,2})/);
  if (m2) return `${m2[1]}-${m2[2].padStart(2,'0')}-${m2[3].padStart(2,'0')}`;
  return null;
}

function getYesterday() {
  const d = new Date();
  d.setDate(d.getDate() - 1);
  const pad = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`;
}

// ==================== Find Chrome ====================
function findChrome() {
  const paths = [
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/usr/bin/google-chrome',
    '/usr/bin/chromium-browser',
  ];
  for (const p of paths) {
    if (fs.existsSync(p)) return p;
  }
  try {
    return execSync('which google-chrome || which chromium-browser || which chromium 2>/dev/null', { encoding: 'utf8' }).trim();
  } catch { return null; }
}

// ==================== Main Scraper ====================
async function scrape(options = {}) {
  const { latest = 0, yesterday = false, date = null } = options;
  console.log('[<网站名称>] 启动 Chrome CDP 爬虫...');

  const chromePath = findChrome();
  if (!chromePath) {
    console.error('找不到 Chrome 浏览器');
    process.exit(1);
  }
  console.log(`Chrome 路径: ${chromePath}`);

  // 启动 Chrome 带远程调试端口（随机端口避免冲突）
  const debugPort = 9222 + Math.floor(Math.random() * 1000);
  const userDataDir = `/tmp/<name>-chrome-${Date.now()}`;

  console.log(`启动 Chrome (调试端口: ${debugPort})...`);
  const chromeProcess = spawn(chromePath, [
    `--remote-debugging-port=${debugPort}`,
    `--user-data-dir=${userDataDir}`,
    '--no-first-run',
    '--no-default-browser-check',
  ], {
    stdio: 'ignore',
    detached: true,
  });

  // 等待 Chrome 启动（必须等够时间）
  await sleep(3000);

  let browser = null;
  try {
    // 通过 CDP 连接到 Chrome
    browser = await chromium.connectOverCDP(`http://localhost:${debugPort}`);
    const contexts = browser.contexts();
    const context = contexts[0] || await browser.newContext();
    const page = context.pages()[0] || await context.newPage();

    console.log('[<网站名称>] 访问列表页...');
    await page.goto(LIST_URL, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await sleep(5000);  // 等 JS 渲染完成

    const content = await page.content();
    console.log(`页面长度: ${content.length}`);

    if (content.length < 2000) {
      console.error('页面内容过短，可能被 WAF 拦截');
      fs.writeFileSync('/tmp/<name>_debug.html', content);
      return;
    }

    // ====== 提取列表（根据实际页面结构调整选择器）======
    const links = await page.evaluate(() => {
      const results = [];
      
      // TODO: 根据目标网站的实际结构调整这个选择器
      // 示例：document.querySelectorAll('div.gg_nr a')
      document.querySelectorAll('<列表选择器>').forEach(el => {
        const href = el.getAttribute('href');
        const title = el.innerText.trim() || el.getAttribute('title');
        if (href && title && title.length > 5) {
          const fullUrl = href.startsWith('http') ? href : `<BASE_URL>${href}`;
          if (!results.some(r => r.url === fullUrl)) {
            results.push({ url: fullUrl, title });
          }
        }
      });
      return results;
    });

    console.log(`找到 ${links.length} 条公告`);

    if (links.length === 0) {
      console.log('未找到公告');
      return;
    }

    // 过滤
    let filteredLinks = links;
    let targetDate = null;
    
    if (yesterday) {
      targetDate = getYesterday();
      console.log(`只爬取 ${targetDate} 的数据`);
    } else if (date) {
      targetDate = date;
      console.log(`只爬取 ${date} 的数据`);
    } else if (latest > 0) {
      filteredLinks = links.slice(0, latest);
      console.log(`只爬取最新 ${latest} 条`);
    }

    const writer = new JsonWriter(OUTPUT_FILE, { source: '<网站名称>', scrapeTime: formatScrapeTime() });

    console.log(`\n开始爬取 ${filteredLinks.length} 条公告...\n`);

    for (let i = 0; i < filteredLinks.length; i++) {
      const link = filteredLinks[i];
      console.log(`[${i+1}/${filteredLinks.length}] ${link.title.substring(0, 50)}...`);

      try {
        await page.goto(link.url, { waitUntil: 'domcontentloaded', timeout: 30000 });
        await sleep(2000);  // 等详情页渲染

        // ====== 提取详情（根据实际页面结构调整选择器）======
        const detail = await page.evaluate(() => {
          // TODO: 根据目标网站的实际结构调整这些选择器
          const titleEl = document.querySelector('<标题选择器>');
          const dateEl = document.querySelector('<日期选择器>');
          const contentEl = document.querySelector('<正文选择器>');

          let content = '';
          if (contentEl) {
            // 提取所有段落并拼接
            content = Array.from(contentEl.querySelectorAll('p'))
              .map(p => p.innerText.trim())
              .filter(t => t.length > 0)
              .join('\n\n');
          }

          return {
            title: titleEl ? titleEl.innerText.trim() : '',
            dateText: dateEl ? dateEl.innerText.trim() : '',
            content
          };
        });

        const publishTime = parseDate(detail.dateText);

        // 客户端日期过滤（--yesterday / --date 模式）
        if (targetDate && publishTime && publishTime !== targetDate) {
          console.log(`  ⊘ 跳过（日期 ${publishTime} ≠ ${targetDate}）`);
          continue;
        }

        writer.addRow({
          publishTime: publishTime || '',
          title: detail.title || link.title,
          url: link.url,
          content: detail.content
        });

        console.log(`  ✓ 已保存 (日期: ${publishTime || '未知'})`);

        if (i < filteredLinks.length - 1) await sleep(1000);  // 请求间隔

      } catch (err) {
        console.log(`  ✗ 失败: ${err.message}`);
      }
    }

    console.log(`\n爬取完成，共 ${writer.count} 条`);
    console.log(`数据已保存到: ${OUTPUT_FILE}`);

  } finally {
    // 必须清理：关闭 browser、kill Chrome、删除临时目录
    if (browser) await browser.close();
    try { chromeProcess.kill(); } catch {}
    try { execSync(`rm -rf "${userDataDir}"`); } catch {}
  }
}

// ==================== CLI Entry Point ====================
if (require.main === module) {
  const args = process.argv.slice(2);

  if (args.includes('--info')) {
    console.log(JSON.stringify({
      name: '<name>',
      description: '<网站名称> (Chrome CDP 兜底方案)',
      modes: ['latest', 'yesterday', 'date'],
      outputFile: 'raw_data/<name>_data.json',
      antiBot: 'chrome-cdp'
    }));
    process.exit(0);
  }

  let latest = 0;
  let yesterday = false;
  let date = null;

  const latestIdx = args.indexOf('--latest');
  const yesterdayIdx = args.indexOf('--yesterday');
  const dateIdx = args.indexOf('--date');

  if (yesterdayIdx >= 0) {
    yesterday = true;
  } else if (dateIdx >= 0) {
    date = args[dateIdx + 1];
    if (!date || !/^\d{4}-\d{2}-\d{2}$/.test(date)) {
      console.error('错误: --date 参数格式必须是 YYYY-MM-DD');
      process.exit(1);
    }
  } else if (latestIdx >= 0) {
    latest = parseInt(args[latestIdx + 1]) || 0;
    if (latest <= 0) {
      console.error('错误: --latest 参数必须是正整数');
      process.exit(1);
    }
  } else {
    console.error('错误: 必须指定 --latest、--yesterday 或 --date 参数');
    process.exit(1);
  }

  scrape({ latest, yesterday, date }).catch(err => {
    console.error('爬虫执行失败:', err.message);
    process.exit(1);
  });
}

module.exports = { scrape };
