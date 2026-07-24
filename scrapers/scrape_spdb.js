/**
 * 浦发银行采购供应商门户 v2 (spdb_v2)
 * HTTP/HTTPS 直接请求方案 — 不依赖 Playwright
 * 解密链：AES-ECB (响应 data) + 自定义 Base64 (content 字段)
 *
 * Usage:
 *   node scrape_spdb_v2.js --info             # 输出元数据 JSON
 *   node scrape_spdb_v2.js --latest 5         # 爬取最新 N 条
 *   node scrape_spdb_v2.js --yesterday        # 爬取昨天数据
 *   node scrape_spdb_v2.js --date YYYY-MM-DD  # 爬取指定日期
 */

const https = require('https');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const { stripHtml } = require('./utility/stripHtml');
const { JsonWriter } = require('./utility/JsonWriter');

const OUTPUT_JSON = path.join(__dirname, '..', 'raw_data', 'spdb_v2_data.json');

const BASE_URL = 'https://ebuy.spdb.com.cn';
const APP_URL = `${BASE_URL}/app`;

// 公告类型映射
const NOTICE_TYPE_MAP = {
  '00100001': '招标公告',
  '0011004': '结果公告',
  '0011008': '招标公告',
  '00100010': '招标公告',
  '00100007': '变更公告',
  '00100011': '变更公告',
};

// ===================== 自定义 Base64 解码 =====================
const CUSTOM_ALPHABET = 'RSTUVWXYZaDEFGHIJKLMNOPQklmnopqrstuvwxyzbc45678defghijABC01239+/=';

function utf8Decode(str) {
  let result = '';
  let i = 0;
  while (i < str.length) {
    const c = str.charCodeAt(i);
    if (c < 128) { result += String.fromCharCode(c); i++; }
    else if (c > 191 && c < 224) {
      const c2 = str.charCodeAt(i + 1);
      result += String.fromCharCode((c & 31) << 6 | c2 & 63);
      i += 2;
    } else {
      const c2 = str.charCodeAt(i + 1);
      const c3 = str.charCodeAt(i + 2);
      result += String.fromCharCode((c & 15) << 12 | (c2 & 63) << 6 | c3 & 63);
      i += 3;
    }
  }
  return result;
}

function customBase64Decode(str) {
  str = str.replace(/[^A-Za-z0-9+/=]/g, '');
  let result = '';
  let d = 0;
  while (d < str.length) {
    const f = CUSTOM_ALPHABET.indexOf(str.charAt(d++));
    const C = CUSTOM_ALPHABET.indexOf(str.charAt(d++));
    const t = CUSTOM_ALPHABET.indexOf(str.charAt(d++));
    const n = CUSTOM_ALPHABET.indexOf(str.charAt(d++));
    const o = f << 2 | C >> 4;
    const c = (C & 15) << 4 | t >> 2;
    const h = (t & 3) << 6 | n;
    result += String.fromCharCode(o);
    if (t != 64) result += String.fromCharCode(c);
    if (n != 64) result += String.fromCharCode(h);
  }
  return utf8Decode(result);
}

function decodeHtml(str) {
  let r = str;
  r = r.replace(/%3E/g, '>').replace(/%3C/g, '<');
  return customBase64Decode(r);
}

// ===================== HTTP 请求 =====================
function httpRequest(url, options = {}) {
  return new Promise((resolve, reject) => {
    const parsed = new URL(url);
    const isHttps = parsed.protocol === 'https:';
    const lib = isHttps ? https : require('http');
    const reqOptions = {
      hostname: parsed.hostname,
      port: parsed.port || (isHttps ? 443 : 80),
      path: parsed.pathname + parsed.search,
      method: options.method || 'GET',
      headers: {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Connection': 'keep-alive',
        'Authorization': 'null',
        ...options.headers,
      },
      timeout: 30000,
      // 允许遗留 SSL 重协商（浦发服务器需要）
      secureOptions: crypto.constants.SSL_OP_LEGACY_SERVER_CONNECT,
    };

    if (options.body) {
      reqOptions.headers['Content-Type'] = options.headers?.['Content-Type'] || 'application/x-www-form-urlencoded;charset:utf-8';
      reqOptions.headers['Content-Length'] = Buffer.byteLength(options.body);
    }

    const req = lib.request(reqOptions, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          try {
            const jsonData = JSON.parse(data);
            // 提取响应头中的 Content-Visa
            const contentVisa = res.headers['content-visa'] || '';
            resolve({ data: jsonData, contentVisa });
          } catch (e) {
            reject(new Error(`JSON parse error: ${e.message}, raw: ${data.substring(0, 200)}`));
          }
        } else {
          reject(new Error(`HTTP ${res.statusCode}: ${data.substring(0, 300)}`));
        }
      });
    });

    req.on('error', reject);
    req.on('timeout', () => { req.destroy(); reject(new Error('Request timeout')); });

    if (options.body) req.write(options.body);
    req.end();
  });
}

