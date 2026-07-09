/**
 * 中国银行中银智采 (BOC PCM) 采购公告爬虫
 *
 * Usage:
 *   node scrape_boc_pcm.js --yesterday        # 爬取昨天发布的公告
 *   node scrape_boc_pcm.js --latest 5         # 爬取最新 N 条公告（默认5条）
 *   node scrape_boc_pcm.js --latest 10        # 爬取最新 10 条公告
 *   node scrape_boc_pcm.js --date 2026-07-03  # 爬取指定日期的公告
 */

const https = require('https');
const fs = require('fs');
const path = require('path');
const { stripHtml } = require('./utility/stripHtml');
const { JsonWriter } = require('./utility/JsonWriter');

const OUTPUT_JSON = path.join(__dirname, '..', '..', 'raw_data', 'boc_pcm_data.json');
const BASE_URL = '/pcm/c-pcm-web/C08411SUP000/v1/SupplierEnroll/client';
const HOSTNAME = 'ctpch.fmscop.bankofchina.com';

// ===================== 请求层 =====================

/**
 * 构造 BOC PCM API 的 reqHeader
 * 该接口需要标准的请求头包装，否则返回 500
 */
function buildReqHeader(apiPath) {
  const now = new Date();
  const pad = (n, len = 2) => String(n).padStart(len, '0');
  const ts =
    now.getFullYear() +
    pad(now.getMonth() + 1) +
    pad(now.getDate()) +
    pad(now.getHours()) +
    pad(now.getMinutes()) +
    pad(now.getSeconds());

  let globalSerNo = 'C084110647U5A' + ts;
  for (let i = 0; i < 7; i++) globalSerNo += Math.floor(Math.random() * 10);

  const requestTime =
    now.getFullYear() +
    pad(now.getMonth() + 1) +
    pad(now.getDate()) +
    ' ' +
    pad(now.getHours()) +
    ':' +
    pad(now.getMinutes()) +
    ':' +
    pad(now.getSeconds()) +
    '.' +
    pad(now.getMilliseconds(), 3);

  // apiCode 从路径中提取 /v1 之后的部分
  const apiCode = apiPath.substring(apiPath.indexOf('/v1') + 3);

  return {
    formatVer: '01',
    globalSerNo,
    txnSerNo: '10000000000000000000',
    requestTime,
    callCode: 'A084110647U5A',
    channelCode: '000100',
    entityCode: '003',
    targetSerCode: 'C08411GWG100',
    apiCode,
    apiVer: 'v1',
    branchNo: '',
    shardingType: '09',
    shardingKey: '',
    msgLvl: '1',
    msgStatus: '1',
    zipMethod: '01',
    encryptFlag: '1',
    encryptKeyVer: '0',
    initialVector: '',
    reserveField: '',
  };
}

/**
 * 发送 API 请求
 * @param {string} apiPath - API 路径（不含 hostname），如 /SupplierEnroll/client/getNoticeByType
 * @param {object} reqBody - 请求体
 * @returns {Promise<object>} respBody
 */
