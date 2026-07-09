/**
 * 中国政府采购网 (ccgp.gov.cn) 金融相关标书爬虫
 *
 * Usage:
 *   node scrape_ccgp.js --list 1                    # 搜索1页，取最新结果
 *   node scrape_ccgp.js --list all                   # 搜索全部页
 *   node scrape_ccgp.js --list 1 --limit 5           # 搜索1页，只保留最新5条
 *   node scrape_ccgp.js --yesterday                  # 昨天数据
 *   node scrape_ccgp.js --begin-date 2026-07-01 --end-date 2026-07-06
 *   node scrape_ccgp.js resume                       # 断点续爬
 */

const http = require('http');
const https = require('https');
const fs = require('fs');
const path = require('path');
const { URL } = require('url');
const { stripHtml } = require('./utility/stripHtml');
const { JsonWriter } = require('./utility/JsonWriter');

// ===================== 配置 =====================

const OUTPUT_JSON = path.join(__dirname, '..', '..', 'raw_data', 'ccgp_data.json');

// 搜索关键词
const FINANCE_KEYWORDS = ['银行', '保险', '证券'];

const REQUEST_DELAY = 8000;
const DETAIL_DELAY = 10000;

const sleep = (ms) => new Promise(r => setTimeout(r, ms));

// ===================== HTTP 请求 =====================

function fetchUrl(url, maxRetries = 3) {
  return new Promise((resolve, reject) => {
    const parsed = new URL(url);
    const lib = parsed.protocol === 'https:' ? https : http;

    const attempt = (retry) => {
      const req = lib.get(url, {
        headers: {
          'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
          'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
          'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
          'Accept-Encoding': 'identity',
        },
        timeout: 20000,
      }, (res) => {
        if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
          return fetchUrl(new URL(res.headers.location, url).href, maxRetries).then(resolve).catch(reject);
        }
        let data = '';
        res.setEncoding('utf8');
        res.on('data', c => data += c);
        res.on('end', () => {
          if (data.includes('频繁访问') || (data.includes('频繁') && data.includes('事件ID'))) {
            if (retry < maxRetries) {
              const wait = (retry + 1) * 30000;
              console.log(`    ⚠ 频繁访问限制，等待 ${wait / 1000}s... (${retry + 1}/${maxRetries})`);
              setTimeout(() => attempt(retry + 1), wait);
            } else {
              reject(new Error('频繁访问 - 已重试 ' + maxRetries + ' 次'));
            }
          } else {
            resolve({ status: res.statusCode, data, headers: res.headers });
          }
        });
      });
      req.on('error', (e) => {
        if (retry < maxRetries) setTimeout(() => attempt(retry + 1), 5000);
        else reject(e);
      });
      req.setTimeout(20000, () => { req.destroy(); reject(new Error('timeout')); });
    };
    attempt(0);
  });
}

// ===================== 搜索页 =====================

function buildSearchUrl(keyword, page, startTime, endTime) {
  const params = new URLSearchParams({
    searchtype: '1', page_index: String(page), bidSort: '0',
    buyerName: '', projectId: '', pinMu: '0', bidType: '0',
    dbselect: 'bidx', kw: keyword,
    start_time: startTime ? startTime.replace(/-/g, ':') : '',
    end_time: endTime ? endTime.replace(/-/g, ':') : '',
    timeType: '6', displayZone: '', zoneId: '', pppStatus: '0', agentName: '',
  });
  return `http://search.ccgp.gov.cn/bxsearch?${params.toString()}`;
}

