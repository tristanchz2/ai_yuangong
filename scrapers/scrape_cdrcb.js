/**
 * 成都农商银行 (cdrcb) 项目招采公告爬虫
 *
 * Usage:
 *   node scrape_cdrcb.js --info             # 输出元数据 JSON
 *   node scrape_cdrcb.js --latest 5         # 爬取最新 N 条
 *   node scrape_cdrcb.js --yesterday        # 爬取昨天数据
 *   node scrape_cdrcb.js --date YYYY-MM-DD  # 爬取指定日期
 *
 * 注意：该网站多数公告内容以图片形式发布，content 字段会存储图片 URL 列表。
 */

const https = require('https');
const fs = require('fs');
const path = require('path');
const { stripHtml } = require('./utility/stripHtml');
const { JsonWriter } = require('./utility/JsonWriter');

// ★ 路径只用一层 ..，因为爬虫在 scrapers/ 下运行
const OUTPUT_JSON = path.join(__dirname, '..', 'raw_data', 'cdrcb_data.json');

const BASE_URL = 'https://www.cdrcb.com';

// ===================== HTTP 请求 =====================
function httpsRequest(options, body = null) {
  return new Promise((resolve, reject) => {
    const req = https.request(options, (res) => {
      const chunks = [];
      res.on('data', (chunk) => chunks.push(chunk));
      res.on('end', () => {
        const data = Buffer.concat(chunks).toString('utf8');
        if (res.statusCode >= 400) {
          reject(new Error(`HTTP ${res.statusCode}: ${data.substring(0, 200)}`));
        } else {
          resolve(data);
        }
      });
    });
    req.on('error', reject);
    req.setTimeout(30000, () => {
      req.destroy();
      reject(new Error('请求超时'));
    });
    if (body) req.write(body);
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
      const data = await requestFn();
      return data;
    } catch (e) {
      if (attempt < MAX_ATTEMPTS) {
        console.log(`    ⚠ ${e.message}，等待 ${delay/1000}s...`);
        await sleep(delay);
        delay = Math.min(delay * 2, MAX_DELAY);
      } else {
        console.log(`    ✗ ${label}: 失败 - ${e.message}`);
        return null;
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
  const d = new Date();
  d.setDate(d.getDate() - 1);
  return formatDate(d);
}

function formatScrapeTime() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}`;
}

// ===================== 列表 API =====================
async function fetchList(page, num) {
  const options = {
    hostname: 'www.cdrcb.com',
    path: '/cgnews/dt.htm',
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
      'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
      'Referer': 'https://www.cdrcb.com/cgnews/',
      'Origin': 'https://www.cdrcb.com',
    },
  };
  const body = `tp=5&page=${page}&num=${num}`;

  const result = await requestWithBackoff(
    () => httpsRequest(options, body),
    `列表第${page}页`
  );

  if (!result) return null;

  try {
    return JSON.parse(result);
  } catch (e) {
    console.error(`    ✗ JSON 解析失败: ${e.message}`);
    return null;
  }
}

// ===================== 详情页解析 =====================
async function fetchDetail(id) {
  const options = {
    hostname: 'www.cdrcb.com',
    path: `/cgnews/cgnewsdetail.htm?id=${id}`,
    method: 'GET',
    headers: {
      'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
      'Referer': 'https://www.cdrcb.com/cgnews/',
    },
  };

  const html = await requestWithBackoff(
    () => httpsRequest(options),
    `详情 id=${id}`
  );

  if (!html) return null;

  // 提取标题
  const titleMatch = html.match(/<div class="cost_title">([\s\S]*?)<\/div>/i);
  const title = titleMatch ? stripHtml(titleMatch[1]).trim() : '';

  // 提取发布时间（从 lcbz0 的 tm 属性）
  const timeMatch = html.match(/class="lcbz0"[^>]*tm="(\d{4}-\d{2}-\d{2})"/i);
  const publishTime = timeMatch ? timeMatch[1] : '';

  // 提取公告类型（从 lcbz0 的 span 文本）
  const typeMatch = html.match(/class="lcbz0"[^>]*>[\s\S]*?<span>([^<]+)<\/span>/i);
  const noticeType = typeMatch ? typeMatch[1].trim() : '';

  // 提取内容（图片或文字）
  const contentMatch = html.match(/id="ncontid"[^>]*>([\s\S]*?)<\/div>/i);
  let content = '';
  let contentHtml = '';

  if (contentMatch) {
    contentHtml = contentMatch[1];

    // 提取图片 URL
    const imgUrls = [];
    const imgRegex = /<img[^>]*src="([^"]+)"/gi;
    let imgMatch;
    while ((imgMatch = imgRegex.exec(contentHtml)) !== null) {
      let url = imgMatch[1];
      if (url.startsWith('..')) {
        url = BASE_URL + url.substring(2);
      } else if (url.startsWith('/')) {
        url = BASE_URL + url;
      } else if (!url.startsWith('http')) {
        url = BASE_URL + '/' + url;
      }
      imgUrls.push(url);
    }

    // 提取附件链接
    const attachmentUrls = [];
    const linkRegex = /<a[^>]*href="([^"]+)"[^>]*>([^<]*)<\/a>/gi;
    let linkMatch;
    while ((linkMatch = linkRegex.exec(contentHtml)) !== null) {
      const href = linkMatch[1];
      const text = stripHtml(linkMatch[2]).trim();
      if (href.match(/\.(docx?|pdf|xlsx?|pptx?|zip|rar)$/i)) {
        let url = href;
        if (url.startsWith('..')) {
          url = BASE_URL + url.substring(2);
        } else if (url.startsWith('/')) {
          url = BASE_URL + url;
        } else if (!url.startsWith('http')) {
          url = BASE_URL + '/' + url;
        }
        attachmentUrls.push({ url, text });
      }
    }

    // 提取文字内容
    const textContent = stripHtml(contentHtml).trim();

    // 构建 content
    if (imgUrls.length > 0) {
      content = `[公告内容以图片形式发布]\n`;
      imgUrls.forEach((url, i) => {
        content += `图片${i + 1}: ${url}\n`;
      });
    }

    if (attachmentUrls.length > 0) {
      if (content) content += '\n';
      content += `[附件下载]\n`;
      attachmentUrls.forEach((att, i) => {
        content += `附件${i + 1}: ${att.text || '下载'} - ${att.url}\n`;
      });
    }

    if (textContent && textContent.length > 20) {
      if (content) content += '\n[正文内容]\n';
      content += textContent;
    }
  }

  if (!content || content.trim().length < 10) {
    content = '[公告内容详见详情页]';
  }

  return {
    title,
    content: content.trim(),
    publishTime,
    noticeType,
  };
}

// ===================== 主流程 =====================
async function main() {
  const args = process.argv.slice(2);

  if (args.includes('--info')) {
    console.log(JSON.stringify({
      name: 'cdrcb',
      description: '成都农商银行项目招采公告（采购/招标/中标/变更等）',
      modes: ['latest', 'yesterday', 'date'],
      outputFile: 'raw_data/cdrcb_data.json',
    }));
    return;
  }

  // 参数解析
  let mode = 'latest', count = 5, targetDate = null;
  const yesterdayIdx = args.indexOf('--yesterday');
  const latestIdx = args.indexOf('--latest');
  const dateIdx = args.indexOf('--date');

  if (yesterdayIdx >= 0) {
    mode = 'date';
    targetDate = getYesterday();
  } else if (dateIdx >= 0) {
    mode = 'date';
    targetDate = args[dateIdx + 1];
  } else if (latestIdx >= 0) {
    count = parseInt(args[latestIdx + 1]) || 5;
  }

  const scrapeTime = formatScrapeTime();
  const writer = new JsonWriter(OUTPUT_JSON, { source: 'cdrcb', scrapeTime });

  console.log(`开始爬取成都农商银行项目招采公告 (${mode === 'date' ? targetDate : `最新${count}条`})`);
  console.log(`输出文件: ${OUTPUT_JSON}\n`);

  // 1. 获取列表数据
  const pageSize = 20;
  let page = 1;
  const allItems = [];

  while (true) {
    console.log(`获取列表第 ${page} 页...`);
    const listData = await fetchList(page, pageSize);

    if (!listData || !listData.ns || listData.ns.length === 0) {
      console.log('  无更多数据');
      break;
    }

    console.log(`  第 ${page} 页: ${listData.ns.length} 条`);

    for (const item of listData.ns) {
      allItems.push(item);

      // --latest 模式：达到数量后停止
      if (mode === 'latest' && allItems.length >= count) {
        break;
      }

      // --date 模式：日期过滤
      if (mode === 'date') {
        const itemDate = (item.stime || '').substring(0, 10);
        if (itemDate < targetDate) {
          console.log(`  ✓ 数据 ${itemDate} 早于目标日期 ${targetDate}，停止翻页`);
          break;
        }
      }
    }

    // 停止条件
    if (mode === 'latest' && allItems.length >= count) break;
    if (mode === 'date') {
      const lastDate = (listData.ns[listData.ns.length - 1].stime || '').substring(0, 10);
      if (lastDate && lastDate < targetDate) break;
    }
    if (page >= listData.totalPage) break;

    page++;
    await sleep(2000 + Math.random() * 1000);
  }

  // 客户端日期过滤
  let targetItems = allItems;
  if (mode === 'date') {
    targetItems = allItems.filter(item => {
      const itemDate = (item.stime || '').substring(0, 10);
      return itemDate === targetDate;
    });
    console.log(`\n日期过滤: ${allItems.length} → ${targetItems.length} 条 (${targetDate})\n`);
  } else if (mode === 'latest') {
    targetItems = allItems.slice(0, count);
  }

  if (targetItems.length === 0) {
    console.log('未找到符合条件的公告');
    return;
  }

  console.log(`准备爬取 ${targetItems.length} 条公告详情\n`);

  // 2. 爬取详情
  for (let i = 0; i < targetItems.length; i++) {
    const item = targetItems[i];
    console.log(`[${i + 1}/${targetItems.length}] ${item.title.substring(0, 40)}...`);

    const detail = await fetchDetail(item.d);

    if (detail) {
      const row = {
        title: detail.title || item.title,
        content: detail.content,
        publishTime: detail.publishTime || item.stime,
        url: `${BASE_URL}/cgnews/cgnewsdetail.htm?id=${item.d}`,
        noticeType: detail.noticeType || '',
      };

      writer.addRow(row);

      const contentLen = row.content.length;
      const hasImage = row.content.includes('[公告内容以图片形式发布]');
      console.log(`  ✓ 完成 (content: ${contentLen} 字符${hasImage ? ', 图片形式' : ''})`);
    } else {
      console.log(`  ✗ 详情获取失败`);
    }

    // 请求间隔
    if (i < targetItems.length - 1) {
      await sleep(2000 + Math.random() * 2000);
    }
  }

  console.log(`\n✅ 爬取完成，共 ${writer.count} 条记录`);
  console.log(`输出文件: ${OUTPUT_JSON}`);
}

main().catch((e) => {
  console.error('失败:', e.message);
  process.exit(1);
});
