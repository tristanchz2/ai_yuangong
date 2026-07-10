/**
 * 渤海银行渤采易采平台 (cbhb) 采购公告爬虫
 *
 * Usage:
 *   node scrape_cbhb.js --latest 5    # 爬取最新 N 条
 *   node scrape_cbhb.js --yesterday   # 爬取昨天数据
 *   node scrape_cbhb.js --date YYYY-MM-DD  # 爬取指定日期
 */

const https = require('https');
const fs = require('fs');
const path = require('path');

const { stripHtml } = require('./utility/stripHtml');
const { JsonWriter } = require('./utility/JsonWriter');

const OUTPUT_JSON = path.join(__dirname, '..', 'raw_data', 'cbhb_data.json');
const BASE_URL = 'https://app.bhypt.cbhb.com.cn';

// ===================== HTTP 请求 =====================
function httpsGet(url, options = {}) {
  return new Promise((resolve, reject) => {
    const urlObj = new URL(url);
    const reqOptions = {
      hostname: urlObj.hostname,
      port: 443,
      path: urlObj.pathname + urlObj.search,
      method: 'GET',
      headers: {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        ...options.headers
      },
      timeout: 30000
    };

    const req = https.request(reqOptions, (res) => {
      if (res.statusCode !== 200) {
        reject(new Error(`HTTP ${res.statusCode}`));
        return;
      }

      const chunks = [];
      res.on('data', (chunk) => chunks.push(chunk));
      res.on('end', () => {
        const buffer = Buffer.concat(chunks);
        resolve(buffer.toString('utf-8'));
      });
    });

    req.on('error', reject);
    req.on('timeout', () => {
      req.destroy();
      reject(new Error('Request timeout'));
    });

    req.end();
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
      const data = await requestFn();
      return data;
    } catch (e) {
      if (attempt < MAX_ATTEMPTS) {
        console.log(`    ⚠ ${e.message}，等待 ${delay/1000}s...`);
        await sleep(delay);
        delay = Math.min(delay * 2, MAX_DELAY);
      } else {
        console.log(`    ✗ ${label}: 失败 - ${e.message}`);
        throw e;
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
function formatScrapeTime() { const d = new Date(); const pad = (n) => String(n).padStart(2, '0'); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}`; }

// ===================== 列表页解析 =====================
function parseListPage(html) {
  const items = [];
  
  // 匹配每个列表项: <li name="li_name">...</li>
  const liRegex = /<li name="li_name">([\s\S]*?)<\/li>/gi;
  let liMatch;
  
  while ((liMatch = liRegex.exec(html)) !== null) {
    const liContent = liMatch[1];
    
    // 提取链接和标题
    const linkMatch = liContent.match(/<a[^>]*href="([^"]*)"[^>]*title="([^"]*)"[^>]*>/i);
    if (!linkMatch) continue;
    
    const detailPath = linkMatch[1];
    const title = linkMatch[2];
    
    // 提取日期 - 允许 <em> 标签内有空白字符和换行
    const dateMatch = liContent.match(/<em>\s*(\d{4}-\d{2}-\d{2})\s*<\/em>/i);
    const date = dateMatch ? dateMatch[1] : '';
    
    // 构造完整 URL
    const detailUrl = detailPath.startsWith('http') ? detailPath : BASE_URL + detailPath;
    
    items.push({
      title: stripHtml(title).trim(),
      date,
      detailUrl,
      detailPath
    });
  }
  
  return items;
}

// ===================== 详情页解析（关键！） =====================
function parseDetailPage(html) {
  let content = '';
  
  // 策略 1: 精确选择器 - <div class="main-text">
  const mainTextMatch = html.match(/<div class="main-text">([\s\S]*?)<\/div>/i);
  if (mainTextMatch) {
    content = stripHtml(mainTextMatch[1]);
  }
  
  // 策略 2: 提取所有 <p> 标签（当找不到 main-text 容器时）
  if (!content || content.length < 200) {
    const paragraphs = [];
    const pMatches = html.match(/<p[^>]*>([\s\S]*?)<\/p>/gi) || [];
    
    for (const p of pMatches) {
      const text = stripHtml(p).trim();
      if (text.length > 20) {  // 过滤空段落
        paragraphs.push(text);
      }
    }
    
    if (paragraphs.length > 0) {
      content = paragraphs.join('\n\n');
    }
  }
  
  // 清理内容
  content = content.replace(/\s+/g, ' ').trim();
  
  // 验证内容长度
  if (content.length < 200) {
    console.warn(`    ⚠ 提取的内容过短 (${content.length} chars)，可能提取失败`);
  }
  
  return { content };
}

// ===================== 主流程 =====================
async function main() {
  const args = process.argv.slice(2);

  if (args.includes('--info')) {
    console.log(JSON.stringify({
      name: 'cbhb',
      description: '渤海银行渤采易采平台采购公告',
      modes: ['latest', 'yesterday', 'date'],
      outputFile: 'raw_data/cbhb_data.json',
    }));
    return;
  }

  // 参数解析
  let mode = 'latest', count = 5, targetDate = null;
  const yesterdayIdx = args.indexOf('--yesterday');
  const latestIdx = args.indexOf('--latest');
  const dateIdx = args.indexOf('--date');
  
  if (yesterdayIdx >= 0) {
    mode = 'date';
    targetDate = getYesterday();
  } else if (dateIdx >= 0) {
    mode = 'date';
    targetDate = args[dateIdx + 1];
  } else if (latestIdx >= 0) {
    count = parseInt(args[latestIdx + 1]) || 5;
  }

  console.log(`🚀 开始爬取渤海银行采购公告 (模式: ${mode}, ${mode === 'date' ? `日期: ${targetDate}` : `数量: ${count}`})`);

  // 初始化 JSON writer
  const writer = new JsonWriter(OUTPUT_JSON, {
    source: '渤海银行',
    scrapeTime: formatScrapeTime()
  });

  // 获取所有列表项
  let allItems = [];
  let page = 1;
  const maxPages = mode === 'date' ? 14 : Math.ceil(count / 10);  // 最多 14 页

  console.log(`📄 开始获取列表页...`);

  while (page <= maxPages) {
    const pageUrl = page === 1 
      ? `${BASE_URL}/cms/channel/ywgg1qb/index.htm`
      : `${BASE_URL}/cms/channel/ywgg1qb/index_${page}.htm`;
    
    console.log(`  第 ${page} 页: ${pageUrl}`);
    
    const html = await requestWithBackoff(
      () => httpsGet(pageUrl),
      `列表页 ${page}`
    );
    
    const items = parseListPage(html);
    
    if (items.length === 0) {
      console.log(`    ⚠ 第 ${page} 页没有数据，停止翻页`);
      break;
    }
    
    allItems = allItems.concat(items);
    console.log(`    ✓ 获取 ${items.length} 条 (总计: ${allItems.length})`);
    
    // 如果是日期模式，检查是否已经找到目标日期
    if (mode === 'date' && items.some(item => item.date === targetDate)) {
      console.log(`    ✓ 已找到目标日期 ${targetDate} 的数据`);
      break;
    }
    
    // 如果获取的数据已经足够
    if (mode === 'latest' && allItems.length >= count) {
      break;
    }
    
    page++;
    
    // 请求间隔
    await sleep(2000 + Math.random() * 3000);
  }

  // 过滤日期
  let itemsToProcess = allItems;
  if (mode === 'date') {
    itemsToProcess = allItems.filter(item => item.date === targetDate);
    console.log(`\n🔍 日期过滤: 找到 ${itemsToProcess.length} 条 ${targetDate} 的数据`);
  } else if (mode === 'latest') {
    itemsToProcess = allItems.slice(0, count);
  }

  if (itemsToProcess.length === 0) {
    console.log('❌ 没有找到符合条件的数据');
    new JsonWriter(OUTPUT_JSON, { source: '渤海银行', scrapeTime: formatScrapeTime() });
    return;
  }

  console.log(`\n📝 开始获取 ${itemsToProcess.length} 条详情...`);

  // 获取详情
  for (let i = 0; i < itemsToProcess.length; i++) {
    const item = itemsToProcess[i];
    console.log(`\n[${i + 1}/${itemsToProcess.length}] ${item.title}`);
    console.log(`  日期: ${item.date}`);
    console.log(`  URL: ${item.detailUrl}`);
    
    try {
      const detailHtml = await requestWithBackoff(
        () => httpsGet(item.detailUrl),
        `详情页 ${item.title}`
      );
      
      const { content } = parseDetailPage(detailHtml);
      
      // 验证 content 质量
      if (content.length < 200) {
        console.warn(`  ⚠ 内容过短 (${content.length} chars)`);
      }
      
      if (content.trim() === item.title.trim()) {
        console.warn(`  ⚠ 内容等于标题，提取可能失败`);
      }
      
      // 写入数据
      const rowData = {
        title: item.title,
        publishTime: item.date,
        url: item.detailUrl,
        content,
      };

      writer.addRow(rowData);
      console.log(`  ✓ 已保存 (内容长度: ${content.length} chars)`);
      
    } catch (e) {
      console.error(`  ✗ 获取失败: ${e.message}`);
    }
    
    // 请求间隔
    if (i < itemsToProcess.length - 1) {
      await sleep(2000 + Math.random() * 3000);
    }
  }

  console.log(`\n✅ 完成！共保存 ${itemsToProcess.length} 条数据到 ${OUTPUT_JSON}`);
}

main().catch((e) => {
  console.error('❌ 失败:', e.message);
  process.exit(1);
});
