/**
 * 浙商银行数智采购平台 (czbank) 集中采购公示公告
 *
 * API:
 *   列表: POST /portal/category {pageNo, pageSize, categoryCode, _t}
 *   详情: GET /portal/detail?articleId=<encoded>
 *
 * Usage:
 *   node scrape_czbank.js --info             # 输出元数据 JSON
 *   node scrape_czbank.js --latest 5         # 爬取最新 N 条
 *   node scrape_czbank.js --yesterday        # 爬取昨天数据
 *   node scrape_czbank.js --date YYYY-MM-DD  # 爬取指定日期
 */

const https = require('https');
const fs = require('fs');
const path = require('path');
const { stripHtml } = require('./utility/stripHtml');
const { JsonWriter } = require('./utility/JsonWriter');

// ★ 路径只用一层 ..，因为爬虫在 scrapers/ 下运行
const OUTPUT_JSON = path.join(__dirname, '..', 'raw_data', 'czbank_data.json');

const BASE_URL = 'ccgp.szcgpt.czbank.com';
const CATEGORY_CODE = '134-848230';

// ===================== pathName → noticeType 映射 =====================
const NOTICE_TYPE_MAP = {
  '资格预审公告': '采购公告',
  '公开招标公告': '采购公告',
  '竞争性谈判公告': '采购公告',
  '竞争性磋商公告': '采购公告',
  '竞争性谈判（磋商）公告': '采购公告',
  '询价公告': '采购公告',
  '招标公告': '采购公告',
  '更正公告': '其他',
  '更正（澄清）公告': '其他',
  '中标（成交）结果公告': '结果公告',
  '采购结果': '结果公告',
  '成交结果': '结果公告',
  '中标结果': '结果公告',
  '终止公告': '其他',
  '废标公告': '其他',
  '采购结果更正公告': '其他',
};

function mapNoticeType(pathName) {
  if (!pathName) return '其他';
  // 精确匹配
  if (NOTICE_TYPE_MAP[pathName]) return NOTICE_TYPE_MAP[pathName];
  // 模糊匹配
  for (const [key, val] of Object.entries(NOTICE_TYPE_MAP)) {
    if (pathName.includes(key) || key.includes(pathName)) return val;
  }
  // 根据关键词推断
  if (pathName.includes('招标') || pathName.includes('磋商') || pathName.includes('谈判') || pathName.includes('询价')) return '采购公告';
  if (pathName.includes('结果') || pathName.includes('成交') || pathName.includes('中标')) return '结果公告';
  return '其他';
}

