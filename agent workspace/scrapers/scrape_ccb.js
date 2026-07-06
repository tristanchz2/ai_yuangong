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

const OUTPUT_JSON = path.join(__dirname, '..', '..', 'row_data', 'ccb_data.json');
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

// ===================== HTML 解析 =====================

function stripHtml(s) {
  if (!s) return '';
  return s
    .replace(/<[^>]+>/g, '')
    .replace(/&nbsp;/g, ' ')
    .replace(/&lt;/g, '<').replace(/&gt;/g, '>')
    .replace(/&amp;/g, '&').replace(/&quot;/g, '"').replace(/&#\d+;/g, '')
    .replace(/[ \t]+/g, ' ')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
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

// ===================== 保存输出 =====================

function saveOutput(rows) {
  const jsonOutput = {
    scrapeTime: new Date().toISOString(),
    total: rows.length,
    rows: rows.map((r) => ({
      publishTime: (r.releaseDate || '').substring(0, 10),
      noticeType: CHANNEL_TYPE_MAP[r.channelId] || '招标公告',
      content: r.content || r.title,
    })),
  };
  fs.writeFileSync(OUTPUT_JSON, JSON.stringify(jsonOutput, null, 2), 'utf8');
  return jsonOutput;
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

  let mode = 'latest';
  let count = 5;
  let targetDate = null;

  const yesterdayIdx = args.indexOf('--yesterday');
  const latestIdx = args.indexOf('--latest');
  const dateIdx = args.indexOf('--date');

  if (yesterdayIdx >= 0) {
    mode = 'date';
    targetDate = getYesterday();
    console.log(`📅 模式：爬取昨天的公告 (${targetDate})\n`);
  } else if (dateIdx >= 0) {
    mode = 'date';
    targetDate = args[dateIdx + 1];
    if (!targetDate || !/^\d{4}-\d{2}-\d{2}$/.test(targetDate)) {
      console.error('⚠ --date 参数格式错误，应为 yyyy-MM-dd');
      process.exit(1);
    }
    console.log(`📅 模式：爬取指定日期的公告 (${targetDate})\n`);
  } else if (latestIdx >= 0) {
    mode = 'latest';
    count = parseInt(args[latestIdx + 1]) || 5;
    console.log(`📋 模式：爬取最新 ${count} 条公告\n`);
  } else {
    console.log(`📋 模式：爬取最新 ${count} 条公告（默认）\n`);
  }

  let allItems = [];

  if (mode === 'latest') {
    console.log('[1/2] 获取公告列表...');
    const items = await requestWithBackoff(
      () => fetchList(1),
      '列表'
    );

    if (items.length === 0) {
      console.log('  无数据');
      return;
    }

    console.log(`  第1页 ${items.length} 条`);
    allItems = items.slice(0, count);
    console.log(`  选取前 ${allItems.length} 条\n`);
  } else {
    console.log(`[1/2] 获取 ${targetDate} 的公告列表...`);
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
        `  第 ${pageNo} 页 ✓ (已匹配 ${allItems.length} 条，本页 ${matchedThisPage}/${items.length} 条)`
      );

      // 如果本页数据不足 PAGE_SIZE 条，说明是最后一页
      if (items.length < PAGE_SIZE) foundAll = true;
      pageNo++;
    }

    console.log(`  日期筛选完成: ${allItems.length} 条匹配 ${targetDate}\n`);
  }

  if (allItems.length === 0) {
    console.log('✓ 无匹配数据');
    saveOutput([]);
    return;
  }

  // ---- 爬取详情 ----
  console.log(`[2/2] 爬取 ${allItems.length} 条公告正文...`);
  let detailOk = 0;
  let detailFail = 0;

  for (let i = 0; i < allItems.length; i++) {
    const item = allItems[i];
    process.stdout.write(`  [${i + 1}/${allItems.length}] ${item.title.substring(0, 40)}... `);

    if (i > 0) await sleep(1000 + Math.random() * 1000);

    try {
      const detail = await requestWithBackoff(
        () => fetchDetail(item.id, item.releaseDate),
        `详情${i + 1}`
      );

      const content = stripHtml(detail.content || '');
      if (content) {
        item.content = content;
        detailOk++;
        console.log(`✓ (${content.length} 字)`);
      } else {
        console.log('⚠ 未提取到正文');
        detailFail++;
      }
    } catch (e) {
      console.log(`✗ ${e.message}`);
      detailFail++;
    }
  }

  console.log(`\n  详情爬取完成: ${detailOk} 成功, ${detailFail} 失败\n`);

  // ---- 保存 ----
  console.log('[保存] 写入 JSON...');
  const output = saveOutput(allItems);
  console.log(`  ${OUTPUT_JSON}`);
  console.log(`  共 ${output.total} 条`);
  console.log('\n✓ 完成！');

  // 打印摘要
  console.log('\n--- 数据摘要 ---');
  allItems.forEach((r, i) => {
    const type = CHANNEL_TYPE_MAP[r.channelId] || '招标公告';
    const contentLen = r.content ? r.content.length : 0;
    console.log(
      `  ${i + 1}. [${type}] ${r.title.substring(0, 50)} (${(r.releaseDate || '').substring(0, 10)}) ${contentLen ? `[${contentLen}字]` : '[仅标题]'}`
    );
  });
}

main().catch((e) => {
  console.error('失败:', e.message);
  process.exit(1);
});
