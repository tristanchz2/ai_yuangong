/**
 * 长沙银行 (CSB) 招标公告爬虫
 *
 * Usage:
 *   node scrape_cscb.js --info             # 输出元数据 JSON
 *   node scrape_cscb.js --latest 5         # 爬取最新 N 条
 *   node scrape_cscb.js --yesterday        # 爬取昨天数据
 *   node scrape_cscb.js --date YYYY-MM-DD  # 爬取指定日期
 */

const https = require('https');
const fs = require('fs');
const path = require('path');
const { stripHtml } = require('./utility/stripHtml');
const { JsonWriter } = require('./utility/JsonWriter');

const OUTPUT_JSON = path.join(__dirname, '..', 'raw_data', 'cscb_data.json');
const BASE_URL = 'https://www.cscb.cn';
const LIST_URL = '/site/col173/list.html';

// ===================== HTTP 请求 =====================
function httpsGet(urlPath, headers = {}) {
  return new Promise((resolve, reject) => {
    const options = {
      hostname: 'www.cscb.cn',
      path: urlPath,
      method: 'GET',
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Referer': 'https://www.cscb.cn/',
        ...headers,
      },
      rejectUnauthorized: false,
      secureProtocol: 'TLS_method',
      secureOptions: require('constants').SSL_OP_LEGACY_SERVER_CONNECT,
    };

    const req = https.request(options, (res) => {
      let data = '';
      res.on('data', (chunk) => data += chunk);
      res.on('end', () => {
        if (res.statusCode >= 400) {
          reject(new Error(`HTTP ${res.statusCode}: ${urlPath}`));
        } else {
          resolve(data);
        }
      });
    });

    req.on('error', (e) => reject(e));
    req.setTimeout(30000, () => {
      req.destroy();
      reject(new Error(`Timeout: ${urlPath}`));
    });
    req.end();
  });
}

