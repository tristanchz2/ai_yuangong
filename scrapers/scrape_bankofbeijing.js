/**
 * 北京银行集中采购管理系统 (bankofbeijing) 采购公告爬虫
 *
 * 数据来源: POST /cms/api/dynamicData/queryContentPage
 * 站点: https://login-cpm-xt.bankofbeijing.com.cn
 *
 * Usage:
 *   node scrape_bankofbeijing.js --info             # 输出元数据 JSON
 *   node scrape_bankofbeijing.js --latest 5         # 爬取最新 N 条
 *   node scrape_bankofbeijing.js --yesterday        # 爬取昨天数据
 *   node scrape_bankofbeijing.js --date YYYY-MM-DD  # 爬取指定日期
 */

const https = require('https');
const constants = require('constants');
const path = require('path');
const { stripHtml } = require('./utility/stripHtml');
const { JsonWriter } = require('./utility/JsonWriter');

// ★ 路径只用一层 ..，因为爬虫在 scrapers/ 下运行
const OUTPUT_JSON = path.join(__dirname, '..', 'raw_data', 'bankofbeijing_data.json');

const BASE_URL = 'https://login-cpm-xt.bankofbeijing.com.cn';
const API_PATH = '/cms/api/dynamicData/queryContentPage';
const SITE_ID = '725';
const CATEGORY_ID = '209'; // 采购公告

// ===================== HTTP 请求 =====================
function makeRequest(postData, label) {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify(postData);
    const options = {
      hostname: 'login-cpm-xt.bankofbeijing.com.cn',
      path: API_PATH,
      method: 'POST',
      headers: {
        'Content-Type': 'application/json; charset=utf-8',
        'Content-Length': Buffer.byteLength(body),
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Origin': BASE_URL,
        'Referer': `${BASE_URL}/cms/default/webfile/1ywgg1/index.html`,
      },
      timeout: 30000,
      rejectUnauthorized: false,
      secureProtocol: 'TLS_method',
      secureOptions: constants.SSL_OP_LEGACY_SERVER_CONNECT,
    };

    const req = https.request(options, (res) => {
      let data = '';
      res.on('data', (chunk) => (data += chunk));
      res.on('end', () => {
        if (res.statusCode !== 200) {
          reject(new Error(`HTTP ${res.statusCode}: ${data.substring(0, 200)}`));
          return;
        }
        try {
          resolve(JSON.parse(data));
        } catch (e) {
          reject(new Error(`JSON 解析失败: ${data.substring(0, 200)}`));
        }
      });
    });
    req.on('error', reject);
    req.on('timeout', () => { req.destroy(); reject(new Error('请求超时')); });
    req.write(body);
    req.end();
  });
}