// ===================== AES-ECB 解密 =====================
function decryptResponse(encryptedData, contentVisa) {
  if (!encryptedData || !contentVisa) return encryptedData;
  
  const keyStr = contentVisa + '39457352';
  const key = Buffer.from(keyStr.substring(0, 16), 'utf8');
  
  try {
    const decipher = crypto.createDecipheriv('aes-128-ecb', key, null);
    decipher.setAutoPadding(true);
    let decrypted = decipher.update(encryptedData, 'base64', 'utf8');
    decrypted += decipher.final('utf8');
    return JSON.parse(decrypted);
  } catch (e) {
    console.log(`    ⚠ AES 解密失败: ${e.message}`);
    return null;
  }
}

// ===================== 限频退避 =====================
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

async function requestWithBackoff(fn, label) {
  let delay = 4000;
  const MAX_ATTEMPTS = 5;
  const MAX_DELAY = 60000;
  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
    try {
      return await fn();
    } catch (e) {
      if (attempt < MAX_ATTEMPTS) {
        console.log(`    ⚠ ${label} (${attempt}/${MAX_ATTEMPTS}): ${e.message}，等待 ${delay / 1000}s...`);
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
  const d = new Date(); d.setDate(d.getDate() - 1); return formatDate(d);
}
function formatScrapeTime() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}`;
}

// ===================== API 调用 =====================

// 获取公告列表
async function fetchNoticeList(page, rows, params = {}) {
  const body = new URLSearchParams({
    page: String(page),
    rows: String(rows),
    noticeStatus: '9',
    validFlag: '1',
    orderRule: '1',
    from: 'notice',
    ...Object.fromEntries(Object.entries(params).map(([k, v]) => [k, String(v)])),
  });

  return requestWithBackoff(
    async () => {
      const result = await httpRequest(`${APP_URL}/noticeManagement/findPurchaseNotice`, {
        method: 'POST',
        body: body.toString(),
        headers: { 'Referer': `${BASE_URL}/#/notice` },
      });
      
      if (result.data.code !== 'AAAAAAA') {
        throw new Error(`API 返回异常: ${result.data.message}`);
      }
      
      // 解密 data 字段
      const decryptedData = decryptResponse(result.data.data, result.contentVisa);
      if (!decryptedData) {
        throw new Error('解密失败');
      }
      
      return decryptedData;
    },
    `获取列表 第${page}页`
  );
}

// ===================== 详情解析 =====================
function extractContent(content) {
  if (!content || typeof content !== 'string') return '';
  
  // 尝试自定义 Base64 解码
  try {
    const decoded = decodeHtml(content);
    if (decoded && decoded.length > 50) {
      return stripHtml(decoded);
    }
  } catch (e) {
    // 解码失败，尝试直接 stripHtml
  }
  
  // 如果已经是纯文本
  if (content.length > 200 && !content.match(/^[A-Za-z0-9+/=]+$/)) {
    return stripHtml(content);
  }
  
  return '';
}

