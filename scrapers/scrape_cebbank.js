/**
 * 光大银行采购公告爬虫
 * 目标页面: https://www.cebbank.com/site/zhpd/zxgg35/cggg/index.html
 * 列表页: /site/zhpd/zxgg35/cggg/index.html（仅标题+链接，无日期，需进详情页取日期）
 * 详情页: /site/zhpd/zxgg35/cggg/{ID}/index.html
 * 翻页: 列表底部"下一页"为 JS 驱动（href 为空），需点击翻页
 *
 * 使用方法:
 *   node scrape_cebbank.js --info              # 输出爬虫信息
 *   node scrape_cebbank.js --latest 5          # 爬取最新 5 条
 *   node scrape_cebbank.js --yesterday         # 爬取昨天的数据（自动翻页直到覆盖昨天）
 *   node scrape_cebbank.js --date 2026-07-22   # 爬取指定日期的数据
 */

const { chromium } = require('playwright');
const { JsonWriter } = require('./utility/JsonWriter');
const { execSync, spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const BASE_URL = 'https://www.cebbank.com';
const LIST_URL = `${BASE_URL}/site/zhpd/zxgg35/cggg/index.html`;
const OUTPUT_FILE = path.join(__dirname, '..', 'raw_data', 'cebbank_data.json');
const MAX_PAGES = 15; // 翻页上限，防止死循环

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

function formatScrapeTime() {
  const now = new Date();
  const pad = n => String(n).padStart(2, '0');
  return `${now.getFullYear()}-${pad(now.getMonth()+1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}`;
}

function formatDate(d) {
  const pad = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`;
}

function getYesterday() {
  const d = new Date();
  d.setDate(d.getDate() - 1);
  return formatDate(d);
}

function parseDate(dateStr) {
  if (!dateStr) return null;
  const m = dateStr.match(/(\d{4})年(\d{1,2})月(\d{1,2})日/);
  if (m) return `${m[1]}-${m[2].padStart(2,'0')}-${m[3].padStart(2,'0')}`;
  const m2 = dateStr.match(/(\d{4})-(\d{1,2})-(\d{1,2})/);
  if (m2) return `${m2[1]}-${m2[2].padStart(2,'0')}-${m2[3].padStart(2,'0')}`;
  return null;
}

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

// 提取当前列表页的公告链接（标题 + URL）
async function extractListLinks(page) {
  return await page.evaluate(() => {
    const results = [];
    document.querySelectorAll('div.gg_nr a').forEach(a => {
      const href = a.getAttribute('href');
      const title = a.innerText.trim() || a.getAttribute('title');
      if (href && title && title.length > 5) {
        const fullUrl = href.startsWith('http') ? href : `https://www.cebbank.com${href}`;
        if (!results.some(r => r.url === fullUrl)) {
          results.push({ url: fullUrl, title });
        }
      }
    });
    return results;
  });
}

