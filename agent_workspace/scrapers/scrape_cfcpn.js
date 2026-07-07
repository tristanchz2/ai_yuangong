/**
 * 金采网 (CFCPN) 采购公告爬虫
 * 
 * Usage:
 *   node scrape_cfcpn.js                    # 从 cfcpn_data.json 加载列表，抓正文
 *   node scrape_cfcpn.js resume             # 从上次中断处续爬
 *   node scrape_cfcpn.js --list 5           # 先爬5页列表，再抓正文
 *   node scrape_cfcpn.js --list all         # 先爬全部列表，再抓正文
 */

const http = require('http');
const fs = require('fs');
const path = require('path');
const { stripHtml } = require('./utility/stripHtml');
const { JsonWriter } = require('./utility/JsonWriter');

const PAGE_SIZE = 10;
const BASE_URL = 'http://www.cfcpn.com/jcw/sys/index/goUrl?url=modules/sys/login/detail&column=undefined&searchVal=';
const OUTPUT_JSON = path.join(__dirname, '..', '..', 'raw_data', 'cfcpn_data.json');

// ===================== 请求层 =====================

function apiRequest(params) {
  const postData = new URLSearchParams(params).toString();
  return new Promise((resolve, reject) => {
    const req = http.request(
      {
        hostname: 'www.cfcpn.com',
        port: 80,
        path: '/jcw/noticeinfo/noticeInfo/dataNoticeList',
        method: 'POST',
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
          'Content-Length': Buffer.byteLength(postData),
          'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
          'Referer': 'http://www.cfcpn.com/jcw/sys/index/goUrl?url=modules/sys/login/list&column=cggg',
          'Origin': 'http://www.cfcpn.com',
        },
      },
      (res) => {
        let data = '';
        res.on('data', (c) => (data += c));
        res.on('end', () => {
          if (res.statusCode !== 200) {
            reject(new Error(`HTTP ${res.statusCode}: ${data.substring(0, 100)}`));
            return;
          }
          try { resolve(JSON.parse(data)); }
          catch (e) { reject(new Error(`JSON parse: ${data.substring(0, 100)}`)); }
        });
      }
    );
    req.on('error', reject);
    req.setTimeout(15000, () => { req.destroy(); reject(new Error('timeout')); });
    req.write(postData);
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
    let data;
    try {
      data = await requestFn();
    } catch (e) {
      if (attempt < MAX_ATTEMPTS) {
        console.log(`    ⚠ 请求异常: ${e.message}，等待 ${delay / 1000}s...`);
        await sleep(delay);
        delay = Math.min(delay * 2, MAX_DELAY);
        continue;
      }
      return { result: false, message: e.message };
    }

    if (data.result !== false || !data.message) return data;

    if (data.message && data.message.includes('频繁')) {
      if (attempt < MAX_ATTEMPTS) {
        const waitSec = delay / 1000;
        console.log(`    ⚠ 限频 → 等待 ${waitSec}s (${attempt}/${MAX_ATTEMPTS})`);
        await sleep(delay);
        delay = Math.min(delay * 2, MAX_DELAY);
      } else {
        console.log(`    ✗ ${label}: 限频，已重试 ${MAX_ATTEMPTS} 次`);
        return data;
      }
    } else {
      return data;
    }
  }
}

let dateBegin = '';
let dateEnd = '';

function fetchPage(pageNo) {
  // 日期过滤在客户端进行，API的日期过滤有bug
  return apiRequest({
    noticeType: '', pageSize: String(PAGE_SIZE), pageNo: String(pageNo),
    noticeState: '1', isValid: '1', orderBy: 'publish_time desc',
    beginPublishTime: '', endPublishTime: '',
    areaProvince: '', labelAllId: '',
    noticeContent: '', briefContent: '', noticeTitle: '',
    purchaseName: '', categoryLabName: '', purchaseId: '',
  });
}

function isInDateRange(row) {
  if (!dateBegin && !dateEnd) return true;
  const pubTime = (row.publishTime || '').substring(0, 10);
  if (dateBegin && pubTime < dateBegin) return false;
  if (dateEnd && pubTime > dateEnd) return false;
  return true;
}

function fetchDetail(id) {
  return apiRequest({ id, isDetail: '1' });
}

// ===================== 辅助函数 =====================

function rowToOutput(r) {
  return {
    id: r.id, url: BASE_URL + r.id,
    title: r.noticeTitle, publishTime: r.publishTime,
    purchaser: r.userName, method: r.purchaseTypeLable, region: r.area,
    category: r.labelAllId, tags: r.yxCategoryNames, source: r.noticeSource,
    content: stripHtml(r.noticeContent),
  };
}

function loadExistingData() {
  if (fs.existsSync(OUTPUT_JSON)) {
    try {
      const j = JSON.parse(fs.readFileSync(OUTPUT_JSON, 'utf8'));
      if (j.rows?.length) return j;
    } catch {}
  }
  return null;
}

