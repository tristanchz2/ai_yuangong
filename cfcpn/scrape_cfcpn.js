/**
 * 金采网 (CFCPN) 采购公告爬虫 v4 (带免费代理池)
 * 
 * Usage:
 *   node scrape_cfcpn.js                    # 从 cfcpn_data.json 加载列表，抓正文
 *   node scrape_cfcpn.js resume             # 从上次中断处续爬
 *   node scrape_cfcpn.js --list 5           # 先爬5页列表，再抓正文
 *   node scrape_cfcpn.js --list all         # 先爬全部列表，再抓正文
 *   node scrape_cfcpn.js --no-proxy         # 不使用代理（直连）
 */

const http = require('http');
const https = require('https');
const fs = require('fs');
const path = require('path');
const net = require('net');

const API_URL = 'http://www.cfcpn.com/jcw/noticeinfo/noticeInfo/dataNoticeList';
const PAGE_SIZE = 10;
const OUTPUT_JSON = path.join(__dirname, '..', 'row_data', 'cfcpn_data.json');
const PROGRESS_FILE = path.join(__dirname, 'cfcpn_progress.json');

// ===================== 代理池 =====================

const PROXY_SOURCES = [
  'https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies/protocols/http/data.txt',
  'https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt',
  'https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/http/data.txt',
];

let proxyPool = [];
let proxyIndex = 0;
let useProxy = true;

// 下载免费代理列表
function downloadProxies(url) {
  return new Promise((resolve) => {
    const mod = url.startsWith('https') ? https : http;
    const req = mod.get(url, { timeout: 10000 }, (res) => {
      let data = '';
      res.on('data', (chunk) => (data += chunk));
      res.on('end', () => resolve(data));
    });
    req.on('error', () => resolve(''));
    req.on('timeout', () => { req.destroy(); resolve(''); });
  });
}

async function initProxyPool() {
  if (!useProxy) {
    console.log('⚡ 直连模式 (不使用代理)\n');
    return;
  }

  console.log('🔄 正在下载免费代理列表...');
  let raw = '';
  for (const url of PROXY_SOURCES) {
    raw = await downloadProxies(url);
    if (raw && raw.length > 100) break;
  }

  if (!raw) {
    console.log('⚠ 无法下载代理列表，切换为直连模式\n');
    useProxy = false;
    return;
  }

  const proxies = raw
    .split('\n')
    .map((l) => l.trim())
    .filter((l) => /^\d+\.\d+\.\d+\.\d+:\d+$/.test(l));

  // 打乱顺序，取前 200 个测试
  const shuffled = proxies.sort(() => Math.random() - 0.5).slice(0, 200);
  console.log(`  下载 ${proxies.length} 个代理，测试前 ${shuffled.length} 个...\n`);

  // 并发测试代理（每批 20 个）
  const BATCH = 20;
  for (let i = 0; i < shuffled.length && proxyPool.length < 30; i += BATCH) {
    const batch = shuffled.slice(i, i + BATCH);
    const results = await Promise.all(batch.map((p) => testProxy(p)));
    const working = results.filter(Boolean);
    proxyPool.push(...working);
    process.stdout.write(
      `  测试 ${Math.min(i + BATCH, shuffled.length)}/${shuffled.length} | 可用: ${proxyPool.length}\r`
    );
    if (proxyPool.length >= 30) break;
  }

  console.log(`\n  ✓ 代理池就绪: ${proxyPool.length} 个可用代理\n`);

  if (proxyPool.length === 0) {
    console.log('⚠ 无可用代理，切换为直连模式\n');
    useProxy = false;
  }
}

// 测试单个代理是否能访问 cfcpn API
function testProxy(proxyStr) {
  return new Promise((resolve) => {
    const [host, port] = proxyStr.split(':');
    const postData = new URLSearchParams({
      id: '003ff714d80444df82f39713d51c6142',
      isDetail: '1',
    }).toString();

    const req = http.request(
      {
        host,
        port: parseInt(port),
        method: 'CONNECT',
        path: 'www.cfcpn.com:80',
      }
    );

    req.on('connect', (_res, socket) => {
      const apiReq = http.request(
        {
          host: 'www.cfcpn.com',
          port: 80,
          path: '/jcw/noticeinfo/noticeInfo/dataNoticeList',
          method: 'POST',
          headers: {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Content-Length': Buffer.byteLength(postData),
          },
          socket: socket,
          agent: new http.Agent({ keepAlive: false }),
        },
        (res) => {
          let data = '';
          res.on('data', (c) => (data += c));
          res.on('end', () => {
            try {
              const json = JSON.parse(data);
              if (json.result && json.rows && json.rows[0] && json.rows[0].noticeContent) {
                resolve({ host, port: parseInt(port), proxy: proxyStr });
              } else {
                resolve(null);
              }
            } catch {
              resolve(null);
            }
          });
        }
      );
      apiReq.on('error', () => resolve(null));
      apiReq.write(postData);
      apiReq.end();
    });

    req.on('error', () => resolve(null));
    req.setTimeout(8000, () => { req.destroy(); resolve(null); });
    req.end();
  });
}

