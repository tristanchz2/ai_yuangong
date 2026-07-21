/**
 * 中国民生银行 (CMBC) 采购公告爬虫
 * 爬取采购公告列表和详情（含附件提取）
 *
 * Usage:
 *   node scrape_cmbc.js --info             # 输出元数据 JSON
 *   node scrape_cmbc.js --latest 5         # 爬取最新 N 条
 *   node scrape_cmbc.js --yesterday        # 爬取昨天数据
 *   node scrape_cmbc.js --date YYYY-MM-DD  # 爬取指定日期
 */

const https = require('https');
const fs = require('fs');
const path = require('path');
const { stripHtml } = require('./utility/stripHtml');
const { JsonWriter } = require('./utility/JsonWriter');

// ★ 路径只用一层 ..，因为爬虫在 scrapers/ 下运行
const OUTPUT_JSON = path.join(__dirname, '..', 'raw_data', 'cmbc_data.json');

// ===================== API 配置 =====================
const BASE_API = 'https://pms.cmbc.com.cn/purchase/api';
const CATEGORY_ID = '0205DC9E86F4C12C256094C8F271049D0289539534AEC561D051E4BB132055B0C181EF712D2717E0BCECBCF31010137B';

// ===================== HTTP 请求 =====================
function httpGet(url, timeout = 20000) {
  return new Promise((resolve, reject) => {
    const req = https.get(url, { timeout }, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(data);
        } else {
          reject(new Error(`HTTP ${res.statusCode}: ${url}`));
        }
      });
    });
    req.on('error', reject);
    req.on('timeout', () => {
      req.destroy();
      reject(new Error(`Timeout: ${url}`));
    });
  });
}

