/**
 * 广发银行供应商服务平台 (cgbchina) 采购公告爬虫
 *
 * Usage:
 *   node scrape_cgbchina.js --latest 5    # 爬取最新 N 条
 *   node scrape_cgbchina.js --yesterday   # 爬取昨天数据
 *   node scrape_cgbchina.js --date YYYY-MM-DD  # 爬取指定日期
 *   node scrape_cgbchina.js --info        # 输出爬虫信息
 */

const https = require('https');
const fs = require('fs');
const path = require('path');
const { stripHtml } = require('./utility/stripHtml');
const { JsonWriter } = require('./utility/JsonWriter');

const OUTPUT_JSON = path.join(__dirname, '..', 'raw_data', 'cgbchina_data.json');

// ===================== HTTP 请求 =====================
function httpRequest(url, options = {}) {
  return new Promise((resolve, reject) => {
    const urlObj = new URL(url);
    const reqOptions = {
      hostname: urlObj.hostname,
      port: urlObj.port || 443,
      path: urlObj.pathname + urlObj.search,
      method: options.method || 'GET',
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'application/json, text/html, */*',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        ...options.headers
      },
      timeout: 30000
    };

    const req = https.request(reqOptions, (res) => {
      let data = '';
      res.on('data', (chunk) => { data += chunk; });
      res.on('end', () => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(data);
        } else {
          reject(new Error(`HTTP ${res.statusCode}: ${data.substring(0, 200)}`));
        }
      });
    });

    req.on('error', (e) => reject(e));
    req.on('timeout', () => {
      req.destroy();
      reject(new Error('Request timeout'));
    });

    if (options.body) {
      req.write(options.body);
    }
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
        console.log(`    ✗ ${label}: 失败`);
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

// ===================== 列表解析 =====================
async function fetchList(page = 1, rows = 12) {
  const url = `https://gfcg.cgbchina.com.cn/gf/Members?act=findGgList&querytype=9&findtype=0&page=${page}&rows=${rows}`;
  
  const html = await requestWithBackoff(() => httpRequest(url), `列表第${page}页`);
  if (!html) return null;
  
  try {
    const json = JSON.parse(html);
    return json.data_list || [];
  } catch (e) {
    console.error('    ✗ 解析列表失败:', e.message);
    return null;
  }
}

// ===================== 详情解析 =====================
async function fetchDetail(code) {
  const url = `https://gfcg.cgbchina.com.cn/gf/Members?act=findPurchaseReport&code=${code}`;
  
  const html = await requestWithBackoff(() => httpRequest(url), `详情 ${code}`);
  if (!html) return null;
  
  try {
    const json = JSON.parse(html);
    
    if (json.type === 1) {
      console.warn(`    ⚠ API返回错误: ${json.mes}`);
      return null;
    }
    
    const content = json.REPORT_CONTENT ? stripHtml(json.REPORT_CONTENT) : '';
    
    if (content.length < 200) {
      console.warn(`    ⚠ 提取的内容过短 (${content.length} 字符)，可能提取失败`);
    }
    
    return { content };
  } catch (e) {
    console.error('    ✗ 解析详情失败:', e.message);
    return null;
  }
}

// ===================== 主流程 =====================
async function main() {
  const args = process.argv.slice(2);

  if (args.includes('--info')) {
    console.log(JSON.stringify({
      name: 'cgbchina',
      description: '广发银行供应商服务平台 - 采购公告',
      modes: ['latest', 'yesterday', 'date'],
      outputFile: 'raw_data/cgbchina_data.json',
      sourceUrl: 'https://gfcg.cgbchina.com.cn/html/gf/purchasemore.html?type=0'
    }, null, 2));
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

  console.log(`\n🚀 开始爬取广发银行采购公告 (${mode})`);
  console.log(`   ${mode === 'date' ? `目标日期: ${targetDate}` : `最新 ${count} 条`}\n`);

  // 初始化 JsonWriter
  const writer = new JsonWriter(OUTPUT_JSON, {
    source: 'cgbchina',
    scrapeTime: new Date().toISOString()
  });

  // 获取列表（API 一次性返回所有数据）
  console.log('📋 获取列表...');
  const list = await fetchList(1, 100);
  
  if (!list || list.length === 0) {
    console.log('   没有找到数据');
    return;
  }

  console.log(`   找到 ${list.length} 条记录`);

  // 过滤数据
  let allItems = [];
  
  if (mode === 'date' && targetDate) {
    // 日期过滤
    allItems = list.filter(item => item.TIME === targetDate);
    console.log(`   其中 ${targetDate} 的有 ${allItems.length} 条`);
  } else {
    // latest 模式 - 取前 N 条
    allItems = list.slice(0, count);
  }

  if (allItems.length === 0) {
    console.log('\n❌ 没有找到符合条件的记录');
    return;
  }

  console.log(`\n📊 共找到 ${allItems.length} 条记录，开始获取详情...\n`);

  // 逐条获取详情
  let successCount = 0;
  let failCount = 0;

  for (let i = 0; i < allItems.length; i++) {
    const item = allItems[i];
    console.log(`[${i + 1}/${allItems.length}] ${item.TITLE}`);
    console.log(`   日期: ${item.TIME}`);

    // 获取详情
    const detail = await fetchDetail(item.ID);
    
    if (!detail || !detail.content || detail.content.length < 50) {
      console.log('   ❌ 详情获取失败或内容过短');
      failCount++;
      continue;
    }

    // 验证 content 不等于 title
    if (detail.content.trim() === item.TITLE.trim()) {
      console.log('   ❌ Content 等于 Title，提取失败');
      failCount++;
      continue;
    }

    // 构建数据行
    const row = {
      id: item.ID,
      title: item.TITLE,
      date: item.TIME,
      content: detail.content,
      url: `https://gfcg.cgbchina.com.cn/html/gf/purchasereport.html?code=${item.ID}`,
      scraped_at: new Date().toISOString()
    };

    // 增量写入
    await writer.addRow(row);
    successCount++;
    
    console.log(`   ✅ 成功 (${detail.content.length} 字符)`);

    // 请求间隔
    if (i < allItems.length - 1) {
      await sleep(2000 + Math.random() * 1000); // 2-3 秒随机间隔
    }
  }

  // 完成
  
  console.log(`\n✅ 爬取完成`);
  console.log(`   成功: ${successCount} 条`);
  console.log(`   失败: ${failCount} 条`);
  console.log(`   输出: ${OUTPUT_JSON}\n`);
}

main().catch((e) => {
  console.error('\n❌ 爬取失败:', e.message);
  console.error(e.stack);
  process.exit(1);
});