// ===================== 限频退避 =====================
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function requestWithBackoff(postData, label) {
  let delay = 5000;
  const MAX_ATTEMPTS = 6;
  const MAX_DELAY = 120000;
  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
    try {
      const data = await makeRequest(postData, label);
      if (data && data.msg && data.msg.includes('频繁')) {
        if (attempt < MAX_ATTEMPTS) {
          console.log(`    ⚠ 限频 → 等待 ${delay / 1000}s`);
          await sleep(delay);
          delay = Math.min(delay * 2, MAX_DELAY);
          continue;
        }
      }
      return data;
    } catch (e) {
      if (attempt < MAX_ATTEMPTS) {
        console.log(`    ⚠ ${e.message}，等待 ${delay / 1000}s...`);
        await sleep(delay);
        delay = Math.min(delay * 2, MAX_DELAY);
      } else {
        console.log(`    ✗ ${label}: 失败`);
        return { msg: 'failed', res: { total: 0, rows: [] } };
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

/**
 * 解析 API 返回的 publishDate (UTC ISO 格式如 "2026-07-24T05:50:02.000+0000")
 * 转为本地日期 YYYY-MM-DD
 */
function parsePublishDate(utcDateStr) {
  if (!utcDateStr) return '';
  try {
    const d = new Date(utcDateStr);
    return formatDate(d);
  } catch (e) {
    return '';
  }
}

// ===================== 主流程 =====================
async function main() {
  const args = process.argv.slice(2);

  // --info
  if (args.includes('--info')) {
    console.log(JSON.stringify({
      name: 'bankofbeijing',
      description: '北京银行集中采购管理系统 - 采购公告',
      modes: ['latest', 'yesterday', 'date'],
      outputFile: 'raw_data/bankofbeijing_data.json',
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

  console.log(`\n🕷  北京银行集中采购管理系统爬虫`);
  console.log(`   模式: ${mode === 'latest' ? `最新 ${count} 条` : `日期 ${targetDate}`}`);
  console.log(`   API: POST ${API_PATH}`);
  console.log(`   siteId=${SITE_ID}, categoryId=${CATEGORY_ID}`);

  const scrapeTime = formatScrapeTime();
  const writer = new JsonWriter(OUTPUT_JSON, { source: 'bankofbeijing', scrapeTime });

  // ★ 确定要爬多少数据
  let pageSize = 20;
  let maxPages = 1;
  if (mode === 'date') {
    // 日期模式可能需要翻多页（日期过滤在客户端做）
    pageSize = 20;
    maxPages = 10; // 最多翻10页找当天数据
  } else {
    // latest 模式：根据 count 计算页数
    pageSize = Math.min(count, 50);
    maxPages = Math.ceil(count / pageSize);
  }

  let totalFetched = 0;
  let stopFetching = false;

  for (let page = 1; page <= maxPages && !stopFetching; page++) {
    console.log(`\n📄 第 ${page}/${maxPages} 页 (pageSize=${pageSize})...`);

    const postData = {
      pageNo: page,
      pageSize: pageSize,
      dto: {
        siteId: SITE_ID,
        categoryId: CATEGORY_ID,
        bidType: '',
        province: '',
        city: '',
        county: '',
        publishDays: '',
        purchaseMode: '',
        publishOrganization: '',
      },
    };

    const result = await requestWithBackoff(postData, `page ${page}`);
    if (!result || !result.res || !result.res.rows || result.res.rows.length === 0) {
      console.log('   ⚠ 无数据返回，停止');
      break;
    }

    const rows = result.res.rows;
    console.log(`   API 返回 ${rows.length} 条，总计 ${result.res.total} 条`);

    for (let i = 0; i < rows.length; i++) {
      const item = rows[i];

      // 解析日期
      const publishDate = parsePublishDate(item.publishDate);

      // ★ 客户端日期过滤（强制！API 可能静默忽略日期参数）
      if (mode === 'date' && publishDate !== targetDate) {
        // 打印诊断
        if (i === 0 || i === rows.length - 1) {
          console.log(`   [${i + 1}/${rows.length}] ${publishDate} ≠ ${targetDate} → 跳过`);
        }

        // 提前终止：如果数据按时间倒序，当前记录的日期比目标日期早，后面的只会更早
        if (publishDate && publishDate < targetDate) {
          console.log(`   ✓ 当前数据 ${publishDate} 早于目标 ${targetDate}，停止翻页`);
          stopFetching = true;
          break;
        }
        continue;
      }

      // ★ 提取内容（从 API 返回的 text 字段，已是完整 HTML）
      let content = '';
      if (item.text) {
        content = stripHtml(item.text);
      }

      // 验证 content 质量
      if (content.length < 50) {
        console.warn(`   ⚠ [${i + 1}] content 过短 (${content.length} 字符)，标题: ${item.title}`);
      }

      // 构造 URL（API 返回的 url 是相对路径如 /1ywgg1/20260724/xxx.html）
      const detailPath = item.url || '';
      const fullUrl = detailPath.startsWith('http')
        ? detailPath
        : `${BASE_URL}/cms/default/webfile${detailPath}`;

      // noticeType: 使用 categoryName
      const noticeType = item.categoryName || '采购公告';

      const row = {
        title: item.title || '',
        content: content,
        publishTime: publishDate,
        url: fullUrl,
        noticeType: noticeType,
      };

      writer.addRow(row);
      totalFetched++;
      const titlePreview = (item.title || '').substring(0, 40);
      console.log(`   [${totalFetched}] ${titlePreview}... ✓ (${content.length} 字)`);

      // latest 模式：达到目标数量就停
      if (mode === 'latest' && totalFetched >= count) {
        stopFetching = true;
        break;
      }

      // 请求间隔（避免被限频）
      if (!stopFetching) {
        const delay = 1500 + Math.floor(Math.random() * 2000);
        await sleep(delay);
      }
    }

    // 日期模式：打印诊断信息
    if (mode === 'date') {
      const matchedInPage = rows.filter(r => parsePublishDate(r.publishDate) === targetDate).length;
      console.log(`   📊 本页匹配: ${matchedInPage}/${rows.length} 条是 ${targetDate} 的`);

      // 如果 API 日期过滤不生效的诊断
      if (matchedInPage === 0 && rows.length > 0) {
        const firstDate = parsePublishDate(rows[0].publishDate);
        const lastDate = parsePublishDate(rows[rows.length - 1].publishDate);
        console.log(`   🔍 API日期过滤诊断: 本页日期范围 ${firstDate} ~ ${lastDate}`);
      }
    }

    // 页间延迟
    if (page < maxPages && !stopFetching) {
      await sleep(2000 + Math.floor(Math.random() * 2000));
    }
  }

  console.log(`\n✅ 完成！共 ${totalFetched} 条记录 → ${OUTPUT_JSON}`);
}

main().catch((e) => {
  console.error('失败:', e.message);
  process.exit(1);
});