function apiRequest(apiPath, reqBody) {
  const fullPath = BASE_URL + apiPath;
  const payload = JSON.stringify({
    reqHeader: buildReqHeader(fullPath),
    reqBody,
  });

  return new Promise((resolve, reject) => {
    const req = https.request(
      {
        hostname: HOSTNAME,
        port: 443,
        path: fullPath,
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Content-Length': Buffer.byteLength(payload),
          'User-Agent':
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
          Referer: `https://${HOSTNAME}/pcm/`,
          Origin: `https://${HOSTNAME}`,
        },
      },
      (res) => {
        let data = '';
        res.on('data', (c) => (data += c));
        res.on('end', () => {
          if (res.statusCode !== 200) {
            reject(new Error(`HTTP ${res.statusCode}: ${data.substring(0, 200)}`));
            return;
          }
          try {
            const json = JSON.parse(data);
            if (json.respHeader && json.respHeader.respStatus !== '00') {
              reject(
                new Error(
                  `API error: ${json.respHeader.respStatus} - ${json.respMsgAuth || 'unknown'}`
                )
              );
              return;
            }
            resolve(json.respBody);
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
 * @param {number} pageNo - 页码
 * @param {number} pageSize - 每页条数
 * @param {object} [extra] - 额外过滤条件
 * @returns {Promise<{data: Array, totalRecord: number}>}
 */
function fetchList(pageNo, pageSize = 10, extra = {}) {
  return apiRequest('/getNoticeByType', {
    orgType: 1, // 1=总行, 不传则全部
    pageSize,
    pageNo,
    ...extra,
  });
}

/**
 * 获取公告详情
 * @param {string} pkNotice - 公告 ID
 * @param {string} noticeType - 公告类型
 * @returns {Promise<object>}
 */
function fetchDetail(pkNotice, noticeType) {
  return apiRequest('/getNoticeDetail', { pkNotice, noticeType });
}

/**
 * noticeType 映射
 * 1 = 招标公告, 2 = 变更公告, 3 = 结果公告
 */
const NOTICE_TYPE_MAP = {
  '1': '招标公告',
  '2': '变更公告',
  '3': '结果公告',
};

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

// ===================== 主流程 =====================

async function main() {
  const args = process.argv.slice(2);

  // ---- --info: 输出元数据 JSON ----
  if (args.includes('--info')) {
    console.log(JSON.stringify({
      name: 'boc_pcm',
      description: '中国银行中银智采 (BOC PCM) 采购公告爬虫',
      modes: ['latest', 'yesterday', 'date'],
      outputFile: 'raw_data/boc_pcm_data.json',
    }));
    return;
  }

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

    if (!result || !result.data || result.data.length === 0) {
      console.log('  无数据');
      return;
    }

    allItems = result.data.slice(0, count);
    console.log(`    API 共 ${result.totalRecord} 条，选取 ${allItems.length} 条`);
  } else {
    // ---- 按日期爬取 ----
    console.log(`  [列表] 日期 ${targetDate}`);
    let pageNo = 1;
    let foundAll = false;

    while (!foundAll) {
      await sleep(1500);
      const result = await requestWithBackoff(
        () => fetchList(pageNo, 20),
        `列表第${pageNo}页`
      );

      if (!result || !result.data || result.data.length === 0) {
        if (pageNo === 1) console.log('  无数据');
        break;
      }

      if (pageNo === 1) {
        console.log(`    API 共 ${result.totalRecord} 条`);
      }

      for (const item of result.data) {
        const pubDate = (item.ancmAncDt || '').substring(0, 10);
        if (pubDate === targetDate) {
          allItems.push(item);
        } else if (pubDate < targetDate) {
          // 已经过了目标日期，停止
          foundAll = true;
          break;
        }
      }

      console.log(
        `    第 ${pageNo} 页 ✓ (${allItems.length} 条匹配)`
      );

      // 如果本页最老的数据已经早于目标日期，停止
      const oldestDate = (result.data[result.data.length - 1]?.ancmAncDt || '').substring(0, 10);
      if (oldestDate < targetDate) {
        foundAll = true;
      }

      pageNo++;
    }

    console.log(`    共 ${allItems.length} 条匹配\n`);
  }

  if (allItems.length === 0) {
    console.log('✓ 无匹配数据');
    new JsonWriter(OUTPUT_JSON, { source: '中银智采', scrapeTime: new Date().toISOString() });
    return;
  }

  // ---- 初始化增量写入器 ----
  const writer = new JsonWriter(OUTPUT_JSON, {
    source: '中银智采',
    scrapeTime: new Date().toISOString(),
  });

  // ---- 爬取详情 ----
  console.log(`  [详情] ${allItems.length} 条`);

  for (let i = 0; i < allItems.length; i++) {
    const item = allItems[i];

    if (!item.ancmCntnt) {
      await sleep(2000);
      try {
        const detail = await requestWithBackoff(
          () => fetchDetail(item.pkNotice, item.noticeType),
          `详情${i + 1}`
        );
        if (detail) {
          item.ancmCntnt = detail.ancmCntnt || '';
          item.ancmAttached = detail.ancmAttached || item.ancmAttached;
          if (detail.ancmAncDt) item.ancmAncDt = detail.ancmAncDt;
          if (detail.ancmHdlnCntnt) item.ancmHdlnCntnt = detail.ancmHdlnCntnt;
        }
      } catch (e) {
        item.ancmCntnt = '';
      }
    }

    const st = item.ancmCntnt ? '✓' : '✗';
    console.log(
      `    [${i + 1}/${allItems.length}] ${item.ancmHdlnCntnt?.substring(0, 40)}... ${st}`
    );

    writer.addRow({
      publishTime: item.ancmAncDt,
      noticeType: NOTICE_TYPE_MAP[item.noticeType] || item.noticeType,
      content: stripHtml(item.ancmCntnt || ''),
    });
  }

  console.log(`\n✓ boc_pcm (${writer.count}/${writer.count})`);
}

main().catch((e) => {
  console.error('失败:', e.message);
  process.exit(1);
});