function parseSearchResults(html) {
  const results = [];
  const ulMatch = html.match(/<ul class="vT-srch-result-list-bid">([\s\S]*?)<\/ul>/);
  if (!ulMatch) return results;

  const items = ulMatch[1].match(/<li>([\s\S]*?)<\/li>/g) || [];
  for (const item of items) {
    const titleMatch = item.match(/<a[^>]*href="([^"]+)"[^>]*>([\s\S]*?)<\/a>/);
    if (!titleMatch) continue;

    const url = titleMatch[1];
    const title = titleMatch[2].replace(/<[^>]+>/g, '').trim();

    const previewMatch = item.match(/<p>([\s\S]*?)<\/p>/);
    const preview = previewMatch ? previewMatch[1].replace(/<[^>]+>/g, '').trim() : '';

    const spanMatch = item.match(/<span>([\s\S]*?)<\/span>/);
    let date = '', purchaser = '', agent = '', bidType = '', region = '', category = '';
    if (spanMatch) {
      const span = spanMatch[1];
      const dateM = span.match(/(\d{4}\.\d{2}\.\d{2}\s+\d{2}:\d{2}:\d{2})/);
      date = dateM ? dateM[1] : '';
      const purchM = span.match(/采购人：([^|<]+)/);
      purchaser = purchM ? purchM[1].trim() : '';
      const agentM = span.match(/代理机构：([^|<]+)/);
      agent = agentM ? agentM[1].trim() : '';
      const strongs = span.match(/<strong[^>]*>([\s\S]*?)<\/strong>/g) || [];
      if (strongs[0]) bidType = strongs[0].replace(/<[^>]+>/g, '').trim();
      if (strongs[1]) category = strongs[1].replace(/<[^>]+>/g, '').trim();
      const regionM = span.match(/<br\/>\s*<strong[^>]*>[\s\S]*?<\/strong>\s*\|\s*([^|<]+)\s*\|/);
      region = regionM ? regionM[1].trim() : '';
    }

    results.push({ url, title, preview, date, purchaser, agent, bidType, region, category });
  }
  return results;
}