// ===================== HTTP 请求 =====================
function httpsRequest(options, body) {
  return new Promise((resolve, reject) => {
    const req = https.request({
      hostname: BASE_URL,
      port: 443,
      method: options.method || 'GET',
      path: options.path,
      headers: {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Origin': `https://${BASE_URL}`,
        'Referer': `https://${BASE_URL}/luban/category?parentId=700835&childrenCode=${CATEGORY_CODE}`,
        ...(options.headers || {}),
      },
      timeout: 30000,
    }, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        if (res.statusCode >= 400) {
          reject(new Error(`HTTP ${res.statusCode}: ${data.substring(0, 200)}`));
        } else {
          try {
            resolve(JSON.parse(data));
          } catch (e) {
            reject(new Error(`JSON parse error: ${data.substring(0, 200)}`));
          }
        }
      });
    });
    req.on('error', reject);
    req.on('timeout', () => { req.destroy(); reject(new Error('Request timeout')); });
    if (body) req.write(body);
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
      if (data && data.success === false) {
        const msg = data.message || data.error || 'Unknown error';
        if (msg.includes('频繁')) {
          if (attempt < MAX_ATTEMPTS) {
            console.log(`    ⚠ 限频 → 等待 ${delay/1000}s`);
            await sleep(delay);
            delay = Math.min(delay * 2, MAX_DELAY);
            continue;
          }
        }
        throw new Error(`API error: ${msg}`);
      }
      return data;
    } catch (e) {
      if (attempt < MAX_ATTEMPTS) {
        console.log(`    ⚠ ${label}: ${e.message}，等待 ${delay/1000}s...`);
        await sleep(delay);
        delay = Math.min(delay * 2, MAX_DELAY);
      } else {
        console.log(`    ✗ ${label}: 最终失败 - ${e.message}`);
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
function formatScrapeTime() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}`;
}
function msToDateStr(ms) {
  const d = new Date(ms);
  return formatDate(d);
}

// ===================== API 调用 =====================
async function fetchList(pageNo, pageSize) {
  const body = JSON.stringify({
    pageNo,
    pageSize,
    categoryCode: CATEGORY_CODE,
    _t: Date.now(),
  });
  const resp = await httpsRequest({
    method: 'POST',
    path: '/portal/category',
    headers: { 'Content-Type': 'application/json' },
  }, body);
  return resp;
}

async function fetchDetail(articleId) {
  // ★ 必须 URL 编码 articleId（含 + / = 特殊字符）
  const encodedId = encodeURIComponent(articleId);
  const resp = await httpsRequest({
    method: 'GET',
    path: `/portal/detail?articleId=${encodedId}`,
  });
  return resp;
}

// ===================== 主流程 =====================
async function main() {
  const args = process.argv.slice(2);

  if (args.includes('--info')) {
    console.log(JSON.stringify({
      name: 'czbank',
      description: '浙商银行数智采购平台 - 集中采购公示公告',
      modes: ['latest', 'yesterday', 'date'],
      outputFile: 'raw_data/czbank_data.json',
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

  console.log(`🚀 开始爬取浙商银行数智采购平台 (${mode}${targetDate ? `: ${targetDate}` : `: latest ${count}`})...`);

  const writer = new JsonWriter(OUTPUT_JSON, {
    source: '浙商银行数智采购平台',
    scrapeTime: formatScrapeTime(),
  });

  if (mode === 'date') {
    // ====== 按日期爬取 ======
    console.log(`  目标日期: ${targetDate}`);
    let pageNo = 1;
    const pageSize = 20;
    let found = 0;
    const MAX_PAGES = 15;
    let consecutiveNonMatchPages = 0;

    while (pageNo <= MAX_PAGES) {
      console.log(`\n📄 获取列表第 ${pageNo} 页...`);
      const resp = await requestWithBackoff(
        () => fetchList(pageNo, pageSize),
        `列表第${pageNo}页`
      );
      if (!resp || !resp.success || !resp.result) {
        console.log(`  ✗ 获取列表失败`);
        break;
      }

      const items = resp.result.data.data;
      const total = resp.result.data.total;

      if (items.length === 0) {
        console.log(`  第 ${pageNo} 页: 无数据，停止`);
        break;
      }

      // 客户端日期过滤
      const matchedItems = items.filter(item => {
        const itemDate = msToDateStr(item.publishDate);
        return itemDate === targetDate;
      });

      console.log(`  第 ${pageNo} 页: ${items.length} 条，其中 ${matchedItems.length} 条是 ${targetDate} 的`);

      // 处理匹配项
      for (const item of matchedItems) {
        const title = (item.title || '').replace(/^[\u200b\u200c\u200d\u200e\u200f\uFEFF]+/, '').trim();
        console.log(`[${found + 1}] ${title.substring(0, 50)}...`);

        try {
          const detailResp = await requestWithBackoff(
            () => fetchDetail(item.articleId),
            `详情: ${title.substring(0, 20)}`
          );

          let content = '';
          if (detailResp && detailResp.success && detailResp.result && detailResp.result.data) {
            const detailData = detailResp.result.data;
            content = stripHtml(detailData.content || '') || '';
          }

          if (!content || content.length < 50) {
            content = title;
            console.log(`    ⚠ 内容过短或为空，使用标题`);
          }

          const noticeType = mapNoticeType(item.pathName);

          writer.addRow({
            title,
            content,
            publishTime: msToDateStr(item.publishDate),
            url: `https://${BASE_URL}/luban/detail?parentId=700835&articleId=${encodeURIComponent(item.articleId)}`,
            noticeType,
          });
          found++;
        } catch (e) {
          console.log(`    ✗ 详情获取失败: ${e.message}`);
          // 记录基本信息
          writer.addRow({
            title,
            content: title,
            publishTime: msToDateStr(item.publishDate),
            url: `https://${BASE_URL}/luban/detail?parentId=700835&articleId=${encodeURIComponent(item.articleId)}`,
            noticeType: mapNoticeType(item.pathName),
          });
          found++;
        }

        // 请求间隔
        await sleep(2000 + Math.random() * 2000);
      }

      // 提前终止逻辑：检查当前页日期范围
      const lastItemDate = msToDateStr(items[items.length - 1].publishDate);
      if (lastItemDate < targetDate) {
        console.log(`  ✓ 当前页最早数据 ${lastItemDate} 早于目标日期 ${targetDate}，停止翻页`);
        break;
      }

      // 连续多页无匹配
      if (matchedItems.length === 0) {
        consecutiveNonMatchPages++;
        if (consecutiveNonMatchPages >= 3) {
          console.log(`  连续 ${consecutiveNonMatchPages} 页无匹配，停止翻页`);
          break;
        }
      } else {
        consecutiveNonMatchPages = 0;
      }

      pageNo++;
      await sleep(3000 + Math.random() * 2000);
    }

    console.log(`\n✅ 日期 ${targetDate} 爬取完成，共 ${writer.count} 条记录`);

  } else {
    // ====== latest 模式 ======
    console.log(`  获取最新 ${count} 条...`);

    const resp = await requestWithBackoff(
      () => fetchList(1, Math.max(count, 15)),
      '列表'
    );

    if (!resp || !resp.success || !resp.result) {
      console.log('✗ 获取列表失败');
      process.exit(1);
    }

    const items = resp.result.data.data.slice(0, count);
    console.log(`  获取到 ${items.length} 条记录`);

    for (let i = 0; i < items.length; i++) {
      const item = items[i];
      const title = (item.title || '').replace(/^[\u200b\u200c\u200d\u200e\u200f\uFEFF]+/, '').trim();
      console.log(`[${i + 1}/${items.length}] ${title.substring(0, 50)}...`);

      try {
        const detailResp = await requestWithBackoff(
          () => fetchDetail(item.articleId),
          `详情: ${title.substring(0, 20)}`
        );

        let content = '';
        if (detailResp && detailResp.success && detailResp.result && detailResp.result.data) {
          const detailData = detailResp.result.data;
          content = stripHtml(detailData.content || '') || '';
        }

        if (!content || content.length < 50) {
          content = title;
          console.log(`    ⚠ 内容过短或为空，使用标题`);
        }

        const noticeType = mapNoticeType(item.pathName);

        writer.addRow({
          title,
          content,
          publishTime: msToDateStr(item.publishDate),
          url: `https://${BASE_URL}/luban/detail?parentId=700835&articleId=${encodeURIComponent(item.articleId)}`,
          noticeType,
        });
      } catch (e) {
        console.log(`    ✗ 详情获取失败: ${e.message}`);
        writer.addRow({
          title,
          content: title,
          publishTime: msToDateStr(item.publishDate),
          url: `https://${BASE_URL}/luban/detail?parentId=700835&articleId=${encodeURIComponent(item.articleId)}`,
          noticeType: mapNoticeType(item.pathName),
        });
      }

      // 请求间隔
      if (i < items.length - 1) {
        await sleep(2000 + Math.random() * 2000);
      }
    }

    console.log(`\n✅ 爬取完成，共 ${writer.count} 条记录`);
  }
}

main().catch((e) => { console.error('失败:', e.message); process.exit(1); });
