/**
 * 徽商银行 (HF Bank) 预公告爬虫
 * 目标页面: https://www.hfbank.com.cn/gyhf/cgpt/jzcg/ygg/index.shtml
 * 列表页: 分页结构，每个 item 有链接+日期
 * 详情页: .articleHead h3 (标题), .tag (类型), em (发布时间), .articleCon (正文)
 *
 * Usage:
 *   node scrape_hfbank.js --info             # 输出元数据 JSON
 *   node scrape_hfbank.js --latest 5         # 爬取最新 N 条
 *   node scrape_hfbank.js --yesterday        # 爬取昨天数据
 *   node scrape_hfbank.js --date YYYY-MM-DD  # 爬取指定日期
 *
 * 使用系统 Chrome CDP 绕过 WAF 检测
 */

const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const { execSync, spawn } = require('child_process');
const { JsonWriter } = require('./utility/JsonWriter');

const OUTPUT_JSON = path.join(__dirname, '..', 'raw_data', 'hfbank_data.json');
const BASE_URL = 'https://www.hfbank.com.cn';
const LIST_URL = `${BASE_URL}/gyhf/cgpt/jzcg/ygg/index.shtml`;
const MAX_PAGES = 10;

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

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ===================== Chrome 启动 =====================
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

// ===================== 主流程 =====================
async function main() {
  const args = process.argv.slice(2);

  if (args.includes('--info')) {
    console.log(JSON.stringify({
      name: 'hfbank',
      description: '徽商银行采购预公告爬虫 (Playwright + Chrome CDP)',
      modes: ['latest', 'yesterday', 'date'],
      outputFile: 'raw_data/hfbank_data.json',
    }));
    return;
  }

  // 参数解析
  let mode = 'latest', count = 5, targetDate = null;
  const yesterdayIdx = args.indexOf('--yesterday');
  const latestIdx = args.indexOf('--latest');
  const dateIdx = args.indexOf('--date');
  if (yesterdayIdx >= 0) { mode = 'date'; targetDate = getYesterday(); }
  else if (dateIdx >= 0) { mode = 'date'; targetDate = args[dateIdx + 1]; }
  else if (latestIdx >= 0) { count = parseInt(args[latestIdx + 1]) || 5; }

  console.log(`🚀 开始爬取徽商银行预公告 (${mode}模式)...`);

  // 查找并启动 Chrome
  const chromePath = findChrome();
  if (!chromePath) {
    console.error('❌ 找不到 Chrome 浏览器');
    process.exit(1);
  }

  const debugPort = 9222 + Math.floor(Math.random() * 1000);
  const userDataDir = `/tmp/hfbank-chrome-${Date.now()}`;

  const chromeProcess = spawn(chromePath, [
    `--remote-debugging-port=${debugPort}`,
    `--user-data-dir=${userDataDir}`,
    '--no-first-run',
    '--no-default-browser-check',
  ], { stdio: 'ignore', detached: true });

  await sleep(3000);

  let browser = null;
  try {
    browser = await chromium.connectOverCDP(`http://localhost:${debugPort}`);
    const context = browser.contexts()[0] || await browser.newContext();
    const page = context.pages()[0] || await context.newPage();

    const writer = new JsonWriter(OUTPUT_JSON, { source: '徽商银行', scrapeTime: formatScrapeTime() });
    const seen = new Set();

    // 逐页处理列表
    for (let pageNo = 1; pageNo <= MAX_PAGES; pageNo++) {
      const listUrl = pageNo === 1
        ? LIST_URL
        : `${BASE_URL}/gyhf/cgpt/jzcg/ygg/index_${pageNo}.shtml`;

      console.log(`  📄 第 ${pageNo} 页: ${listUrl}`);
      await page.goto(listUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
      await sleep(6000);

      const content = await page.content();
      if (content.length < 2000) {
        console.error(`  ❌ 页面内容过短 (${content.length} chars)，可能被 WAF 拦截`);
        break;
      }

      // 提取列表项: div.item > a + span
      const items = await page.evaluate(() => {
        const results = [];
        const container = document.querySelector('#imgArticleList');
        if (!container) return results;

        const divItems = container.querySelectorAll('div.item');
        divItems.forEach(item => {
          const a = item.querySelector('a');
          const span = item.querySelector('span');
          if (!a) return;

          const href = a.getAttribute('href') || '';
          const title = (a.getAttribute('title') || a.textContent || '').trim();
          const dateStr = span ? span.textContent.trim() : '';

          // 只收集详情页链接（排除分类导航链接）
          if (href && title && href.endsWith('.shtml') && !href.endsWith('index.shtml')) {
            // 将相对路径转为绝对路径
            const fullUrl = href.startsWith('http') ? href : `https://www.hfbank.com.cn${href.replace(/\.\.\//g, '').replace(/^\//, '')}`;
            // 更准确的相对路径处理
            let resolvedUrl = href;
            if (!href.startsWith('http')) {
              // ../../../../gyhf/cgpt/jzcg/ygg/316231.shtml
              const parts = href.replace(/\.\.\//g, '').split('/');
              resolvedUrl = `https://www.hfbank.com.cn/${parts.join('/')}`;
            }

            results.push({
              title,
              url: resolvedUrl,
              publishTime: dateStr // 格式 YYYY-MM-DD
            });
          }
        });
        return results;
      });

      console.log(`  📋 找到 ${items.length} 条记录`);

      if (items.length === 0) {
        console.log('  ✓ 没有更多记录，停止翻页');
        break;
      }

      // 日期过滤 (客户端)
      let filteredItems = items;
      if (mode === 'date' && targetDate) {
        filteredItems = items.filter(item => item.publishTime === targetDate);
        console.log(`  日期过滤: ${filteredItems.length}/${items.length} 条匹配 ${targetDate}`);

        // 提前终止：如果当前页所有日期都早于目标日期
        const dates = items.map(i => i.publishTime).filter(d => d);
        if (dates.length > 0) {
          const earliest = dates[dates.length - 1];
          const latest = dates[0];
          if (earliest < targetDate && latest < targetDate) {
            console.log(`  ✓ 当前页最晚日期 ${latest} 早于目标 ${targetDate}，停止翻页`);
            break;
          }
        }
      }

      // 数量限制 (latest 模式)
      if (mode === 'latest') {
        filteredItems = filteredItems.slice(0, count - writer.count);
      }

      // 逐条提取详情
      for (const item of filteredItems) {
        if (seen.has(item.url)) continue;
        seen.add(item.url);

        if (mode === 'latest' && writer.count >= count) break;

        console.log(`  [${writer.count + 1}] ${item.title.substring(0, 40)}...`);

        try {
          await page.goto(item.url, { waitUntil: 'domcontentloaded', timeout: 30000 });
          await sleep(5000);

          const detail = await page.evaluate(() => {
            // 标题
            const h3 = document.querySelector('.articleHead h3');
            const title = h3 ? h3.textContent.trim() : '';

            // 公告类型
            const tag = document.querySelector('.articleHead .tag');
            const noticeType = tag ? tag.textContent.trim() : '';

            // 发布时间
            const ems = document.querySelectorAll('.articleHead em');
            let publishTime = '';
            for (const em of ems) {
              const text = em.textContent.trim();
              const m = text.match(/(\d{4}-\d{2}-\d{2})/);
              if (m) { publishTime = m[1]; break; }
            }

            // 正文
            const articleCon = document.querySelector('.articleCon');
            let content = '';
            if (articleCon) {
              content = articleCon.innerText || articleCon.textContent || '';
            }

            return { title, noticeType, publishTime, content };
          });

          const finalTitle = detail.title || item.title;
          const finalPublishTime = detail.publishTime || item.publishTime;
          const content = detail.content || '';

          if (content.length < 200) {
            console.log(`    ⚠ 内容过短 (${content.length} 字符)`);
          }

          // 公告类型映射
          let noticeType = detail.noticeType || '';
          const typeMap = {
            '预公告': '采购公告',
            '招标公告': '采购公告',
            '采购公告': '采购公告',
            '成交公告': '结果公告',
            '结果公告': '结果公告',
            '中标公告': '结果公告',
            '变更公告': '变更公告',
          };
          if (typeMap[noticeType]) noticeType = typeMap[noticeType];

          writer.addRow({
            title: finalTitle,
            content: content || finalTitle,
            publishTime: finalPublishTime,
            url: item.url,
            noticeType: noticeType
          });

          console.log(`    ✓ ${finalPublishTime} | ${noticeType || '未知类型'} | ${content.length} 字符`);

          // 请求间隔
          await sleep(2000 + Math.random() * 1000);
        } catch (e) {
          console.log(`    ✗ 详情提取失败: ${e.message}`);
          writer.addRow({
            title: item.title,
            content: item.title,
            publishTime: item.publishTime,
            url: item.url,
            noticeType: ''
          });
        }
      }

      // latest 模式达到目标数量就停止
      if (mode === 'latest' && writer.count >= count) {
        console.log(`  ✓ 已达到目标数量 ${count}，停止`);
        break;
      }

      // date 模式：如果当前页有匹配的数据且没有更早的数据了，停止
      if (mode === 'date' && targetDate && filteredItems.length > 0) {
        const dates = items.map(i => i.publishTime).filter(d => d);
        const earliest = dates[dates.length - 1];
        if (earliest < targetDate) {
          console.log(`  ✓ 当前页最早日期 ${earliest} 早于目标 ${targetDate}，停止翻页`);
          break;
        }
      }
    }

    console.log(`\n✅ 爬取完成，共 ${writer.count} 条记录`);
  } finally {
    if (browser) await browser.close();
    if (chromeProcess) {
      try { process.kill(-chromeProcess.pid); } catch {}
    }
  }
}

main().catch((e) => { console.error('失败:', e.message); process.exit(1); });