function getPageCount(html) {
  const m = html.match(/Pager\(\{[\s\S]*?size:\s*(\d+)/);
  return m ? parseInt(m[1]) : 1;
}

// ===================== 详情页 =====================

function parseDetailPage(html) {
  let content = '';
  const contentMatch = html.match(/<div[^>]*class="[^"]*vF_detail_content[^"]*"[^>]*>([\s\S]*?)<\/div>/);
  if (contentMatch) {
    content = contentMatch[1].replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
  } else {
    const bodyMatch = html.match(/<div[^>]*class="[^"]*content[^"]*"[^>]*>([\s\S]*?)<\/div>/);
    if (bodyMatch) content = bodyMatch[1].replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
  }
  return { content };
}

// ===================== 项目去重 =====================

function extractProjectName(title) {
  return title
    .replace(/[-—\s]*(公开招标|竞争性磋商|竞争性谈判|询价|单一来源|资格预审|邀请|中标|成交|更正|其他|终止|废标|变更|结果)?[（(]?公告[）)]?$/g, '')
    .replace(/[-—\s]*(采购包\d+).*$/g, '')
    .replace(/\(第[一二三四五六七八九十\d]+次\)/g, '')
    .replace(/（第[一二三四五六七八九十\d]+次）/g, '')
    .trim();
}

function similarity(a, b) {
  if (!a || !b) return 0;
  const shorter = a.length < b.length ? a : b;
  const longer = a.length < b.length ? b : a;
  if (shorter.length === 0) return 0;
  let matches = 0;
  for (let i = 0; i < shorter.length; i++) {
    if (longer.includes(shorter.substring(i, i + 2))) matches++;
  }
  return matches / shorter.length;
}

function deduplicateByProject(entries) {
  const groups = [];
  const assigned = new Set();
  for (let i = 0; i < entries.length; i++) {
    if (assigned.has(i)) continue;
    const nameI = extractProjectName(entries[i].title);
    const group = [i];
    assigned.add(i);
    for (let j = i + 1; j < entries.length; j++) {
      if (assigned.has(j)) continue;
      const nameJ = extractProjectName(entries[j].title);
      if (nameI.length > 5 && similarity(nameI, nameJ) > 0.85) {
        group.push(j);
        assigned.add(j);
      }
    }
    groups.push(group);
  }
  const result = [];
  for (const group of groups) {
    const sorted = group
      .map(idx => ({ idx, entry: entries[idx] }))
      .sort((a, b) => (b.entry.date || '').localeCompare(a.entry.date || ''));
    const primary = sorted[0].entry;
    result.push(primary);
  }
  return result;
}

// ===================== 主流程 =====================

async function main() {
  // 解析参数 (与 scrape_cfcpn.js 风格一致)
  const args = process.argv.slice(2);

  // ---- --info: 输出元数据 JSON ----
  if (args.includes('--info')) {
    console.log(JSON.stringify({
      name: 'ccgp',
      description: '中国政府采购网 (ccgp.gov.cn) 金融相关标书爬虫',
      modes: ['latest', 'yesterday'],
      outputFile: 'raw_data/ccgp_data.json',
    }));
    return;
  }

  // ---- 标准接口参数转换 ----
  const latestIdx = args.indexOf('--latest');
  const isYesterday = args.includes('--yesterday');

  if (latestIdx >= 0) {
    // --latest N → 转换为 --list 1 --limit N
    const n = parseInt(args[latestIdx + 1]) || 5;
    if (!args.includes('--list')) { args.push('--list', '1'); }
    if (!args.includes('--limit')) { args.push('--limit', String(n)); }
  } else if (!args.includes('resume') && !args.includes('--list') && !isYesterday && !args.includes('--begin-date')) {
    // 默认行为: --latest 5
    args.push('--list', '1', '--limit', '5');
  }

  const isResume = args.includes('resume');

  const listIdx = args.indexOf('--list');
  const listPages = listIdx >= 0 ? args[listIdx + 1] : null;

  const beginIdx = args.indexOf('--begin-date');
  const endIdx = args.indexOf('--end-date');
  const limitIdx = args.indexOf('--limit');
  const isYesterdayArg = args.includes('--yesterday');

  let dateBegin = '', dateEnd = '';
  let limit = null;

  if (isYesterdayArg) {
    const d = new Date();
    d.setDate(d.getDate() - 1);
    dateBegin = d.toISOString().substring(0, 10);
    dateEnd = dateBegin;
  }
  if (beginIdx >= 0) dateBegin = args[beginIdx + 1] || '';
  if (endIdx >= 0) dateEnd = args[endIdx + 1] || '';
  if (limitIdx >= 0) limit = parseInt(args[limitIdx + 1]) || null;

  // --list 模式不指定日期时，默认近30天
  if (listPages && !dateBegin && !dateEnd && !isYesterdayArg) {
    const now = new Date();
    const ago = new Date(now.getTime() - 30 * 86400000);
    dateEnd = now.toISOString().substring(0, 10);
    dateBegin = ago.toISOString().substring(0, 10);
  }

  const maxPages = listPages === 'all' ? 99999 : (listPages ? parseInt(listPages) || 1 : 1);

  // ---- Phase 1: 搜索 ----
  console.log(`  [列表] 关键词: ${FINANCE_KEYWORDS.join(', ')}`);
  let allEntries = [];
  let processedUrls = new Set();
  let startKeywordIdx = 0;

  if (isResume) {
    try {
      const existing = JSON.parse(fs.readFileSync(OUTPUT_JSON, 'utf8'));
      if (existing.rows?.length) {
        allEntries = existing.rows;
        processedUrls = new Set(allEntries.map(e => e.url));
        console.log(`♻ 续爬: ${allEntries.length} 条已处理\n`);
      }
    } catch {}
  }

  for (let ki = startKeywordIdx; ki < FINANCE_KEYWORDS.length; ki++) {
    const keyword = FINANCE_KEYWORDS[ki];
    console.log(`  搜索: "${keyword}" (${ki + 1}/${FINANCE_KEYWORDS.length})`);
    if (ki > 0) await sleep(REQUEST_DELAY);

    let pageHtml;
    try {
      const resp = await fetchUrl(buildSearchUrl(keyword, 1, dateBegin, dateEnd));
      pageHtml = resp.data;
    } catch (e) {
      console.log(`    ⚠ 搜索失败: ${e.message}`);
      continue;
    }

    const pageCount = Math.min(getPageCount(pageHtml), maxPages);
    const pageResults = parseSearchResults(pageHtml);
    let newCount = 0;

    for (const r of pageResults) {
      if (!processedUrls.has(r.url)) {
        processedUrls.add(r.url);
        r.searchKeyword = keyword;
        allEntries.push(r);
        newCount++;
      }
    }
    console.log(`    第1页: ${pageResults.length}条, ${newCount}条新增`);

    if (limit && allEntries.length >= limit) {
      console.log(`    已达 ${limit} 条上限\n`);
      break;
    }

    for (let page = 2; page <= pageCount; page++) {
      await sleep(REQUEST_DELAY);
      try {
        const resp = await fetchUrl(buildSearchUrl(keyword, page, dateBegin, dateEnd));
        const results = parseSearchResults(resp.data);
        let pNew = 0;
        for (const r of results) {
          if (!processedUrls.has(r.url)) {
            processedUrls.add(r.url);
            r.searchKeyword = keyword;
            allEntries.push(r);
            pNew++;
          }
        }
        console.log(`    第${page}页: ${results.length}条, ${pNew}条新增`);
        if (limit && allEntries.length >= limit) break;
      } catch (e) {
        console.log(`    ⚠ 第${page}页失败: ${e.message}`);
      }
    }

    if (limit && allEntries.length >= limit) break;
  }

  // 按日期排序，如果有限制则截断
  allEntries.sort((a, b) => (b.date || '').localeCompare(a.date || ''));
  if (limit) allEntries = allEntries.slice(0, limit);

  console.log(`    共 ${allEntries.length} 条`);

  if (allEntries.length === 0) {
    console.log('  ✓ 该日期范围内无数据');
    new JsonWriter(OUTPUT_JSON, { source: '中国政府采购网', scrapeTime: new Date().toISOString() });
    return;
  }

  // ---- 初始化增量写入器 ----
  const writer = new JsonWriter(OUTPUT_JSON, {
    source: '中国政府采购网',
    scrapeTime: new Date().toISOString(),
  });
  for (const e of allEntries) {
    writer.addRow({
      title: stripHtml(e.title),
      url: e.url,
      date: e.date,
      purchaser: e.purchaser,
      agent: e.agent,
      bidType: e.bidType,
      region: e.region,
      category: e.category,
      content: '',
    });
  }

  // ---- Phase 2: 详情页（仅爬正文） ----
  console.log(`  [详情] ${writer.count} 条`);

  for (let i = 0; i < writer.count; i++) {
    const entry = writer.rows[i];
    if (entry.content) continue;
    if (i > 0) await sleep(DETAIL_DELAY);

    try {
      const resp = await fetchUrl(entry.url);
      const detail = parseDetailPage(resp.data);
      const content = stripHtml(detail.content).substring(0, 5000);
      console.log(`    [${i + 1}/${writer.count}] ${entry.title.substring(0, 40)}... ✓`);
      writer.setRow(i, { ...entry, content });
    } catch (e) {
      console.log(`    [${i + 1}/${writer.count}] ${entry.title.substring(0, 40)}... ✗ ${e.message}`);
    }
  }

  // ---- 去重 + 最终写入 ----
  const rawEntries = writer.rows.map((r, i) => ({
    ...allEntries[i],
    content: r.content || allEntries[i]?.content || '',
  }));
  const deduped = deduplicateByProject(rawEntries);

  const finalWriter = new JsonWriter(OUTPUT_JSON, {
    source: '中国政府采购网',
    scrapeTime: new Date().toISOString(),
  });
  for (const e of deduped) {
    finalWriter.addRow({
      title: stripHtml(e.title),
      url: e.url,
      date: e.date,
      purchaser: e.purchaser,
      agent: e.agent,
      bidType: e.bidType,
      region: e.region,
      category: e.category,
      content: stripHtml(e.content || ''),
    });
  }
  console.log(`\n✓ ccgp (${finalWriter.count}/${finalWriter.count})`);
}

main().catch(e => { console.error('失败:', e.message); process.exit(1); });
