/**
 * 工商银行工银集采 (ICBC) 招标公告爬虫
 *
 * 数据来源: https://jc.icbc.com.cn/#/announcementList/2
 *
 * Usage:
 *   node scrape_icbc.js --yesterday        # 爬取昨天发布的公告
 *   node scrape_icbc.js --latest 5         # 爬取最新 N 条公告（默认5条）
 *   node scrape_icbc.js --latest 10        # 爬取最新 10 条公告
 *   node scrape_icbc.js --date 2026-07-05  # 爬取指定日期的公告
 */

const https = require('https');
const fs = require('fs');
const path = require('path');

const OUTPUT_JSON = path.join(__dirname, '..', '..', 'row_data', 'icbc_data.json');
const HOSTNAME = 'jc.icbc.com.cn';
const API_PATH = '/app/queryPortalNoticeInfoPage';

// ===================== 请求层 =====================

/**
 * 发送 API 请求
 * @param {object} body - 请求体
 * @returns {Promise<object>}
 */
function apiRequest(body) {
  const payload = JSON.stringify(body);

  return new Promise((resolve, reject) => {
    const req = https.request(
      {
        hostname: HOSTNAME,
        port: 443,
        path: API_PATH,
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Content-Length': Buffer.byteLength(payload),
          'User-Agent':
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
          Referer: `https://${HOSTNAME}/`,
          Origin: `https://${HOSTNAME}`,
        },
      },
      (res) => {
        let data = '';
        res.on('data', (c) => (data += c));
        res.on('end', () => {
          if (res.statusCode !== 200) {
            reject(
              new Error(`HTTP ${res.statusCode}: ${data.substring(0, 200)}`)
            );
            return;
          }
          try {
            resolve(JSON.parse(data));
          } catch (e) {
            reject(new Error(`JSON parse: ${data.substring(0, 200)}`));
          }
        });
      }
    );
    req.on('error', reject);
    req.setTimeout(15000, () => {
      req.destroy();
      reject(new Error('timeout'));
    });
    req.write(payload);
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
      return await requestFn();
    } catch (e) {
      if (attempt < MAX_ATTEMPTS) {
        console.log(`    ⚠ 请求异常: ${e.message}，等待 ${delay / 1000}s...`);
        await sleep(delay);
        delay = Math.min(delay * 2, MAX_DELAY);
      } else {
        console.log(`    ✗ ${label}: 失败，已重试 ${MAX_ATTEMPTS} 次`);
        throw e;
      }
    }
  }
}

// ===================== API 封装 =====================

/**
 * 获取公告列表
 * @param {number} curPage - 页码
 * @param {number} pageSize - 每页条数
 * @param {string} beginDate - 起始日期 yyyy-MM-dd
 * @param {string} endDate - 截止日期 yyyy-MM-dd
 * @returns {Promise<{rows: Array, totalNum: number, totalPage: number}>}
 */
function fetchList(curPage, pageSize = 10, beginDate = '', endDate = '') {
  return apiRequest({
    menuId: 'MENU030000000', // 招标公告
    projType: '',
    noticeStatus: '2',
    curPage,
    pageSize,
    branchIds: [],
    struSign: '',
    beginDate,
    endDate,
  });
}

/**
 * 获取公告详情（含正文 HTML）
 * @param {string} noticeId - 公告 ID
 * @returns {Promise<object>} noticeDetail
 */
function fetchDetail(noticeId) {
  return new Promise((resolve, reject) => {
    const req = https.request(
      {
        hostname: HOSTNAME,
        port: 443,
        path: `/app/api/notice/detail/${encodeURIComponent(noticeId)}`,
        method: 'GET',
        headers: {
          'User-Agent':
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
          Referer: `https://${HOSTNAME}/`,
        },
      },
      (res) => {
        let data = '';
        res.on('data', (c) => (data += c));
        res.on('end', () => {
          if (res.statusCode !== 200) {
            reject(
              new Error(`HTTP ${res.statusCode}: ${data.substring(0, 200)}`)
            );
            return;
          }
          try {
            const json = JSON.parse(data);
            resolve(json.noticeDetail || null);
          } catch (e) {
            reject(new Error(`JSON parse: ${data.substring(0, 200)}`));
          }
        });
      }
    );
    req.on('error', reject);
    req.setTimeout(15000, () => {
      req.destroy();
      reject(new Error('timeout'));
    });
    req.end();
  });
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

/**
 * 格式化 ICBC 时间戳
 * "202607061531" → "2026-07-06 15:31"
 */
function formatIssueDate(raw) {
  if (!raw || raw.length < 8) return raw || '';
  const y = raw.substring(0, 4);
  const m = raw.substring(4, 6);
  const d = raw.substring(6, 8);
  const h = raw.length >= 10 ? raw.substring(8, 10) : '00';
  const min = raw.length >= 12 ? raw.substring(10, 12) : '00';
  return `${y}-${m}-${d} ${h}:${min}`;
}

/**
 * 从 issueDate 中提取日期部分 yyyy-MM-dd
 */
function extractDate(raw) {
  if (!raw || raw.length < 8) return '';
  return `${raw.substring(0, 4)}-${raw.substring(4, 6)}-${raw.substring(6, 8)}`;
}

// ===================== HTML 转纯文本 =====================

/**
 * 将 HTML 转为纯文本
 * - 去除所有标签
 * - 将 &nbsp; 等实体转义为空格
 * - 合并多余空白行
 */
function stripHtml(html) {
  if (!html) return '';
  return html
    // <br> / <p> / <div> 等块级元素转为换行
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/p>/gi, '\n')
    .replace(/<\/div>/gi, '\n')
    .replace(/<\/li>/gi, '\n')
    // 去除所有标签
    .replace(/<[^>]+>/g, '')
    // 常见 HTML 实体
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    // 合并连续空格为单个
    .replace(/[ \t]+/g, ' ')
    // 合并连续空行为单个
    .replace(/\n\s*\n/g, '\n')
    .trim();
}

