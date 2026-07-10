/**
 * 平安银行慧采系统 (pingan) 采购公告爬虫
 *
 * 通过 REST API 抓取供应商征集公告，支持分页和日期过滤。
 *
 * Usage:
 *   node scrape_pingan.js --info             # 输出元数据 JSON
 *   node scrape_pingan.js --latest 5         # 爬取最新 N 条
 *   node scrape_pingan.js --yesterday        # 爬取昨天数据
 *   node scrape_pingan.js --date YYYY-MM-DD  # 爬取指定日期
 */

const https = require('https');
const path = require('path');
const { stripHtml } = require('./utility/stripHtml');
const { JsonWriter } = require('./utility/JsonWriter');

const OUTPUT_JSON = path.join(__dirname, '..', 'raw_data', 'pingan_data.json');
const API_BASE = 'https://ebank.pingan.com.cn/cr/eps/sppt';
const PORTAL_URL = 'https://ebank.pingan.com.cn/cr/eps-sppt-portal/index.html';
const HEADERS = {
  'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
  'Referer': PORTAL_URL,
  'Accept': 'application/json'
};

// ===================== HTTP =====================

function httpGet(url) {
  return new Promise((resolve, reject) => {
    const req = https.get(url, { headers: HEADERS }, res => {
      let data = '';
      res.on('data', c => data += c);
      res.on('end', () => {
        try { resolve(JSON.parse(data)); }
        catch (e) { reject(new Error(`JSON parse failed: ${e.message}`)); }
      });
    });
    req.on('error', reject);
    req.setTimeout(30000, () => { req.destroy(); reject(new Error('timeout 30s')); });
  });
}

// ===================== 重试 =====================

const sleep = ms => new Promise(r => setTimeout(r, ms));

async function requestWithBackoff(fn, label) {
  let delay = 3000;
  for (let i = 1; i <= 6; i++) {
    try { return await fn(); }
    catch (e) {
      if (i === 6) throw e;
      console.log(`    ⚠ ${label} 失败: ${e.message}, 等待 ${delay/1000}s...`);
      await sleep(delay);
      delay = Math.min(delay * 2, 120000);
    }
  }
}

// ===================== 日期工具 =====================

function formatDate(d) {
  const p = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())}`;
}

function getYesterday() {
  const d = new Date();
  d.setDate(d.getDate() - 1);
  return formatDate(d);
}

function formatScrapeTime() {
  const d = new Date();
  const p = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())}T${p(d.getHours())}`;
}

// ===================== 公告类型映射 =====================

function mapCollectType(t) {
  // "1" = 征集（采购公告）, "2" = 公示（结果公告）
  return { '1': '采购公告', '2': '结果公告' }[t] || '其他';
}

// ===================== 主流程 =====================

async function main() {
  const args = process.argv.slice(2);

  if (args.includes('--info')) {
    console.log(JSON.stringify({
      name: 'pingan',
      description: '平安银行慧采系统采购公告',
      modes: ['latest', 'yesterday', 'date'],
      outputFile: 'raw_data/pingan_data.json'
    }));
    return;
  }

  let mode = 'latest', count = 5, targetDate = null;
  const yi = args.indexOf('--yesterday'), li = args.indexOf('--latest'), di = args.indexOf('--date');
  if (yi >= 0) { mode = 'date'; targetDate = getYesterday(); }
  else if (di >= 0) { mode = 'date'; targetDate = args[di + 1]; }
  else if (li >= 0) { count = parseInt(args[li + 1]) || 5; }

  const writer = new JsonWriter(OUTPUT_JSON, { source: '平安银行慧采系统', scrapeTime: formatScrapeTime() });

  console.log(`🚀 开始爬取 平安银行慧采系统 (${mode}模式)...`);

  // 列表 API
  const size = Math.max(count, 8);
  const listUrl = `${API_BASE}/purCollectNotice/homeCollectPage?current=1&size=${size}`;
  const list = await requestWithBackoff(() => httpGet(listUrl), '列表');

  if (!list || list.code !== 200) throw new Error(`列表失败: code=${list?.code}`);

  let records = list.data.records || [];
  console.log(`📋 列表共 ${records.length} 条`);

  // 日期过滤
  if (mode === 'date' && targetDate) {
    records = records.filter(r => r.publishDate && r.publishDate.startsWith(targetDate));
    console.log(`📅 日期过滤后剩 ${records.length} 条`);
  }

  // 数量限制
  if (mode === 'latest') records = records.slice(0, count);

  if (!records.length) { console.log('⚠ 无记录'); return; }

  // 详情
  for (let i = 0; i < records.length; i++) {
    const rec = records[i];
    console.log(`[${i+1}/${records.length}] ${rec.collectNoticeName.substring(0, 40)}...`);

    try {
      const detailUrl = `${API_BASE}/purCollectNotice/homeDetail?id=${rec.id}`;
      const detail = await requestWithBackoff(() => httpGet(detailUrl), `详情 ${rec.id}`);

      if (!detail || detail.code !== 200) throw new Error(`详情失败: code=${detail?.code}`);

      const content = stripHtml(detail.data.content || '');
      if (content.length < 200) console.log(`    ⚠ 内容过短 (${content.length} 字符)`);

      writer.addRow({
        title: detail.data.collectNoticeName,
        content,
        publishTime: detail.data.publishDate,
        url: `${PORTAL_URL}#/noticeView?id=${rec.id}`,
        noticeType: mapCollectType(rec.collectType)
      });

      console.log(`    ✓ ${content.length} 字符`);
      if (i < records.length - 1) await sleep(2000 + Math.random() * 1000);
    } catch (e) {
      console.log(`    ✗ ${e.message}`);
      writer.addRow({
        title: rec.collectNoticeName,
        content: rec.collectNoticeName,
        publishTime: rec.publishDate,
        url: `${PORTAL_URL}#/noticeView?id=${rec.id}`,
        noticeType: mapCollectType(rec.collectType)
      });
    }
  }

  console.log(`\n✅ 完成，共 ${writer.count} 条`);
}

main().catch(e => { console.error('失败:', e.message); process.exit(1); });