function downloadFile(url, destPath, timeout = 60000) {
  return new Promise((resolve, reject) => {
    const req = https.get(url, { timeout }, (res) => {
      if (res.statusCode >= 300) {
        reject(new Error(`HTTP ${res.statusCode}: ${url}`));
        return;
      }
      const fileStream = fs.createWriteStream(destPath);
      res.pipe(fileStream);
      fileStream.on('finish', () => {
        fileStream.close();
        resolve(destPath);
      });
      fileStream.on('error', (err) => {
        fs.unlink(destPath, () => {});
        reject(err);
      });
    });
    req.on('error', reject);
    req.on('timeout', () => {
      req.destroy();
      reject(new Error(`Timeout downloading: ${url}`));
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
      if (data && data.message && data.message.includes('频繁')) {
        if (attempt < MAX_ATTEMPTS) {
          console.log(`    ⚠ 限频 → 等待 ${delay/1000}s`);
          await sleep(delay);
          delay = Math.min(delay * 2, MAX_DELAY);
          continue;
        }
      }
      return data;
    } catch (e) {
      if (attempt < MAX_ATTEMPTS) {
        console.log(`    ⚠ ${e.message}，等待 ${delay/1000}s...`);
        await sleep(delay);
        delay = Math.min(delay * 2, MAX_DELAY);
      } else {
        console.log(`    ✗ ${label}: 失败`);
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
  const d = new Date(); d.setDate(d.getDate() - 1); return formatDate(d);
}
function formatScrapeTime() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}`;
}

// ===================== 附件下载和内容提取 =====================
const { execSync } = require('child_process');
const os = require('os');

async function downloadAndExtractAttachments(attachmentUrls) {
  const contents = [];
  
  for (const att of attachmentUrls) {
    console.log(`    📎 下载附件: ${att.attName}`);
    
    const ext = path.extname(att.attName).toLowerCase() || '.docx';
    const tempFile = path.join(os.tmpdir(), `att_${Date.now()}_${Math.random().toString(36).slice(2)}${ext}`);
    
    try {
      await downloadFile(att.atturl, tempFile);
      
      const extractorScript = path.join(__dirname, 'utility', 'extract_attachment.py');
      const extractedText = execSync(
        `python3 "${extractorScript}" "${tempFile}"`,
        { encoding: 'utf-8', maxBuffer: 50 * 1024 * 1024 }
      );
      
      if (extractedText.trim().length > 0) {
        contents.push({
          filename: att.attName,
          text: extractedText.trim()
        });
        console.log(`      ✓ 提取 ${extractedText.trim().length} 字`);
      } else {
        console.log(`      ⚠ 附件内容为空`);
      }
    } catch (e) {
      console.log(`      ⚠ 附件提取失败: ${e.message}`);
    } finally {
      try { fs.unlinkSync(tempFile); } catch (e) {}
    }
  }
  
  return contents;
}

// ===================== 获取列表数据 =====================
async function fetchList(pageNo, pageSize) {
  const url = `${BASE_API}/getNewsListMore?pageno=${pageNo}&rowsize=${pageSize}&categoryId=${CATEGORY_ID}`;
  const responseText = await requestWithBackoff(() => httpGet(url), `获取列表第${pageNo}页`);
  if (!responseText) return null;
  
  try {
    return JSON.parse(responseText);
  } catch (e) {
    console.error(`  ✗ JSON 解析失败: ${e.message}`);
    return null;
  }
}

// ===================== 获取详情数据（含附件） =====================
async function fetchDetail(fdId) {
  const url = `${BASE_API}/getNewsDetails?fdId=${fdId}`;
  const responseText = await requestWithBackoff(() => httpGet(url), `获取详情${fdId.substring(0, 8)}...`);
  if (!responseText) return null;
  
  try {
    return JSON.parse(responseText);
  } catch (e) {
    console.error(`  ✗ JSON 解析失败: ${e.message}`);
    return null;
  }
}

// ===================== 主流程 =====================
async function main() {
  const args = process.argv.slice(2);

  if (args.includes('--info')) {
    console.log(JSON.stringify({
      name: 'cmbc',
      description: '中国民生银行采购公告',
      modes: ['latest', 'yesterday', 'date'],
      outputFile: 'raw_data/cmbc_data.json',
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

  const writer = new JsonWriter(OUTPUT_JSON, { source: '中国民生银行', scrapeTime: formatScrapeTime() });

  console.log(`🚀 开始爬取中国民生银行 (${mode}模式)...`);

  // 1. 获取列表数据（列表 API 已包含 fdContent）
  const PAGE_SIZE = 10;
  const MAX_PAGES = 20;
  let allItems = [];
  let pageNo = 1;
  let hasMore = true;

  while (hasMore && pageNo <= MAX_PAGES) {
    console.log(`\n📄 获取第 ${pageNo} 页...`);
    const result = await fetchList(pageNo, PAGE_SIZE);
    
    if (!result || !result.data || result.data.length === 0) {
      console.log(`  ⚠ 没有更多数据`);
      break;
    }

    const items = result.data;
    console.log(`  ✓ 获取 ${items.length} 条记录`);

    // 日期过滤（客户端二次验证）
    if (mode === 'date' && targetDate) {
      const matchedItems = items.filter(item => {
        const itemDate = (item.createTime || '').substring(0, 10);
        return itemDate === targetDate;
      });
      
      console.log(`  📅 其中 ${matchedItems.length} 条是 ${targetDate} 的`);
      allItems.push(...matchedItems);

      // 提前终止：如果当前页最后一条记录的日期比目标日期早，停止翻页
      const lastDate = (items[items.length - 1].createTime || '').substring(0, 10);
      if (lastDate && lastDate < targetDate) {
        console.log(`  ✓ 当前页最早数据 ${lastDate} 早于目标日期 ${targetDate}，停止翻页`);
        break;
      }
    } else {
      allItems.push(...items);
      
      // 数量限制
      if (mode === 'latest' && allItems.length >= count) {
        allItems = allItems.slice(0, count);
        hasMore = false;
        break;
      }
    }

    // 检查是否有下一页
    if (items.length < PAGE_SIZE || pageNo >= parseInt(result.pageTotal || '1')) {
      hasMore = false;
    } else {
      pageNo++;
      await sleep(2000 + Math.random() * 1000);
    }
  }

  console.log(`\n📋 找到 ${allItems.length} 条记录，开始处理详情...`);

  // 2. 处理每条记录（列表 API 已有 content，只需获取附件）
  for (let i = 0; i < allItems.length; i++) {
    const item = allItems[i];
    console.log(`\n[${i + 1}/${allItems.length}] ${item.docSubject.substring(0, 40)}...`);

    try {
      // 从列表 API 提取正文
      let content = stripHtml(item.fdContent || '');
      
      if (!content || content.length < 200) {
        console.log(`    ⚠ 列表内容过短 (${content.length} 字符)，尝试获取详情...`);
        const detail = await fetchDetail(item.fdId);
        if (detail && detail.fdContent) {
          content = stripHtml(detail.fdContent);
        }
      }

      // 获取详情（检查附件）
      const detail = await fetchDetail(item.fdId);
      let attachments = [];
      
      if (detail && detail.attUrl && detail.attUrl.length > 0) {
        console.log(`    📎 发现 ${detail.attUrl.length} 个附件`);
        attachments = await downloadAndExtractAttachments(detail.attUrl);
        
        // 将附件内容拼接到正文
        if (attachments.length > 0) {
          const attachmentText = attachments.map(att => 
            `\n\n---附件: ${att.filename}---\n${att.text}`
          ).join('');
          content += attachmentText;
        }
      }

      if (!content || content.length < 200) {
        console.log(`    ⚠ 最终内容过短 (${content.length} 字符)`);
      }

      // 构建详情页 URL
      const detailUrl = `https://pms.cmbc.com.cn/purchase/details.html?fdId=${item.fdId}`;

      writer.addRow({
        title: item.docSubject || '',
        content: content || item.docSubject || '',
        publishTime: item.createTime || '',
        url: detailUrl,
        noticeType: '', // API 未提供类型信息
        dept: item.dept || '',
        readCount: item.readCount || 0,
      });

      console.log(`    ✓ 内容 ${content.length} 字`);

      // 请求间隔
      if (i < allItems.length - 1) {
        await sleep(2000 + Math.random() * 1000);
      }
    } catch (e) {
      console.log(`    ✗ 处理失败: ${e.message}`);
      // 即使失败，也记录基本信息
      writer.addRow({
        title: item.docSubject || '',
        content: item.docSubject || '',
        publishTime: item.createTime || '',
        url: `https://pms.cmbc.com.cn/purchase/details.html?fdId=${item.fdId}`,
        noticeType: '',
        dept: item.dept || '',
        readCount: item.readCount || 0,
      });
    }
  }

  console.log(`\n✅ 爬取完成，共 ${writer.count} 条记录`);
  console.log(`📁 输出文件: ${OUTPUT_JSON}`);
}

main().catch((e) => { 
  console.error('失败:', e.message); 
  process.exit(1); 
});
