/**
 * 中国邮政集团有限公司招标公告爬虫
 * 爬取网址：https://www.chinapost.com.cn/cn/category/1813/137338-1.htm
 * 
 * Usage:
 *   node scrape_chinapost.js --info           # 查看爬虫信息
 *   node scrape_chinapost.js --latest 5       # 爬取最新5条
 *   node scrape_chinapost.js --yesterday      # 爬取昨天的公告
 */

const https = require('https');
const zlib = require('zlib');
const fs = require('fs');
const path = require('path');
const { stripHtml } = require('./utility/stripHtml');
const { JsonWriter } = require('./utility/JsonWriter');

const OUTPUT_JSON = path.join(__dirname, '..', '..', 'raw_data', 'chinapost_data.json');

// ===================== HTTP 请求 =====================
function request(url, options = {}) {
  return new Promise((resolve, reject) => {
    const req = https.get(url, {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate',
        ...options.headers
      },
      timeout: 30000
    }, (res) => {
      // 处理重定向
      if ([301, 302, 307, 308].includes(res.statusCode)) {
        return resolve(request(res.headers.location, options));
      }

      const chunks = [];
      let stream = res;

      // 根据编码解压
      const encoding = res.headers['content-encoding'];
      if (encoding === 'gzip') {
        stream = res.pipe(zlib.createGunzip());
      } else if (encoding === 'deflate') {
        stream = res.pipe(zlib.createInflate());
      }

      stream.on('data', chunk => chunks.push(chunk));
      stream.on('end', () => {
        const data = Buffer.concat(chunks).toString('utf-8');
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(data);
        } else {
          reject(new Error(`HTTP ${res.statusCode}`));
        }
      });
      stream.on('error', reject);
    });
    req.on('error', reject);
    req.on('timeout', () => {
      req.destroy();
      reject(new Error('Request timeout'));
    });
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
  const d = new Date();
  d.setDate(d.getDate() - 1);
  return formatDate(d);
}

// ===================== 列表页解析 =====================
function parseListPage(html) {
  const items = [];
  
  // 提取所有列表项
  const listMatch = html.match(/<div class="new_list">[\s\S]*?<ul>([\s\S]*?)<\/ul>[\s\S]*?<\/div>/);
  if (!listMatch) return items;
  
  const listHtml = listMatch[1];
  const liRegex = /<li>[\s\S]*?<span id=ReportIDname><a href=([^ >]+)[^>]*>([\s\S]*?)<\/a><\/span>[\s\S]*?<span id=ReportIDIssueTime>(\d{4}-\d{2}-\d{2})<\/span>[\s\S]*?<\/li>/g;
  
  let match;
  while ((match = liRegex.exec(listHtml)) !== null) {
    items.push({
      detailUrl: match[1],
      title: match[2].trim(),
      date: match[3]
    });
  }
  
  return items;
}

// ===================== 详情页解析 =====================
function parseDetailPage(html) {
  let content = '';
  
  // 策略1: 提取 #ReportIDtext 里的内容
  const contentMatch = html.match(/<span id=ReportIDtext>([\s\S]*?)<\/span>/);
  if (contentMatch) {
    content = stripHtml(contentMatch[1]);
  }
  
  // 策略2: 如果策略1失败，提取所有 <p> 标签
  if (!content || content.length < 200) {
    const paragraphs = [];
    const pMatches = html.match(/<p[^>]*>([\s\S]*?)<\/p>/gi) || [];
    for (const p of pMatches) {
      const text = stripHtml(p).trim();
      if (text.length > 20) {
        paragraphs.push(text);
      }
    }
    if (paragraphs.length > 0) {
      content = paragraphs.join('\n\n');
    }
  }
  
  // 验证内容长度
  if (content.length < 200) {
    console.warn('    ⚠ 提取的内容过短，可能提取失败');
  }
  
  return content;
}

// ===================== 主流程 =====================
async function main() {
  const args = process.argv.slice(2);

  if (args.includes('--info')) {
    console.log(JSON.stringify({
      name: 'chinapost',
      description: '中国邮政集团有限公司招标公告',
      modes: ['latest', 'yesterday'],
      outputFile: 'raw_data/chinapost_data.json',
    }, null, 2));
    return;
  }

  // 参数解析
  let mode = 'latest', count = 5, targetDate = null;
  const yesterdayIdx = args.indexOf('--yesterday');
  const latestIdx = args.indexOf('--latest');
  
  if (yesterdayIdx >= 0) {
    mode = 'date';
    targetDate = getYesterday();
  } else if (latestIdx >= 0) {
    count = parseInt(args[latestIdx + 1]) || 5;
  }

  console.log(`\n🚀 开始爬取中国邮政招标公告 (模式: ${mode})`);

  const writer = new JsonWriter(OUTPUT_JSON, {
    source: 'chinapost',
    scrapeTime: new Date().toISOString()
  });

  let items = [];
  let page = 1;
  const maxPages = 10; // 最多爬10页（200条）

  // 爬取列表页
  while (items.length < count && page <= maxPages) {
    console.log(`\n📄 爬取列表页 ${page}...`);
    
    const url = `https://www.chinapost.com.cn/cn/category/1813/137338-${page}.htm`;
    const html = await requestWithBackoff(() => request(url), `列表页${page}`);
    const listItems = parseListPage(html);
    
    if (listItems.length === 0) {
      console.log('    没有更多数据');
      break;
    }
    
    // 如果是按日期筛选
    if (targetDate) {
      const filtered = listItems.filter(item => item.date === targetDate);
      items.push(...filtered);
      
      // 如果当前页最早的日期早于目标日期，停止
      const lastDate = listItems[listItems.length - 1].date;
      if (lastDate < targetDate) {
        console.log('    已到达目标日期范围');
        break;
      }
    } else {
      items.push(...listItems);
    }
    
    page++;
    await sleep(2000 + Math.random() * 3000);
  }

  // 截取需要的数量
  if (!targetDate) {
    items = items.slice(0, count);
  }

  console.log(`\n✓ 找到 ${items.length} 条公告`);

  // 爬取详情页
  for (let i = 0; i < items.length; i++) {
    const item = items[i];
    console.log(`\n[${i + 1}/${items.length}] ${item.title}`);
    console.log(`    日期: ${item.date}`);
    
    const detailUrl = `https://www.chinapost.com.cn${item.detailUrl}`;
    
    try {
      const html = await requestWithBackoff(() => request(detailUrl), `详情页${i + 1}`);
      const content = parseDetailPage(html);
      
      const record = {
        id: item.detailUrl.match(/\/(\d+)-1\.htm/)[1],
        title: item.title,
        date: item.date,
        url: detailUrl,
        content: content,
        scraped_at: new Date().toISOString()
      };
      
      writer.addRow(record);
      console.log(`    ✓ 已保存 (内容长度: ${content.length} 字符)`);
      
    } catch (e) {
      console.error(`    ✗ 失败: ${e.message}`);
    }
    
    if (i < items.length - 1) {
      await sleep(2000 + Math.random() * 3000);
    }
  }

  console.log(`\n✅ 完成！共 ${writer.count} 条数据已保存到 ${OUTPUT_JSON}`);
}

main().catch((e) => {
  console.error('\n❌ 失败:', e.message);
  process.exit(1);
});