// ===================== 保存输出 =====================

function saveOutput(rows) {
  const jsonOutput = {
    source: '工银集采',
    scrapeTime: new Date().toISOString(),
    rows: rows.map((r) => ({
      publishTime: formatIssueDate(r.issueDate),
      title: r.noticeTitle,
      branch: r.structName,
      projType: r.projTypeName,
      status: r.noticeStatus,
      sourceUrl: r.noticeUrl || '',
      content: stripHtml(r._content),
    })),
  };
  fs.writeFileSync(OUTPUT_JSON, JSON.stringify(jsonOutput, null, 2), 'utf8');
  return jsonOutput;
}

// ===================== 主流程 =====================

async function main() {
  const args = process.argv.slice(2);

  let mode = 'latest';
  let count = 5;
  let targetDate = null;

  // 解析参数
  const yesterdayIdx = args.indexOf('--yesterday');
  const latestIdx = args.indexOf('--latest');
  const dateIdx = args.indexOf('--date');

  if (yesterdayIdx >= 0) {
    mode = 'date';
    targetDate = getYesterday();
  } else if (dateIdx >= 0) {
    mode = 'date';
    targetDate = args[dateIdx + 1];
    if (!targetDate || !/^\d{4}-\d{2}-\d{2}$/.test(targetDate)) {
      console.error('✗ --date 参数格式错误，应为 yyyy-MM-dd');
      process.exit(1);
    }
  } else if (latestIdx >= 0) {
    mode = 'latest';
    count = parseInt(args[latestIdx + 1]) || 5;
  }

  let allItems = [];

  if (mode === 'latest') {
    // ---- 爬取最新 N 条 ----
    console.log(`  [列表] 最新 ${count} 条`);
    const result = await requestWithBackoff(
      () => fetchList(1, Math.max(count, 10)),
      '列表'
    );

    if (!result || !result.rows || result.rows.length === 0) {
      console.log('  无数据');
      saveOutput([]);
      return;
    }

    allItems = result.rows.slice(0, count);
    console.log(`    API 共 ${result.totalNum} 条，选取 ${allItems.length} 条`);
  } else {
    // ---- 按日期爬取 ----
    console.log(`  [列表] 日期 ${targetDate}`);

    const result = await requestWithBackoff(
      () => fetchList(1, 100, targetDate, targetDate),
      `日期筛选 ${targetDate}`
    );

    if (!result || !result.rows || result.rows.length === 0) {
      console.log('  无数据');
      saveOutput([]);
      return;
    }

    allItems = result.rows;

    // 如果数据量超过 100 条，翻页获取剩余
    if (result.totalNum > 100) {
      const totalPages = result.totalPage;
      console.log(`    共 ${result.totalNum} 条，需翻 ${totalPages} 页`);
      for (let page = 2; page <= totalPages; page++) {
        await sleep(1500);
        const pageResult = await requestWithBackoff(
          () => fetchList(page, 100, targetDate, targetDate),
          `日期筛选第${page}页`
        );
        if (!pageResult || !pageResult.rows || pageResult.rows.length === 0) {
          break;
        }
        allItems = allItems.concat(pageResult.rows);
        console.log(`    第 ${page}/${totalPages} 页 ✓`);
      }
    }

    console.log(`    共 ${allItems.length} 条匹配\n`);
  }

  if (allItems.length === 0) {
    console.log('✓ 无匹配数据');
    saveOutput([]);
    return;
  }

  // ---- 爬取详情 ----
  console.log(`  [详情] ${allItems.length} 条`);

  for (let i = 0; i < allItems.length; i++) {
    const item = allItems[i];

    if (i > 0) await sleep(1500);

    try {
      const detail = await requestWithBackoff(
        () => fetchDetail(item.noticeId),
        `详情${i + 1}`
      );

      if (detail) {
        item._content = detail.noticeText || '';
        if (detail.issueDate) item.issueDate = detail.issueDate;
        if (detail.noticeTitle) item.noticeTitle = detail.noticeTitle;
      }
    } catch (e) {
      item._content = '';
    }

    const st = item._content ? '✓' : '✗';
    console.log(
      `    [${i + 1}/${allItems.length}] ${item.noticeTitle.substring(0, 40)}... ${st}`
    );
  }

  // ---- 保存 ----
  const output = saveOutput(allItems);
  console.log(`\n✓ icbc (${output.rows.length}/${output.rows.length})`);
}

main().catch((e) => {
  console.error('失败:', e.message);
  process.exit(1);
});