// 获取下一个代理（轮转）
function getNextProxy() {
  if (proxyPool.length === 0) return null;
  const proxy = proxyPool[proxyIndex % proxyPool.length];
  proxyIndex++;
  return proxy;
}

// 移除坏掉的代理
function removeProxy(proxy) {
  const idx = proxyPool.findIndex((p) => p.proxy === proxy.proxy);
  if (idx >= 0) {
    proxyPool.splice(idx, 1);
    if (proxyIndex >= proxyPool.length) proxyIndex = 0;
  }
}

// ===================== 请求层（支持代理） =====================

function apiRequestDirect(params) {
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

function apiRequestViaProxy(params, proxy) {
  const postData = new URLSearchParams(params).toString();
  return new Promise((resolve, reject) => {
    const connectReq = http.request({
      host: proxy.host,
      port: proxy.port,
      method: 'CONNECT',
      path: 'www.cfcpn.com:80',
    });

    connectReq.on('connect', (_res, socket) => {
      const req = http.request(
        {
          host: 'www.cfcpn.com',
          port: 80,
          path: '/jcw/noticeinfo/noticeInfo/dataNoticeList',
          method: 'POST',
          headers: {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Content-Length': Buffer.byteLength(postData),
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
          },
          socket,
          agent: new http.Agent({ keepAlive: false }),
        },
        (res) => {
          let data = '';
          res.on('data', (c) => (data += c));
          res.on('end', () => {
            try { resolve(JSON.parse(data)); }
            catch { reject(new Error(`JSON parse: ${data.substring(0, 100)}`)); }
          });
        }
      );
      req.on('error', reject);
      req.setTimeout(15000, () => { req.destroy(); reject(new Error('proxy timeout')); });
      req.write(postData);
      req.end();
    });

    connectReq.on('error', reject);
    connectReq.setTimeout(10000, () => { connectReq.destroy(); reject(new Error('connect timeout')); });
    connectReq.end();
  });
}

// ===================== 限频退避 + 代理轮转 =====================

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function apiRequest(params) {
  if (!useProxy || proxyPool.length === 0) {
    return apiRequestDirect(params);
  }

  const proxy = getNextProxy();
  try {
    return await apiRequestViaProxy(params, proxy);
  } catch {
    removeProxy(proxy);
    // fallback to direct
    return apiRequestDirect(params);
  }
}

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
        console.log(`    ⚠ 限频 → 等待 ${waitSec}s (${attempt}/${MAX_ATTEMPTS}) [代理池: ${proxyPool.length}]`);
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

// ===================== HTML 处理 =====================

function stripHtml(html) {
  if (!html) return '';
  let t = html;
  t = t.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
  t = t.replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&nbsp;/g, ' ');
  t = t.replace(/&ldquo;/g, '\u201C').replace(/&rdquo;/g, '\u201D').replace(/&mdash;/g, '\u2014');
  t = t.replace(/<br\s*\/?>/gi, '\n');
  t = t.replace(/<\/?(p|div|li|tr|h[1-6]|table|section|article)\b[^>]*>/gi, '\n');
  t = t.replace(/<[^>]+>/g, '');
  t = t.replace(/[ \t]+/g, ' ');
  t = t.replace(/\n[ \t]+/g, '\n');
  t = t.replace(/\n{3,}/g, '\n\n');
  return t.trim();
}

// ===================== 进度管理 =====================

function saveProgress(p) { fs.writeFileSync(PROGRESS_FILE, JSON.stringify(p, null, 2), 'utf8'); }

function saveOutput(rows, total) {
  const jsonOutput = {
    scrapeTime: new Date().toISOString(), total, scraped: rows.length,
    rows: rows.map((r) => ({
      id: r.id, title: r.noticeTitle, publishTime: r.publishTime,
      purchaser: r.userName, method: r.purchaseTypeLable, region: r.area,
      category: r.labelAllId, tags: r.yxCategoryNames, source: r.noticeSource,
      content: stripHtml(r.noticeContent),
    })),
  };
  fs.writeFileSync(OUTPUT_JSON, JSON.stringify(jsonOutput, null, 2), 'utf8');
}

function loadExistingData() {
  if (fs.existsSync(PROGRESS_FILE)) {
    try { const p = JSON.parse(fs.readFileSync(PROGRESS_FILE, 'utf8')); if (p.rows?.length) return p; } catch {}
  }
  if (fs.existsSync(OUTPUT_JSON)) {
    try {
      const j = JSON.parse(fs.readFileSync(OUTPUT_JSON, 'utf8'));
      if (j.rows?.length) {
        const rows = j.rows.map((r) => ({
          id: r.id, noticeTitle: r.title, publishTime: r.publishTime,
          userName: r.purchaser, purchaseTypeLable: r.method, area: r.region,
          labelAllId: r.category, yxCategoryNames: r.tags, noticeSource: r.source,
          noticeContent: r.content ? '__loaded__' : '',
        }));
        return { rows, total: j.total, nextDetailIdx: 0 };
      }
    } catch {}
  }
  return null;
}

