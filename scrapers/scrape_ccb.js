/**
 * 龙集采 / 建设银行采购网 (CCB) 招标专区爬虫
 *
 * Usage:
 *   node scrape_ccb.js --yesterday        # 爬取昨天发布的公告
 *   node scrape_ccb.js --latest 5         # 爬取最新 N 条公告（默认5条）
 *   node scrape_ccb.js --date 2026-07-06  # 爬取指定日期的公告
 *
 * 数据来源：静态 JSON 文件
 *   列表：/json/contentFile/{channelId}/{page}.json
 *   详情：/json/contentFile/{channelId}/{year}/{id}.json
 */

const https = require('https');
const fs = require('fs');
const path = require('path');
const { stripHtml } = require('./utility/stripHtml');
const { JsonWriter } = require('./utility/JsonWriter');

const OUTPUT_JSON = path.join(__dirname, '..', '..', 'raw_data', 'ccb_data.json');
const SITE_BASE = 'https://ibuy.ccb.com';
const CHANNEL_ID = '355'; // 招标公告

// 每页 1000 条（该站点 JSON 固定返回 1000 条/页）
const PAGE_SIZE = 1000;

// ===================== HTTP 请求 =====================

function httpGet(url) {
  return new Promise((resolve, reject) => {
    https.get(url, {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        Accept: 'application/json, text/plain, */*',
        Referer: `${SITE_BASE}/cms/index.html`,
      },
    }, (res) => {
      if (res.statusCode !== 200) {
        reject(new Error(`HTTP ${res.statusCode}: ${url}`));
        res.resume();
        return;
      }
      let data = '';
      res.setEncoding('utf8');
      res.on('data', c => data += c);
      res.on('end', () => {
        try {
          resolve(JSON.parse(data));
        } catch (e) {
          reject(new Error(`JSON parse error: ${e.message}`));
        }
      });
    }).on('error', reject);
  });
}

// ===================== 限频退避 =====================

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function requestWithBackoff(requestFn, label) {
  let delay = 3000;
  const MAX_ATTEMPTS = 4;

  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
    try {
      return await requestFn();
    } catch (e) {
      if (attempt < MAX_ATTEMPTS) {
        console.log(`    ⚠ 请求异常: ${e.message}，等待 ${delay / 1000}s...`);
        await sleep(delay);
        delay *= 2;
      } else {
        console.log(`    ✗ ${label}: 失败，已重试 ${MAX_ATTEMPTS} 次`);
        throw e;
      }
    }
  }
}

// ===================== 类型映射 =====================

const CHANNEL_TYPE_MAP = {
  '355': '招标公告',
  '356': '资格预审公告',
  '357': '变更公告',
  '358': '中标候选人公示',
  '359': '中标结果公示',
  '379': '其他公告',
};

// ===================== API 封装 =====================

/**
 * 获取列表页
 * @param {number} pageNo - 页码（从1开始）
 * @returns {Promise<Array>} 公告列表
 */
async function fetchList(pageNo) {
  const url = `${SITE_BASE}/json/contentFile/${CHANNEL_ID}/${pageNo}.json?t=1`;
  const data = await httpGet(url);
  // data 是数组，每项包含 {id, channelId, title, releaseDate, releaseInst, ptInst, area}
  return Array.isArray(data) ? data : [];
}

/**
 * 获取公告详情
 * @param {string} id - 公告 ID
 * @param {string} releaseDate - 发布日期（用于构造路径中的年份）
 * @returns {Promise<object>} 详情对象（含 content 字段）
 */
async function fetchDetail(id, releaseDate) {
  const year = (releaseDate || '').substring(0, 4) || 'null';
  const url = `${SITE_BASE}/json/contentFile/${CHANNEL_ID}/${year}/${id}.json?t=1`;
  const data = await httpGet(url);
  return data.data || data;
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

// ===================== 主流程 =====================

async function main() {
  const args = process.argv.slice(2);

  // ---- --info: 输出元数据 JSON ----
  if (args.includes('--info')) {
    console.log(JSON.stringify({
      name: 'ccb',
      description: '龙集采 / 建设银行采购网 (CCB) 招标专区爬虫',
      modes: ['latest', 'yesterday', 'date'],
      outputFile: 'raw_data/ccb_data.json',
    }));
    return;
  }

  let mode = 'latest';
  let count = 5;
  let targetDate = null;

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
    console.log(`  [列表] 最新 ${count} 条`);
    const items = await requestWithBackoff(
      () => fetchList(1),
      '列表'
    );

    if (items.length === 0) {
      console.log('  无数据');
      return;
    }

    allItems = items.slice(0, count);
    console.log(`    第1页 ${items.length} 条，选取 ${allItems.length} 条`);
  } else {
    console.log(`  [列表] 日期 ${targetDate}`);
    let pageNo = 1;
    let foundAll = false;

    while (!foundAll) {
      if (pageNo > 1) await sleep(1500);
      const items = await requestWithBackoff(
        () => fetchList(pageNo),
        `列表第${pageNo}页`
      );

      if (items.length === 0) {
        if (pageNo === 1) console.log('  无数据');
        break;
      }

      let matchedThisPage = 0;
      for (const item of items) {
        const pubDate = (item.releaseDate || '').substring(0, 10);
        if (pubDate === targetDate) {
          allItems.push(item);
          matchedThisPage++;
        } else if (pubDate < targetDate) {
          foundAll = true;
          break;
        }
      }

      console.log(
        `    第 ${pageNo} 页 ✓ (${allItems.length} 条匹配)`
      );

      // 如果本页数据不足 PAGE_SIZE 条，说明是最后一页
      if (items.length < PAGE_SIZE) foundAll = true;
      pageNo++;
    }

    console.log(`    共 ${allItems.length} 条匹配\n`);
  }

  if (allItems.length === 0) {
    console.log('✓ 无匹配数据');
    new JsonWriter(OUTPUT_JSON, { source: '龙集采', scrapeTime: new Date().toISOString() });
    return;
  }

  // ---- 初始化增量写入器 ----
  const writer = new JsonWriter(OUTPUT_JSON, {
    source: '龙集采',
    scrapeTime: new Date().toISOString(),
  });

  // ---- 爬取详情 ----
  console.log(`  [详情] ${allItems.length} 条`);

  for (let i = 0; i < allItems.length; i++) {
    const item = allItems[i];

    if (i > 0) await sleep(1000 + Math.random() * 1000);

    try {
      const detail = await requestWithBackoff(
        () => fetchDetail(item.id, item.releaseDate),
        `详情${i + 1}`
      );

      const content = stripHtml(detail.content || '');
      if (content) {
        item.content = content;
        console.log(`    [${i + 1}/${allItems.length}] ${item.title.substring(0, 40)}... ✓ (${content.length}字)`);
      } else {
        console.log(`    [${i + 1}/${allItems.length}] ${item.title.substring(0, 40)}... ✗`);
      }
    } catch (e) {
      console.log(`    [${i + 1}/${allItems.length}] ${item.title.substring(0, 40)}... ✗ ${e.message}`);
    }

    writer.addRow({
      publishTime: (item.releaseDate || '').substring(0, 10),
      noticeType: CHANNEL_TYPE_MAP[item.channelId] || '招标公告',
      content: item.content || item.title,
    });
  }

  console.log(`\n✓ ccb (${writer.count}/${writer.count})`);
}

main().catch((e) => {
  console.error('失败:', e.message);
  process.exit(1);
});
