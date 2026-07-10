/**
 * 华夏银行 (HXB) 招标公告
 *
 * Usage:
 *   node scrape_hxb.js --info            # 输出爬虫信息
 *   node scrape_hxb.js --latest 5        # 爬取最新 N 条
 *   node scrape_hxb.js --yesterday       # 爬取昨天数据
 *   node scrape_hxb.js --date YYYY-MM-DD # 爬取指定日期数据
 */

const https = require('https');
const fs = require('fs');
const path = require('path');
const { stripHtml } = require('./utility/stripHtml');
const { JsonWriter } = require('./utility/JsonWriter');

const LIST_URL = 'https://www.hxb.com.cn/jrhx/hxzx/hxxw/cggg/zbgg/index.shtml';
const BASE_URL = 'https://www.hxb.com.cn';
const OUTPUT_JSON = path.join(__dirname, '..', 'raw_data', 'hxb_data.json');

// ===================== HTTP 请求 =====================

function httpsGet(url, headers = {}) {
  return new Promise((resolve, reject) => {
    const defaultHeaders = {
      'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
      'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
      'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
      ...headers,
    };
    const req = https.get(url, { headers: defaultHeaders, timeout: 30000 }, (res) => {
      if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
        let loc = res.headers.location;
        if (loc.startsWith('/')) loc = BASE_URL + loc;
        return httpsGet(loc, headers).then(resolve).catch(reject);
      }
      if (res.statusCode !== 200) {
        res.resume();
        return reject(new Error(`HTTP ${res.statusCode} for ${url}`));
      }
      const chunks = [];
      res.on('data', (c) => chunks.push(c));
      res.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
      res.on('error', reject);
    });
    req.on('timeout', () => { req.destroy(); reject(new Error(`Timeout for ${url}`)); });
    req.on('error', reject);
  });
}

// ===================== 限频退避 =====================

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function requestWithBackoff(requestFn, label) {
  let delay = 5000;
  const MAX_ATTEMPTS = 6;
  const MAX_DELAY = 120000;
  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
    try {
      return await requestFn();
    } catch (e) {
      if (attempt < MAX_ATTEMPTS) {
        console.log(`    ⚠ ${e.message}，等待 ${delay/1000}s...`);
        await sleep(delay);
        delay = Math.min(delay * 2, MAX_DELAY);
      } else {
        console.log(`    ✗ ${label}: 失败 (${e.message})`);
        return null;
      }
    }
  }
}

// ===================== 日期工具 =====================

function formatDate(d) {
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}
function getYesterday() {
  const d = new Date(); d.setDate(d.getDate() - 1); return formatDate(d);
}

// ===================== 列表解析 =====================

function parseListPage(html) {
  const items = [];
  // Match: <li class="pro_contli" tag="分行名">...<a href="...">...<span class="fl ...">标题</span>...<span class="fr pro_time">日期</span>...</a>
  const liRegex = /<li\s+class="pro_contli"\s+tag="([^"]*)">\s*<a\s+target="_blank"\s+href="([^"]*)">\s*<span\s+class="fl\s+pro_word\s+title_text_hidden">\s*([\s\S]*?)\s*<\/span>\s*<span\s+class="fr\s+pro_time">\s*([\s\S]*?)\s*<\/span>/gi;
  let m;
  while ((m = liRegex.exec(html)) !== null) {
    const branch = m[1].trim();
    const href = m[2].trim();
    const title = stripHtml(m[3]).trim();
    const date = stripHtml(m[4]).trim();
    if (title && href) {
      const url = href.startsWith('http') ? href : BASE_URL + href;
      items.push({ title, date, url, branch });
    }
  }
  return items;
}

// ===================== 详情解析 =====================

function parseDetailPage(html) {
  // Strategy 1: <div id="content">
  const m = html.match(/<div\s+id="content">([\s\S]*?)<\/div>/i);
  if (m) {
    const content = stripHtml(m[1]);
    if (content.length >= 100) return content;
  }
  // Strategy 2: extract all <p> tags
  const paragraphs = [];
  const pRegex = /<p[^>]*>([\s\S]*?)<\/p>/gi;
  let pm;
  while ((pm = pRegex.exec(html)) !== null) {
    const text = stripHtml(pm[1]).trim();
    if (text.length > 10) paragraphs.push(text);
  }
  if (paragraphs.length > 0) return paragraphs.join('\n\n');
  return '';
}

// ===================== 主流程 =====================

async function main() {
  const args = process.argv.slice(2);

  if (args.includes('--info')) {
    console.log(JSON.stringify({
      name: 'hxb',
      description: '华夏银行招标公告',
      modes: ['latest', 'yesterday', 'date'],
      outputFile: 'raw_data/hxb_data.json',
    }, null, 2));
    return;
  }

  // Parse args
  let mode = 'latest', count = 5, targetDate = null;
  const yesterdayIdx = args.indexOf('--yesterday');
  const latestIdx = args.indexOf('--latest');
  const dateIdx = args.indexOf('--date');
  if (yesterdayIdx >= 0) { mode = 'date'; targetDate = getYesterday(); }
  else if (dateIdx >= 0) { mode = 'date'; targetDate = args[dateIdx + 1]; }
  else if (latestIdx >= 0) { count = parseInt(args[latestIdx + 1]) || 5; }

  console.log(`[华夏银行] 开始爬取 (${mode}${mode === 'date' ? ': ' + targetDate : ''})...`);

  // 1. Fetch list page
  console.log('  1/3 获取列表页...');
  const listHtml = await requestWithBackoff(() => httpsGet(LIST_URL), '列表页');
  if (!listHtml) { console.error('  ✗ 无法获取列表页'); process.exit(1); }

  // 2. Parse list
  let items = parseListPage(listHtml);
  console.log(`  找到 ${items.length} 条公告`);

  // Filter by date if needed
  if (mode === 'date') {
    items = items.filter(it => it.date === targetDate);
    console.log(`  日期 ${targetDate} 匹配 ${items.length} 条`);
    if (items.length === 0) { console.log('  无匹配数据'); return; }
  } else {
    items = items.slice(0, count);
  }

  // 3. Init writer
  const writer = new JsonWriter(OUTPUT_JSON, {
    source: '华夏银行',
    scrapeTime: new Date().toISOString().substring(0, 13),
  });

  // 4. Fetch detail pages
  console.log(`  2/3 开始获取 ${items.length} 条详情...`);
  for (let i = 0; i < items.length; i++) {
    const item = items[i];
    console.log(`  [${i+1}/${items.length}] ${item.title.substring(0, 40)}...`);

    const detailHtml = await requestWithBackoff(() => httpsGet(item.url), item.title.substring(0, 20));
    let content = '';
    if (detailHtml) {
      content = parseDetailPage(detailHtml);
    }

    if (!content || content.length < 50) {
      console.warn(`    ⚠ 内容为空或过短 (${content.length} chars)`);
    }

    writer.addRow({
      title: item.title,
      publishTime: item.date,
      url: item.url,
      content: content || item.title,
    });

    // Rate limit: 2-4 seconds between requests
    if (i < items.length - 1) {
      const wait = 2000 + Math.random() * 2000;
      await sleep(wait);
    }
  }

  console.log(`  3/3 完成！共写入 ${writer.count} 条`);
  console.log(`  输出: ${OUTPUT_JSON}`);
}

main().catch((e) => { console.error('失败:', e.message); process.exit(1); });