// ===================== 限频退避 =====================
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function requestWithBackoff(requestFn, label) {
  let delay = 3000;
  const MAX_ATTEMPTS = 5;
  const MAX_DELAY = 60000;
  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
    try {
      return await requestFn();
    } catch (e) {
      if (attempt < MAX_ATTEMPTS) {
        console.log(`    ⚠ ${e.message}，等待 ${delay/1000}s...`);
        await sleep(delay);
        delay = Math.min(delay * 2, MAX_DELAY);
      } else {
        console.log(`    ✗ ${label}: 失败 - ${e.message}`);
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
  const d = new Date();
  d.setDate(d.getDate() - 1);
  return formatDate(d);
}

function formatScrapeTime() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}`;
}

// 将 "2026.07.29" 格式转为 "2026-07-29"
function normalizeDate(dateStr) {
  if (!dateStr) return '';
  return dateStr.replace(/\./g, '-');
}

// ===================== 列表页解析 =====================
function parseListPage(html) {
  const items = [];
  // 匹配列表项：日期 + 标题 + 链接
  // 格式：<li><span>2026.07.29</span><a href="/site/col173/371248.html" class="tit"><i>·</i>标题</a></li>
  const itemRegex = /<li[^>]*>\s*<span[^>]*>(\d{4}\.\d{2}\.\d{2})<\/span>\s*<a[^>]*href="([^"]+)"[^>]*class="tit"[^>]*>[\s\S]*?<\/a>\s*<\/li>/gi;
  let match;
  while ((match = itemRegex.exec(html)) !== null) {
    const fullMatch = match[0];
    const date = match[1];
    const href = match[2];
    
    // 提取标题：从 <a> 标签内容中去掉 <i>·</i> 标签
    const titleMatch = fullMatch.match(/<a[^>]*>([\s\S]*?)<\/a>/i);
    let title = '';
    if (titleMatch) {
      title = titleMatch[1]
        .replace(/<i[^>]*>[\s\S]*?<\/i>/gi, '') // 去掉 <i>·</i>
        .replace(/<[^>]+>/g, '') // 去掉其他 HTML 标签
        .trim();
    }
    
    if (!title) continue;
    
    items.push({
      date: normalizeDate(date),
      href: href,
      title: title,
    });
  }
  return items;
}

// ===================== 详情页解析 =====================
function parseDetailPage(html) {
  let content = '';
  
  // 策略 1: 精确选择器 .NewsInfoCon
  const newsInfoConMatch = html.match(/<div[^>]*class="NewsInfoCon"[^>]*>([\s\S]*?)<\/div>/i);
  if (newsInfoConMatch) {
    content = stripHtml(newsInfoConMatch[1]);
  }
  
  // 策略 2: 提取所有 <p> 标签（当找不到 NewsInfoCon 时）
  if (!content || content.length < 200) {
    const paragraphs = [];
    const pMatches = html.match(/<p[^>]*>([\s\S]*?)<\/p>/gi) || [];
    for (const p of pMatches) {
      const text = stripHtml(p).trim();
      if (text.length > 20) {
        paragraphs.push(text);
      }
    }
    if (paragraphs.length > 0) {
      content = paragraphs.join('\n\n');
    }
  }
  
  if (content.length < 200) {
    console.warn('    ⚠ 提取的内容过短，可能提取失败');
  }
  
  return content;
}

// ===================== 主流程 =====================
async function main() {
  const args = process.argv.slice(2);

  if (args.includes('--info')) {
    console.log(JSON.stringify({
      name: 'cscb',
      description: '长沙银行招标公告',
      modes: ['latest', 'yesterday', 'date'],
      outputFile: 'raw_data/cscb_data.json',
    }));
    return;
  }

  let mode = 'latest', count = 5, targetDate = null;
  const yesterdayIdx = args.indexOf('--yesterday');
  const latestIdx = args.indexOf('--latest');
  const dateIdx = args.indexOf('--date');
  if (yesterdayIdx >= 0) { mode = 'date'; targetDate = getYesterday(); }
  else if (dateIdx >= 0) { mode = 'date'; targetDate = args[dateIdx + 1]; }
  else if (latestIdx >= 0) { count = parseInt(args[latestIdx + 1]) || 5; }

  const scrapeTime = formatScrapeTime();
  const writer = new JsonWriter(OUTPUT_JSON, { source: 'cscb', scrapeTime });

  console.log(`🕷️  开始爬取长沙银行招标公告...`);
  console.log(`📅 模式: ${mode === 'latest' ? `最新 ${count} 条` : `日期 ${targetDate}`}`);
  console.log();

  // 1. 获取列表页
  const listHtml = await requestWithBackoff(() => httpsGet(LIST_URL), '列表页');
  if (!listHtml) {
    console.error('❌ 无法获取列表页');
    process.exit(1);
  }

  let items = parseListPage(listHtml);
  console.log(`✓ 列表页解析成功，找到 ${items.length} 条公告`);

  // 2. 日期过滤（客户端）
  if (mode === 'date') {
    items = items.filter(item => item.date === targetDate);
    console.log(`✓ 日期过滤后: ${items.length} 条 (${targetDate})`);
    if (items.length === 0) {
      console.log('⚠️  没有找到符合条件的公告');
      return;
    }
  } else if (mode === 'latest') {
    items = items.slice(0, count);
  }

  // 3. 逐个获取详情
  let successCount = 0;
  for (let i = 0; i < items.length; i++) {
    const item = items[i];
    const detailUrl = item.href.startsWith('http') ? item.href : BASE_URL + item.href;
    
    console.log(`[${i + 1}/${items.length}] ${item.title.substring(0, 40)}...`);
    
    const detailHtml = await requestWithBackoff(() => httpsGet(item.href), `详情 ${i + 1}`);
    if (!detailHtml) {
      console.log(`    ✗ 详情获取失败，跳过`);
      continue;
    }

    const content = parseDetailPage(detailHtml);
    
    const row = {
      title: item.title,
      content: content,
      publishTime: item.date,
      url: detailUrl,
      noticeType: '招标公告',
    };

    writer.addRow(row);
    successCount++;
    console.log(`    ✓ content: ${content.length} 字符`);
    
    if (i < items.length - 1) {
      await sleep(2000 + Math.random() * 2000);
    }
  }

  console.log();
  console.log(`✅ 完成！成功爬取 ${successCount} 条公告`);
}

main().catch((e) => {
  console.error('失败:', e.message);
  process.exit(1);
});
