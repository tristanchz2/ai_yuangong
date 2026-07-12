/**
 * 兴业银行集中采购管理平台 (cib) 供应商征集公告
 *
 * Usage:
 *   node scrape_cib.js --info             # 输出元数据 JSON
 *   node scrape_cib.js --latest 5         # 爬取最新 N 条
 *   node scrape_cib.js --yesterday        # 爬取昨天数据
 *   node scrape_cib.js --date YYYY-MM-DD  # 爬取指定日期
 */

const https = require('https');
const fs = require('fs');
const path = require('path');
const { stripHtml } = require('./utility/stripHtml');
const { JsonWriter } = require('./utility/JsonWriter');

// ★ 路径只用一层 ..，因为爬虫在 scrapers/ 下运行
const OUTPUT_JSON = path.join(__dirname, '..', 'raw_data', 'cib_data.json');

const API_URL = 'https://cg.cib.com.cn/cms/api/dynamicData/queryContentPage';
const DETAIL_BASE_URL = 'https://cg.cib.com.cn/cms/default/webfile';

// ===================== HTTP 请求 =====================
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function makeRequest(url, options = {}) {
  return new Promise((resolve, reject) => {
    const urlObj = new URL(url);
    const reqOptions = {
      hostname: urlObj.hostname,
      port: urlObj.port,
      path: urlObj.pathname + urlObj.search,
      method: options.method || 'GET',
      headers: {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Referer': 'https://cg.cib.com.cn/cms/default/webfile/gyszj/index.html',
        ...options.headers,
      },
      timeout: 20000,
    };

    const req = https.request(reqOptions, (res) => {
      let data = '';
      res.on('data', (chunk) => (data += chunk));
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
async function requestWithBackoff(requestFn, label) {
  let delay = 3000;
  const MAX_ATTEMPTS = 5;
  const MAX_DELAY = 60000;

  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
    try {
      return await requestFn();
    } catch (e) {
      if (attempt < MAX_ATTEMPTS) {
        console.log(`    ⚠ ${label} 失败 (尝试 ${attempt}/${MAX_ATTEMPTS}): ${e.message}，等待 ${delay/1000}s...`);
        await sleep(delay);
        delay = Math.min(delay * 2, MAX_DELAY);
      } else {
        console.log(`    ✗ ${label}: 最终失败 - ${e.message}`);
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

// ★ 必须用本地时间，禁止 toISOString()（那是 UTC）
function formatScrapeTime() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}`;
}

// ===================== API 请求 =====================
async function fetchList(pageNo, pageSize, startDate = '', endDate = '') {
  const body = JSON.stringify({
    pageNo,
    pageSize,
    dto: {
      siteId: '725',
      categoryId: '201',
      bidType: '',
      province: '',
      city: '',
      county: '',
      publishDays: '',
      purchaseMode: '',
      publishOrganization: '',
      agentCompanyId: '',
      secondCompanyId: '',
      agentCompanyName: '',
      secondCompanyName: '',
      mainCode: '',
      title: '',
      cgTitleParams: '',
      zjTitleParams: '',
      beginDate: startDate,
      endDate: endDate,
    },
  });

  const responseText = await requestWithBackoff(
    () => makeRequest(API_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json; charset=utf-8',
      },
      body,
    }),
    `列表页 ${pageNo}`
  );

  const data = JSON.parse(responseText);
  return {
    rows: data.res.rows || [],
    total: data.res.total || 0,
  };
}

// ===================== 详情页解析 =====================
async function fetchDetail(url) {
  const html = await requestWithBackoff(
    () => makeRequest(url),
    '详情页'
  );
  return parseDetailPage(html);
}

function parseDetailPage(html) {
  // 多策略提取链
  let content = '';

  // 策略 1: 提取所有 <p> 标签（从参考页面学到的选择器）
  const paragraphs = [];
  const pMatches = html.match(/<p[^>]*>([\s\S]*?)<\/p>/gi) || [];

  for (const p of pMatches) {
    let text = stripHtml(p).trim();
    // 过滤掉空段落和过短的段落
    if (text.length > 10) {
      // 清理 &nbsp; 和多余空格
      text = text.replace(/&nbsp;/g, ' ').replace(/\s+/g, ' ').trim();
      paragraphs.push(text);
    }
  }

  if (paragraphs.length > 0) {
    content = paragraphs.join('\n\n');
  }

  // 验证内容长度
  if (content.length < 200) {
    console.warn(`    ⚠ 提取的内容过短 (${content.length} 字符)`);
  }

  return content;
}

// ===================== 主流程 =====================
async function main() {
  const args = process.argv.slice(2);

  // ★ --info 必须输出合法 JSON
  if (args.includes('--info')) {
    console.log(JSON.stringify({
      name: 'cib',
      description: '兴业银行集中采购管理平台 - 供应商征集公告',
      modes: ['latest', 'yesterday', 'date'],
      outputFile: 'raw_data/cib_data.json',
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

  console.log(`🚀 开始爬取 兴业银行集中采购管理平台 (${mode}模式)...`);

  const writer = new JsonWriter(OUTPUT_JSON, {
    source: '兴业银行集中采购管理平台',
    scrapeTime: formatScrapeTime(),
  });

  try {
    let allItems = [];
    let pageNo = 1;
    const pageSize = 20;

    if (mode === 'latest') {
      // 获取最新 N 条
      console.log(`📋 获取最新 ${count} 条...`);
      const result = await fetchList(pageNo, Math.min(count, pageSize));
      allItems = result.rows;
    } else if (mode === 'date') {
      // 获取指定日期的所有数据
      console.log(`📋 获取 ${targetDate} 的数据...`);
      
      // API 的日期过滤不生效，需要获取所有数据后在客户端过滤
      let totalFetched = 0;
      const maxPages = 10; // 最多翻 10 页，防止无限循环
      let foundEarlierDate = false; // 标记是否找到比目标日期更早的数据
      
      while (pageNo <= maxPages && !foundEarlierDate) {
        const result = await fetchList(pageNo, pageSize);
        
        // 检查这页数据的日期范围
        const dates = result.rows.map(item => (item.publishDate || '').substring(0, 10));
        const minDate = dates.length > 0 ? dates[dates.length - 1] : null; // 这页最早的日期
        
        // 过滤出目标日期的数据
        const todayItems = result.rows.filter(item => {
          const itemDate = (item.publishDate || '').substring(0, 10);
          return itemDate === targetDate;
        });
        
        allItems = allItems.concat(todayItems);
        totalFetched += result.rows.length;
        
        console.log(`  第 ${pageNo} 页: ${result.rows.length} 条，其中 ${todayItems.length} 条是 ${targetDate} 的（日期范围: ${dates[0] || 'N/A'} ~ ${minDate || 'N/A'}）`);
        
        // 如果这页最早的日期比目标日期早，说明后面的数据都不匹配，停止翻页
        if (minDate && minDate < targetDate) {
          console.log(`  ✓ 已找到比 ${targetDate} 更早的数据，停止翻页`);
          foundEarlierDate = true;
        }
        
        // 如果这页没有更多数据，或者已经获取完所有数据，就停止
        if (result.rows.length < pageSize || totalFetched >= result.total) {
          break;
        }
        
        pageNo++;
        await sleep(2000 + Math.random() * 1000);
      }
    }

    console.log(`📋 找到 ${allItems.length} 条记录`);

    if (allItems.length === 0) {
      console.log('⚠ 没有找到数据');
      return;
    }

    // 逐条获取详情
    for (let i = 0; i < allItems.length; i++) {
      const item = allItems[i];
      const detailUrl = DETAIL_BASE_URL + item.url;

      console.log(`[${i + 1}/${allItems.length}] ${item.title.substring(0, 40)}...`);

      try {
        const content = await fetchDetail(detailUrl);

        if (!content || content.length < 200) {
          console.log(`    ⚠ 内容过短 (${content?.length || 0} 字符)`);
        }

        // 格式化发布时间
        let publishTime = item.publishDate || '';
        if (publishTime) {
          publishTime = publishTime.substring(0, 10); // 只保留 YYYY-MM-DD
        }

        writer.addRow({
          title: item.title || '',
          content: content || item.title,
          publishTime,
          url: detailUrl,
          noticeType: item.categoryName || '供应商征集',
        });

        // 请求间隔
        if (i < allItems.length - 1) {
          await sleep(1500 + Math.random() * 1000);
        }

        console.log(`    ✓ 内容长度: ${content?.length || 0} 字符`);
      } catch (e) {
        console.log(`    ✗ 详情提取失败: ${e.message}`);
        // 即使详情失败，也记录基本信息
        writer.addRow({
          title: item.title || '',
          content: item.title || '',
          publishTime: (item.publishDate || '').substring(0, 10),
          url: detailUrl,
          noticeType: item.categoryName || '供应商征集',
        });
      }
    }

    console.log(`\n✅ 爬取完成，共 ${writer.count} 条记录`);
  } catch (e) {
    console.error('❌ 爬取失败:', e.message);
    process.exit(1);
  }
}

main().catch((e) => {
  console.error('失败:', e.message);
  process.exit(1);
});