// ===================== 主流程 =====================

async function main() {
  const args = process.argv.slice(2);
  const isResume = args.includes('resume');
  const listIdx = args.indexOf('--list');
  const listPages = listIdx >= 0 ? args[listIdx + 1] : null;
  const limitIdx = args.indexOf('--limit');
  const limit = limitIdx >= 0 ? parseInt(args[limitIdx + 1]) || 0 : 0;
  const beginIdx = args.indexOf('--begin-date');
  const endIdx = args.indexOf('--end-date');
  if (beginIdx >= 0) dateBegin = args[beginIdx + 1] || '';
  if (endIdx >= 0) dateEnd = args[endIdx + 1] || '';

  let allRows = [];
  let total = 0;
  let startDetailIdx = 0;

  // ---- 可选：爬列表 ----
  if (listPages) {
    const maxPages = listPages === 'all' ? 99999 : parseInt(listPages) || 5;
    console.log(`  [列表] ${maxPages === 99999 ? '全部' : maxPages + ' 页'}`);

    for (let page = 1; page <= maxPages; page++) {
      await sleep(2000);
      const d = await requestWithBackoff(() => fetchPage(page), `列表${page}`);
      if (!d?.result) { console.error(`API 错误: ${d?.message || 'unknown'}`); process.exit(1); }
      if (!d.rows?.length) { if (page === 1) { console.log('  无数据'); } break; }
      if (page === 1) { total = d.total; console.log(`    API 共 ${total} 条`); }

      // 客户端日期过滤
      const filtered = d.rows.filter(isInDateRange);
      allRows.push(...filtered);
      console.log(`    第 ${page} 页 ✓ (${filtered.length}/${d.rows.length} 条)`);

      // 如果数据已经早于起始日期，停止翻页
      const oldestOnPage = d.rows[d.rows.length - 1]?.publishTime?.substring(0, 10) || '';
      if (dateBegin && oldestOnPage < dateBegin) {
        console.log(`    已超出日期范围，停止翻页`);
        break;
      }
    }
    if (listPages === 'all' || maxPages > 1) {
      console.log(`    共 ${allRows.length} 条`);
    }

    // --limit N: 截断到指定条数
    if (limit > 0 && allRows.length > limit) {
      allRows = allRows.slice(0, limit);
    }
  }

  // ---- 加载已有数据 / 续爬 ----
  let writer = null;
  if (allRows.length === 0) {
    if (listPages) {
      console.log('✓ 该日期范围内无数据');
      return;
    }
    const existing = loadExistingData();
    if (!existing?.rows?.length) {
      if (isResume) { console.error('⚠ 无进度文件'); process.exit(1); }
      else { console.error('⚠ 无数据文件，用 --list 5 先爬列表'); process.exit(1); }
    }
    if (isResume) {
      writer = new JsonWriter(OUTPUT_JSON, { source: '金采网', scrapeTime: new Date().toISOString() });
      existing.rows.forEach((r) => writer.addRow(r));
      startDetailIdx = existing.rows.findIndex((r) => !r.content);
      if (startDetailIdx < 0) startDetailIdx = existing.rows.length;
      console.log(`♻ 续爬: ${existing.rows.length} 条, 正文从第 ${startDetailIdx + 1} 条\n`);
    } else {
      writer = new JsonWriter(OUTPUT_JSON, { source: '金采网', scrapeTime: new Date().toISOString() });
      existing.rows.forEach((r) => writer.addRow(r));
      console.log(`📂 加载 ${existing.rows.length} 条\n`);
    }
    allRows = existing.rows; // already in output format
  } else {
    // 从列表阶段的数据初始化写入器
    writer = new JsonWriter(OUTPUT_JSON, { source: '金采网', scrapeTime: new Date().toISOString() });
    for (const row of allRows) {
      writer.addRow(rowToOutput(row));
    }
  }

  // ---- 抓正文 ----
  console.log(`  [详情] ${writer.count} 条`);

  for (let i = startDetailIdx; i < writer.count; i++) {
    const existingRow = writer.rows[i];
    if (existingRow.content && existingRow.content !== stripHtml('')) continue;

    await sleep(2000);

    const detail = await requestWithBackoff(() => fetchDetail(allRows[i]?.id || existingRow.id), `正文${i + 1}`);
    let content = '';
    if (detail?.result && detail.rows?.[0]) {
      content = stripHtml(detail.rows[0].noticeContent || '');
    }

    const st = content ? '✓' : '✗';
    console.log(`    [${i + 1}/${writer.count}] ${(existingRow.title || '').substring(0, 40)}... ${st}`);

    // 每条立即写入磁盘
    writer.setRow(i, { ...existingRow, content });
  }

  console.log(`\n✓ cfcpn (${writer.count}/${writer.count})`);
}

main().catch((e) => { console.error('失败:', e.message); process.exit(1); });