// ===================== 主流程 =====================

async function main() {
  const args = process.argv.slice(2);
  const isResume = args.includes('resume');
  const noProxy = args.includes('--no-proxy');
  const listIdx = args.indexOf('--list');
  const listPages = listIdx >= 0 ? args[listIdx + 1] : null;
  const beginIdx = args.indexOf('--begin-date');
  const endIdx = args.indexOf('--end-date');
  if (beginIdx >= 0) dateBegin = args[beginIdx + 1] || '';
  if (endIdx >= 0) dateEnd = args[endIdx + 1] || '';

  if (noProxy) useProxy = false;

  // 初始化代理池
  await initProxyPool();

  let allRows = [];
  let total = 0;
  let startDetailIdx = 0;

  // ---- 可选：爬列表 ----
  if (listPages) {
    const maxPages = listPages === 'all' ? 99999 : parseInt(listPages) || 5;
    console.log(`[1/3] 爬取列表 ${maxPages === 99999 ? '全部' : maxPages + ' 页'}...\n`);

    for (let page = 1; page <= maxPages; page++) {
      await sleep(2000);
      const d = await requestWithBackoff(() => fetchPage(page), `列表${page}`);
      if (!d?.result) { console.error(`API 错误: ${d?.message || 'unknown'}`); process.exit(1); }
      if (!d.rows?.length) { if (page === 1) { console.log('  无数据'); } break; }
      if (page === 1) { total = d.total; console.log(`  API 共 ${total} 条`); }

      // 客户端日期过滤
      const filtered = d.rows.filter(isInDateRange);
      allRows.push(...filtered);
      console.log(`  第 ${page} 页 ✓ (${filtered.length}/${d.rows.length} 条匹配)`);

      // 如果数据已经早于起始日期，停止翻页
      const oldestOnPage = d.rows[d.rows.length - 1]?.publishTime?.substring(0, 10) || '';
      if (dateBegin && oldestOnPage < dateBegin) {
        console.log(`  已超出日期范围，停止翻页`);
        break;
      }
      saveProgress({ rows: allRows, total: allRows.length, nextDetailIdx: 0 });
    }
    console.log(`  列表完成: ${allRows.length} 条\n`);
  }

  // ---- 加载已有数据 ----
  if (allRows.length === 0) {
    if (listPages) {
      console.log('✓ 该日期范围内无数据');
      return;
    }
    if (isResume) {
      const p = loadExistingData();
      if (!p?.rows) { console.error('⚠ 无进度文件'); process.exit(1); }
      allRows = p.rows; total = p.total || allRows.length; startDetailIdx = p.nextDetailIdx || 0;
      console.log(`♻ 续爬: ${allRows.length} 条, 正文从第 ${startDetailIdx + 1} 条\n`);
    } else {
      const e = loadExistingData();
      if (!e?.rows) { console.error('⚠ 无数据文件，用 --list 5 先爬列表'); process.exit(1); }
      allRows = e.rows; total = e.total || allRows.length;
      console.log(`📂 加载 ${allRows.length} 条\n`);
    }
  }

  // ---- 抓正文 ----
  console.log(`[2/3] 爬取 ${allRows.length} 条正文 (从第 ${startDetailIdx + 1} 条, 代理池: ${proxyPool.length})...\n`);

  for (let i = startDetailIdx; i < allRows.length; i++) {
    const row = allRows[i];
    if (row.noticeContent && row.noticeContent !== '__loaded__') continue;

    await sleep(2000);

    const detail = await requestWithBackoff(() => fetchDetail(row.id), `正文${i + 1}`);
    if (detail?.result && detail.rows?.[0]) {
      row.noticeContent = detail.rows[0].noticeContent || '';
    } else {
      row.noticeContent = '';
    }

    const st = row.noticeContent ? '✓' : '⚠';
    console.log(`  [${i + 1}/${allRows.length}] ${row.noticeTitle?.substring(0, 30)}... ${st} [代理: ${proxyPool.length}]`);

    if ((i + 1) % 5 === 0 || i === allRows.length - 1) {
      saveProgress({ rows: allRows, total, nextDetailIdx: i + 1 });
      saveOutput(allRows, total);
    }
  }

  console.log(`\n[3/3] 保存...`);
  saveOutput(allRows, total);
  console.log(`  JSON: ${OUTPUT_JSON}`);
  if (fs.existsSync(PROGRESS_FILE)) fs.unlinkSync(PROGRESS_FILE);
  console.log(`\n✓ 完成！${allRows.length} 条`);
}

main().catch((e) => { console.error('失败:', e.message); process.exit(1); });