// ===================== 主流程 =====================
async function main() {
  const args = process.argv.slice(2);

  if (args.includes('--info')) {
    console.log(JSON.stringify({
      name: 'spdb_v2',
      description: '浦发银行采购供应商门户 (HTTP直连版)',
      modes: ['latest', 'yesterday', 'date'],
      outputFile: 'raw_data/spdb_v2_data.json',
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

  console.log(`[spdb_v2] 模式: ${mode}${mode === 'date' ? ` 目标日期: ${targetDate}` : ` 数量: ${count}`}`);

  const scrapeTime = formatScrapeTime();
  const writer = new JsonWriter(OUTPUT_JSON, { source: 'spdb_v2', scrapeTime });
  const matchedRows = [];
  let totalCollected = 0;
  let page = 1;
  const pageSize = 10;
  const MAX_PAGES = mode === 'date' ? 15 : Math.ceil(count / pageSize) + 2;

  try {
    while (page <= MAX_PAGES) {
      console.log(`\n[spdb_v2] 获取列表 第${page}页...`);

      const params = {};
      if (mode === 'date' && targetDate) {
        params.startDate = targetDate;
        params.endDate = targetDate;
      }

      const result = await fetchNoticeList(page, pageSize, params);

      if (!result || !result.rows) {
        console.log(`  ✗ API 返回异常: ${JSON.stringify(result).substring(0, 300)}`);
        break;
      }

      const rows = result.rows;
      const total = result.total || 0;
      console.log(`  ✓ 第${page}页: ${rows.length} 条 (总计 ${total})`);

      if (rows.length === 0) break;

      // 日期过滤 + 客户端验证
      let pageItems = rows;
      if (mode === 'date' && targetDate) {
        pageItems = rows.filter(item => {
          const itemDate = (item.publishTime || item.createTime || '').substring(0, 10);
          return itemDate === targetDate;
        });
        console.log(`  客户端过滤: ${rows.length} 条中有 ${pageItems.length} 条是 ${targetDate} 的`);
      } else if (mode === 'latest') {
        const remaining = count - totalCollected;
        if (pageItems.length > remaining) {
          pageItems = pageItems.slice(0, remaining);
        }
      }

      // 逐条处理
      for (const item of pageItems) {
        const noticeId = item.noticeId || item.id;
        const title = item.title || item.noticeName || '';
        const publishTime = item.publishTime || item.createTime || '';
        const noticeTypeCode = item.noticeType ? String(item.noticeType) : '';
        const noticeType = item.noticeTypeName || item.typeName || NOTICE_TYPE_MAP[noticeTypeCode] || '';
        const publishPart = item.publishPart || '';
        const url = `${BASE_URL}/#/noticeDetail?noticeId=${noticeId}`;

        console.log(`  [${totalCollected + 1}/${mode === 'date' ? '?' : count}] ${title.substring(0, 50)}...`);

        // 解析 content
        let content = '';
        if (item.content) {
          content = extractContent(item.content);
        }

        // 如果 content 为空或过短，使用可用信息拼接
        if (!content || content.length < 100) {
          const parts = [];
          if (title) parts.push(`标题: ${title}`);
          if (publishTime) parts.push(`发布时间: ${publishTime}`);
          if (noticeType) parts.push(`公告类型: ${noticeType}`);
          if (publishPart) parts.push(`发布主体: ${publishPart}`);
          if (item.purchaseProject) parts.push(`采购项目: ${item.purchaseProject}`);
          if (item.projectName) parts.push(`项目名称: ${item.projectName}`);
          content = parts.join('\n\n');
        }

        const row = {
          title,
          content: content || title,
          publishTime,
          url,
          noticeType,
          noticeId,
          scrapeTime,
        };

        writer.addRow(row);
        matchedRows.push(row);
        totalCollected++;

        if (content.length < 200) {
          console.log(`    ⚠ content 较短 (${content.length} 字)`);
        } else {
          console.log(`    ✓ content ${content.length} 字`);
        }
      }

      // 终止条件检查
      if (mode === 'latest' && totalCollected >= count) break;

      if (mode === 'date' && targetDate) {
        const lastItem = rows[rows.length - 1];
        const lastDate = (lastItem.publishTime || lastItem.createTime || '').substring(0, 10);
        if (lastDate && lastDate < targetDate) {
          console.log(`  ✓ 当前页最早数据 ${lastDate} 早于目标日期 ${targetDate}，停止翻页`);
          break;
        }
        if (page * pageSize >= total) break;
      }

      page++;
      await sleep(2000 + Math.random() * 2000);
    }

    console.log(`\n[spdb_v2] 完成! 共采集 ${matchedRows.length} 条`);
    console.log(`  输出: ${OUTPUT_JSON}`);

    if (matchedRows.length === 0) {
      console.log('  ℹ 未采集到数据（可能是当天无公告）');
    }
  } catch (e) {
    console.error(`\n[spdb_v2] 失败: ${e.message}`);
    process.exit(1);
  }
}

main().catch((e) => { console.error('失败:', e.message); process.exit(1); });