// 访问详情页，提取标题/日期/正文
async function fetchDetail(page, link) {
  await page.goto(link.url, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await sleep(2000);
  const detail = await page.evaluate(() => {
    const titleEl = document.querySelector('div.title');
    const dateEl = document.querySelector('div.creatDate');
    const contentEl = document.querySelector('div.xilan_con');
    let content = '';
    if (contentEl) {
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
  return {
    title: detail.title || link.title,
    publishTime: parseDate(detail.dateText) || '',
    url: link.url,
    content: detail.content
  };
}

// 点击"下一页"翻页。成功翻到新的一页返回 true；已是最后一页/无翻页按钮返回 false
async function goToNextPage(page) {
  const before = await page.evaluate(() => {
    const a = document.querySelector('div.gg_nr a');
    return a ? a.getAttribute('href') : '';
  });

  const clicked = await page.evaluate(() => {
    const anchors = Array.from(document.querySelectorAll('a'));
    const next = anchors.find(a => {
      const t = (a.innerText || '').trim();
      return t === '下一页' || t === '下页' || t === '>';
    });
    if (!next) return false;
    // 已被禁用（常见 disabled 类名/属性）则视为最后一页
    const cls = (next.className || '') + ' ' + (next.parentElement?.className || '');
    if (next.hasAttribute('disabled') || /disabled|noMore|last|cur/i.test(cls)) return false;
    next.click();
    return true;
  });
  if (!clicked) return false;

  await sleep(3000);
  const after = await page.evaluate(() => {
    const a = document.querySelector('div.gg_nr a');
    return a ? a.getAttribute('href') : '';
  });
  // 翻页后首条链接没变 → 说明没有真正翻页（已到最后一页）
  return after !== before;
}

async function scrape(options = {}) {
  const { mode = 'latest', count = 0, targetDate = null } = options;
  console.log(`[光大银行] 启动爬虫... (模式: ${mode}${targetDate ? ', 目标日期: ' + targetDate : ''}${mode === 'latest' ? ', 最新 ' + count + ' 条' : ''})`);

  const chromePath = findChrome();
  if (!chromePath) {
    console.error('找不到 Chrome 浏览器');
    process.exit(1);
  }
  console.log(`Chrome 路径: ${chromePath}`);

  // 启动 Chrome 带远程调试端口
  const debugPort = 9222 + Math.floor(Math.random() * 1000);
  const userDataDir = `/tmp/cebbank-chrome-${Date.now()}`;

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

  // 等待 Chrome 启动
  await sleep(3000);

  let browser = null;
  try {
    browser = await chromium.connectOverCDP(`http://localhost:${debugPort}`);
    const contexts = browser.contexts();
    const context = contexts[0] || await browser.newContext();
    const page = context.pages()[0] || await context.newPage();

    console.log('[光大银行] 访问列表页...');
    await page.goto(LIST_URL, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await sleep(5000);

    const content = await page.content();
    console.log(`页面长度: ${content.length}`);

    if (content.length < 2000) {
      console.error('页面内容过短，可能被 WAF 拦截');
      fs.writeFileSync('/tmp/cebbank_debug.html', content);
      return;
    }

    const writer = new JsonWriter(OUTPUT_FILE, { source: '光大银行', scrapeTime: formatScrapeTime() });

    let saved = 0;
    let visited = 0;
    let stop = false;
    const seen = new Set();

    // 逐页处理：列表只有标题/链接，日期需进详情页获取，故边翻页边访问详情边判断
    for (let pageNo = 1; pageNo <= MAX_PAGES && !stop; pageNo++) {
      const links = await extractListLinks(page);
      const newLinks = links.filter(l => !seen.has(l.url));
      newLinks.forEach(l => seen.add(l.url));
      console.log(`\n第 ${pageNo} 页: ${links.length} 条（新增 ${newLinks.length} 条）`);

      if (newLinks.length === 0) {
        console.log('  本页无新增公告，停止');
        break;
      }

      let pageMinDate = null; // 本页最早日期，用于 date 模式提前终止翻页

      for (const link of newLinks) {
        visited++;
        console.log(`[${visited}] ${link.title.substring(0, 50)}...`);
        try {
          const row = await fetchDetail(page, link);
          const d = row.publishTime;
          if (d && (!pageMinDate || d < pageMinDate)) pageMinDate = d;

          if (mode === 'date') {
            if (d === targetDate) {
              writer.addRow(row);
              saved++;
              console.log(`  ✓ 命中 ${d}，已保存`);
            } else {
              console.log(`  · 日期 ${d || '未知'}，跳过`);
            }
          } else {
            // latest 模式
            writer.addRow(row);
            saved++;
            console.log(`  ✓ 已保存 (日期: ${d || '未知'})`);
            if (count > 0 && saved >= count) { stop = true; break; }
          }
          await sleep(1000);
        } catch (err) {
          console.log(`  ✗ 失败: ${err.message}`);
        }
      }

      if (stop) break;

      // date 模式：本页最早日期已早于目标日期 → 后续页面更旧，停止翻页
      if (mode === 'date' && pageMinDate && pageMinDate < targetDate) {
        console.log(`  ✓ 本页最早 ${pageMinDate} 已早于 ${targetDate}，停止翻页`);
        break;
      }

      // 翻到下一页
      if (!(await goToNextPage(page))) {
        console.log('  已到最后一页');
        break;
      }
    }

    console.log(`\n爬取完成，共 ${writer.count} 条`);
    console.log(`数据已保存到: ${OUTPUT_FILE}`);

  } finally {
    if (browser) await browser.close();
    try { chromeProcess.kill(); } catch {}
    await sleep(1500); // 等 Chrome 释放文件句柄，避免临时目录删不干净
    try { execSync(`rm -rf "${userDataDir}"`); } catch {}
  }
}

// CLI
if (require.main === module) {
  const args = process.argv.slice(2);

  if (args.includes('--info')) {
    console.log(JSON.stringify({
      name: 'cebbank',
      description: '光大银行采购公告爬虫',
      modes: ['latest', 'yesterday', 'date'],
      outputFile: 'raw_data/cebbank_data.json',
      antiBot: 'chrome-cdp'
    }));
    process.exit(0);
  }

  let mode = 'latest';
  let count = 0;
  let targetDate = null;

  const latestIdx = args.indexOf('--latest');
  const yesterdayIdx = args.indexOf('--yesterday');
  const dateIdx = args.indexOf('--date');

  if (yesterdayIdx >= 0) {
    mode = 'date';
    targetDate = getYesterday();
  } else if (dateIdx >= 0) {
    mode = 'date';
    targetDate = args[dateIdx + 1];
    if (!targetDate || !/^\d{4}-\d{2}-\d{2}$/.test(targetDate)) {
      console.error('错误: --date 参数格式必须是 YYYY-MM-DD');
      process.exit(1);
    }
  } else if (latestIdx >= 0) {
    mode = 'latest';
    count = parseInt(args[latestIdx + 1]) || 0;
    if (count <= 0) {
      console.error('错误: --latest 参数必须是正整数');
      process.exit(1);
    }
  } else {
    console.error('错误: 必须指定 --latest、--yesterday 或 --date 参数');
    process.exit(1);
  }

  scrape({ mode, count, targetDate }).catch(err => {
    console.error('爬虫执行失败:', err.message);
    process.exit(1);
  });
}

module.exports = { scrape };
