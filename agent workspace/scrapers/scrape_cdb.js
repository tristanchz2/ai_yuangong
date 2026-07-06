/**
 * 国家开发银行采购网 (CDB) 结果公告爬虫
 *
 * Usage:
 *   node scrape_cdb.js --yesterday        # 爬取昨天发布的公告
 *   node scrape_cdb.js --latest 5         # 爬取最新 N 条公告（默认5条）
 *   node scrape_cdb.js --date 2026-07-06  # 爬取指定日期的公告
 */

const https = require('https');
const fs = require('fs');
const path = require('path');

const OUTPUT_JSON = path.join(__dirname, '..', '..', 'row_data', 'cdb_data.json');
const SITE_BASE = 'https://cg.cdb.com.cn';
const LIST_BASE = `${SITE_BASE}/cmsjieguo`;

// ===================== HTTP 请求 =====================

function httpGet(url) {
  return new Promise((resolve, reject) => {
    https.get(url, {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        Accept: 'text/html,application/xhtml+xml',
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
      res.on('end', () => resolve(data));
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

/**
 * 解析列表页，返回 [{url, title, date}]
 */
function parseListPage(html) {
  const items = [];
  // 匹配: <a href="/cmsjieguo/xxx.html"> ... <div class="tit">title</div> <div class="date">date</div> </a>
  const re = /<a\s+href="(\/cmsjieguo\/[^"]+)"[^>]*>([\s\S]*?)<\/a>/g;
  let m;
  while ((m = re.exec(html)) !== null) {
    const href = m[1];
    const inner = m[2];
    const titleMatch = inner.match(/<div\s+class="tit"[^>]*>([\s\S]*?)<\/div>/);
    const dateMatch = inner.match(/<div\s+class="date"[^>]*>([\s\S]*?)<\/div>/);
    const title = titleMatch ? titleMatch[1].replace(/<[^>]+>/g, '').trim() : '';
    const date = dateMatch ? dateMatch[1].replace(/<[^>]+>/g, '').trim() : '';
    if (title) {
      items.push({
        url: SITE_BASE + href,
        title,
        date: date.substring(0, 10).replace(/\//g, '-'),
      });
    }
  }
  return items;
}

/**
 * 解析详情页，提取纯文本正文
 */
function parseDetailPage(html) {
  // 提取 <div class="Content" ...> 中的内容
  const contentMatch = html.match(/<div\s+class="Content"[^>]*>([\s\S]*?)(?=<\/div>\s*<\/div>\s*<!--|<div\s+class="prev_next")/);
  if (!contentMatch) {
    // 备选：查找 <div class="Content" 到对应的 </div>
    const startIdx = html.indexOf('class="Content"');
    if (startIdx < 0) return '';
    const bodyStart = html.indexOf('>', startIdx) + 1;
    // 简单找到匹配的 </div>（不够精确但大多数情况够用）
    let depth = 1;
    let pos = bodyStart;
    while (depth > 0 && pos < html.length) {
      const nextOpen = html.indexOf('<div', pos);
      const nextClose = html.indexOf('</div>', pos);
      if (nextClose < 0) break;
      if (nextOpen >= 0 && nextOpen < nextClose) {
        depth++;
        pos = nextOpen + 4;
      } else {
        depth--;
        if (depth === 0) {
          return stripHtml(html.substring(bodyStart, nextClose));
        }
        pos = nextClose + 6;
      }
    }
    return '';
  }
  return stripHtml(contentMatch[1]);
}

/**
 * 从详情页提取发布时间
 */
function parseDetailDate(html) {
  const m = html.match(/发布时间[：:]\s*(\d{4}\/\d{2}\/\d{2})/);
  return m ? m[1].replace(/\//g, '-') : '';
}

// ===================== 保存输出 =====================

function saveOutput(rows) {
  const jsonOutput = {
    scrapeTime: new Date().toISOString(),
    total: rows.length,
    rows: rows.map((r) => ({
      publishTime: r.publishTime || r.date || '',
      noticeType: '结果公告',
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
    // ---- 爬取最新 N 条 ----
    console.log('[1/2] 获取公告列表...');
    const html = await requestWithBackoff(
      () => httpGet(`${LIST_BASE}/index.html`),
      '列表'
    );

    const items = parseListPage(html);
    if (items.length === 0) {
      console.log('  无数据');
      return;
    }

    console.log(`  本页 ${items.length} 条`);
    allItems = items.slice(0, count);
    console.log(`  选取前 ${allItems.length} 条\n`);
  } else {
    // ---- 按日期爬取 ----
    console.log(`[1/2] 获取 ${targetDate} 的公告列表...`);
    let pageNo = 1;
    let foundAll = false;

    while (!foundAll) {
      const pageUrl = pageNo === 1
        ? `${LIST_BASE}/index.html`
        : `${LIST_BASE}/index_${pageNo}.html`;

      await sleep(1500);
      const html = await requestWithBackoff(
        () => httpGet(pageUrl),
        `列表第${pageNo}页`
      );

      const items = parseListPage(html);
      if (items.length === 0) {
        if (pageNo === 1) console.log('  无数据');
        break;
      }

      let matchedThisPage = 0;
      for (const item of items) {
        if (item.date === targetDate) {
          allItems.push(item);
          matchedThisPage++;
        } else if (item.date < targetDate) {
          foundAll = true;
          break;
        }
      }

      console.log(
        `  第 ${pageNo} 页 ✓ (已匹配 ${allItems.length} 条，本页 ${matchedThisPage}/${items.length} 条)`
      );

      if (pageNo >= 142) foundAll = true; // 最大页数
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

    if (i > 0) await sleep(1500 + Math.random() * 1000);

    try {
      const html = await requestWithBackoff(
        () => httpGet(item.url),
        `详情${i + 1}`
      );

      const content = parseDetailPage(html);
      const date = parseDetailDate(html);
      if (content) {
        item.content = content;
        if (date) item.publishTime = date;
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
    const contentLen = r.content ? r.content.length : 0;
    console.log(
      `  ${i + 1}. ${r.title.substring(0, 50)} (${r.date || '未知时间'}) ${contentLen ? `[${contentLen}字]` : '[仅标题]'}`
    );
  });
}

main().catch((e) => {
  console.error('失败:', e.message);
  process.exit(1);
});
