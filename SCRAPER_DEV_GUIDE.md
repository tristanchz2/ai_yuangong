# 爬虫开发规范与参考 Prompt

> 本文档用于指导 LLM / 开发者为 `ai_yuangong` 项目生成新的爬虫脚本。

## 一、项目架构概览

```
ai_yuangong/
├── scrapers/              # 爬虫文件（Node.js）
│   ├── utility/
│   │   ├── stripHtml.js   # HTML → 纯文本工具
│   │   └── JsonWriter.js  # 增量 JSON 写入器
│   └── scrape_<name>.js   # 每个站点一个爬虫脚本
├── raw_data/              # 爬虫原始输出 JSON
│   └── <name>_data.json
├── extracted_data/        # LLM 提取后的结构化数据（按公告类型+日期分文件）
│   ├── 采购公告/
│   ├── 结果公告/
│   └── 其他/
├── routers/               # FastAPI 后端路由
│   ├── admin.py           # 管理员：站点管理、批量爬取
│   ├── batch_scraper.py   # 批量爬取调度（爬虫5并发 + LLM 3并发）
│   ├── scraper.py         # 爬虫自动生成（Hermes）
│   └── data.py            # 数据查询接口
├── extract_fields.py      # LLM 字段提取器
├── run_scrapers.py        # CLI 运行入口（自动发现 scrapers/scrape_*.js）
├── server.py              # FastAPI 主服务
└── sites.json             # 站点注册表（批量爬取依赖此文件）
```

**数据流水线：**
```
爬虫 (Node.js) → raw_data/<name>_data.json → LLM提取 (extract_fields.py) → extracted_data/{notice_type}/{date}.json
```

---

## 二、新爬虫接口规范

### 2.1 文件命名与位置

| 项目 | 规范 |
|------|------|
| 爬虫文件 | `scrapers/scrape_<name>.js`，`<name>` 从域名推导，小写+下划线 |
| 输出路径 | `raw_data/<name>_data.json` |
| 路径写法 | `path.join(__dirname, '..', 'raw_data', '<name>_data.json')`（**只用一层 `..`**，因为爬虫在 `scrapers/` 目录下运行） |

### 2.2 CLI 接口（必须支持）

```bash
node scrape_<name>.js --info              # 输出元数据 JSON（被 run_scrapers.py --list 和自动发现依赖）
node scrape_<name>.js --latest N          # 爬取最新 N 条
node scrape_<name>.js --yesterday         # 爬取昨天的数据
node scrape_<name>.js --date YYYY-MM-DD   # 爬取指定日期
```

`--info` 必须输出合法 JSON（被 `run_scrapers.py` 和 `batch_scraper.py` 解析）：
```json
{
  "name": "<name>",
  "description": "<网站描述>",
  "modes": ["latest", "yesterday", "date"],
  "outputFile": "raw_data/<name>_data.json"
}
```

### 2.3 输出 JSON 顶层结构

```json
{
  "source": "网站中文名称",
  "scrapeTime": "2026-07-10T15",
  "rows": [...]
}
```

- **`source`**：网站中文名，如 "工银集采"、"国开采购网"、"中国邮政"
- **`scrapeTime`**：爬虫运行时间，格式 `YYYY-MM-DDTHH`，**必须用本地时间**（`new Date()` 的本地时间），**禁止使用 `toISOString()`**（那是 UTC 时间）
- 使用 `JsonWriter` 增量写入，每爬完一条立即写磁盘

### 2.4 每条 row 必须包含的字段

| 字段 | 必填 | 类型 | 说明 |
|------|------|------|------|
| `title` | **是** | string | 公告标题 |
| `content` | **是** | string | 公告正文纯文本（用 `stripHtml()` 处理），**不能等于 title**，长度应 > 200 字 |
| `publishTime` | **是** | string | 发布时间，格式 `YYYY-MM-DD` 或 `YYYY-MM-DD HH:mm` |
| `url` | **是** | string | 公告详情页 URL |
| `noticeType` | **推荐** | string | 公告类型，如 `"采购公告"`、`"结果公告"`、`"招标公告"`、`"变更公告"` 等。如果平台 API/页面提供了类型信息，**必须保留** |

**`noticeType` 的重要性：**
- `extract_fields.py` 会优先使用 raw_data 中已有的 `noticeType`/`bidType`/`method`，映射为严格枚举（`采购公告` / `结果公告` / `其他`）
- 如果爬虫不提供，会 fallback 到 LLM 分类或标题关键词推断，但准确率较低
- 如果平台 API 返回了公告类型字段，一定要在 row 里保留

### 2.5 必须使用的工具函数

```javascript
const { stripHtml } = require('./utility/stripHtml');   // HTML → 纯文本
const { JsonWriter } = require('./utility/JsonWriter');  // 增量 JSON 写入器
```

**JsonWriter 用法：**
```javascript
const writer = new JsonWriter(OUTPUT_JSON, {
  source: '网站中文名',
  scrapeTime: formatScrapeTime()
});

// 每条爬完后立即写入（中途崩溃不丢数据）
writer.addRow({
  title: '公告标题',
  publishTime: '2026-07-09',
  url: 'https://...',
  content: '正文纯文本...',
  noticeType: '采购公告',  // 如果有
});

console.log(`✓ 共 ${writer.count} 条`);
```

### 2.6 必须实现的工程模式

| 模式 | 要求 |
|------|------|
| 限频退避 | `requestWithBackoff`：初始 delay 3-5s，指数退避，最多重试 4-6 次 |
| 请求间隔 | 每次请求之间 `sleep(1500~5000)` + 随机抖动 |
| 超时设置 | 每个请求 15-30s 超时 |
| 进度输出 | `console.log` 打印进度，如 `[1/10] 标题前40字... ✓` |
| 详情提取 | 多策略提取链：精确选择器 → 通用选择器 → 所有 `<p>` 标签 |
| 内容验证 | 提取后检查 `content.length > 200` 且 `content !== title` |

### 2.7 禁止行为

- ❌ 不使用 Playwright/puppeteer 作为爬虫运行时
- ❌ 不使用外部 npm 包（只用 Node.js 内置 `http`/`https` + 项目工具函数；特殊情况如 `cycletls` 除外）
- ❌ 不跳过详情页爬取（content 不能只有标题）
- ❌ 不使用 `toISOString()` 生成 scrapeTime
- ❌ OUTPUT_JSON 路径不多余嵌套 `..`

---

## 三、添加新爬虫的完整步骤

### 第 1 步：创建爬虫文件
创建 `scrapers/scrape_<name>.js`，按上述规范编写代码。

### 第 2 步：测试爬虫
```bash
# 1. 验证 --info 输出
node scrapers/scrape_<name>.js --info

# 2. 单条测试
node scrapers/scrape_<name>.js --latest 1

# 3. 检查 content 质量
python3 -c "
import json
with open('raw_data/<name>_data.json') as f:
    data = json.load(f)
row = data['rows'][0]
print(f'Title: {row[\"title\"][:60]}')
print(f'Content length: {len(row[\"content\"])} chars')
print('PASS' if len(row['content']) > 200 and row['content'].strip() != row['title'].strip() else 'FAIL')
"

# 4. 批量测试
node scrapers/scrape_<name>.js --latest 3

# 5. 测试日期模式
node scrapers/scrape_<name>.js --yesterday
```

### 第 3 步：注册到 sites.json
在 `sites.json` 的 `sites` 数组中添加：
```json
{
  "id": 12,
  "name": "网站中文名",
  "url": "https://example.com/",
  "scraper_name": "<name>",
  "description": "网站描述",
  "status": "active",
  "hidden": false
}
```
- `id`：当前最大 id + 1
- `scraper_name`：必须和爬虫文件名一致（`scrape_<scraper_name>.js`）
- `hidden: false` 才会在批量爬取中被执行

### 第 4 步：验证 LLM 提取流水线
```bash
python3 extract_fields.py --source <name>
```
检查 `extracted_data/` 下是否生成了对应文件。

### 第 5 步：清理残留（如果是替换旧爬虫）
- 删除旧的 `scrapers/scrape_<旧name>.js`
- 删除 `raw_data/<旧name>_data.json`
- `extracted_data/` 下旧源数据会被新数据覆盖

---

## 四、Few-Shot 示例

### 示例 1：POST JSON API 模式（工商银行 ICBC）

**适用场景：** 目标网站有 JSON API，POST 请求，支持分页和日期筛选。

```javascript
/**
 * 工商银行工银集采 (ICBC) 招标公告爬虫
 *
 * 数据来源: https://jc.icbc.com.cn/#/announcementList/2
 *
 * Usage:
 *   node scrape_icbc.js --yesterday
 *   node scrape_icbc.js --latest 5
 *   node scrape_icbc.js --date 2026-07-05
 */

const https = require('https');
const fs = require('fs');
const path = require('path');
const { stripHtml } = require('./utility/stripHtml');
const { JsonWriter } = require('./utility/JsonWriter');

const OUTPUT_JSON = path.join(__dirname, '..', 'raw_data', 'icbc_data.json');
const HOSTNAME = 'jc.icbc.com.cn';
const API_PATH = '/app/queryPortalNoticeInfoPage';

// ===================== 请求层 =====================
function apiRequest(body) {
  const payload = JSON.stringify(body);
  return new Promise((resolve, reject) => {
    const req = https.request({
      hostname: HOSTNAME, port: 443, path: API_PATH, method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(payload),
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        Referer: `https://${HOSTNAME}/`,
        Origin: `https://${HOSTNAME}`,
      },
    }, (res) => {
      let data = '';
      res.on('data', (c) => (data += c));
      res.on('end', () => {
        if (res.statusCode !== 200) { reject(new Error(`HTTP ${res.statusCode}`)); return; }
        try { resolve(JSON.parse(data)); }
        catch (e) { reject(new Error(`JSON parse error`)); }
      });
    });
    req.on('error', reject);
    req.setTimeout(15000, () => { req.destroy(); reject(new Error('timeout')); });
    req.write(payload);
    req.end();
  });
}

// ===================== 限频退避 =====================
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function requestWithBackoff(requestFn, label) {
  let delay = 5000;
  const MAX_ATTEMPTS = 6;
  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
    try { return await requestFn(); }
    catch (e) {
      if (attempt < MAX_ATTEMPTS) {
        console.log(`    ⚠ ${e.message}，等待 ${delay / 1000}s...`);
        await sleep(delay);
        delay = Math.min(delay * 2, 120000);
      } else { throw e; }
    }
  }
}

// ===================== API 封装 =====================
function fetchList(curPage, pageSize = 10, beginDate = '', endDate = '') {
  return apiRequest({
    menuId: 'MENU030000000', projType: '', noticeStatus: '2',
    curPage, pageSize, branchIds: [], struSign: '', beginDate, endDate,
  });
}

function fetchDetail(noticeId) {
  return new Promise((resolve, reject) => {
    const req = https.request({
      hostname: HOSTNAME, port: 443,
      path: `/app/api/notice/detail/${encodeURIComponent(noticeId)}`,
      method: 'GET',
      headers: { 'User-Agent': '...', Referer: `https://${HOSTNAME}/` },
    }, (res) => { /* ... */ });
    // ...
  });
}

// ===================== 日期工具 =====================
function formatDate(d) {
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}
function getYesterday() { const d = new Date(); d.setDate(d.getDate() - 1); return formatDate(d); }
function formatScrapeTime() {
  const d = new Date(); const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}`;
}

// ===================== 主流程 =====================
async function main() {
  const args = process.argv.slice(2);

  // --info 元数据
  if (args.includes('--info')) {
    console.log(JSON.stringify({
      name: 'icbc',
      description: '工商银行工银集采 (ICBC) 招标公告爬虫',
      modes: ['latest', 'yesterday', 'date'],
      outputFile: 'raw_data/icbc_data.json',
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

  let allItems = [];

  if (mode === 'latest') {
    const result = await requestWithBackoff(() => fetchList(1, Math.max(count, 10)), '列表');
    allItems = (result.rows || []).slice(0, count);
  } else {
    const result = await requestWithBackoff(() => fetchList(1, 100, targetDate, targetDate), '日期筛选');
    allItems = result.rows || [];
    // 翻页处理（如果超过 100 条）
    if (result.totalNum > 100) {
      for (let page = 2; page <= result.totalPage; page++) {
        await sleep(1500);
        const pageResult = await requestWithBackoff(() => fetchList(page, 100, targetDate, targetDate), `第${page}页`);
        if (!pageResult?.rows?.length) break;
        allItems = allItems.concat(pageResult.rows);
      }
    }
  }

  if (allItems.length === 0) {
    new JsonWriter(OUTPUT_JSON, { source: '工银集采', scrapeTime: formatScrapeTime() });
    return;
  }

  // 初始化增量写入器
  const writer = new JsonWriter(OUTPUT_JSON, { source: '工银集采', scrapeTime: formatScrapeTime() });

  // 逐条爬取详情
  for (let i = 0; i < allItems.length; i++) {
    const item = allItems[i];
    if (i > 0) await sleep(1500);

    try {
      const detail = await requestWithBackoff(() => fetchDetail(item.noticeId), `详情${i + 1}`);
      if (detail) { item._content = detail.noticeText || ''; }
    } catch (e) { item._content = ''; }

    // ★ 每条爬完后立即写入
    writer.addRow({
      publishTime: item.issueDate,       // 发布时间
      title: item.noticeTitle,            // 标题
      url: `https://jc.icbc.com.cn/#/notice_detailInfo/${item.noticeId}`,  // 详情页 URL
      content: stripHtml(item._content),  // 正文纯文本
      // noticeType: 如果API返回了类型字段，务必加上
    });

    console.log(`    [${i + 1}/${allItems.length}] ${item.noticeTitle.substring(0, 40)}... ${item._content ? '✓' : '✗'}`);
  }

  console.log(`\n✓ icbc (${writer.count}/${writer.count})`);
}

main().catch((e) => { console.error('失败:', e.message); process.exit(1); });
```

**要点：**
- POST JSON API + 分页参数（`curPage`, `pageSize`）
- 日期筛选用 `beginDate`/`endDate`
- 先爬列表，再逐条爬详情（两阶段）
- `noticeId` 构造详情页 URL

---

### 示例 2：HTML 解析模式（国家开发银行 CDB）

**适用场景：** 目标网站没有 API，需要解析 HTML 页面，列表页+详情页结构。

```javascript
/**
 * 国家开发银行采购网 (CDB) 结果公告爬虫
 *
 * Usage:
 *   node scrape_cdb.js --yesterday
 *   node scrape_cdb.js --latest 5
 *   node scrape_cdb.js --date 2026-07-06
 */

const https = require('https');
const fs = require('fs');
const path = require('path');
const { stripHtml } = require('./utility/stripHtml');
const { JsonWriter } = require('./utility/JsonWriter');

const OUTPUT_JSON = path.join(__dirname, '..', 'raw_data', 'cdb_data.json');
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
      if (res.statusCode !== 200) { reject(new Error(`HTTP ${res.statusCode}`)); res.resume(); return; }
      let data = '';
      res.setEncoding('utf8');
      res.on('data', c => data += c);
      res.on('end', () => resolve(data));
    }).on('error', reject);
  });
}

// ===================== 列表页解析 =====================
function parseListPage(html) {
  const items = [];
  // 正则匹配列表项：<a href="..."><div class="tit">标题</div><div class="date">日期</div></a>
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
      items.push({ url: SITE_BASE + href, title, date: date.substring(0, 10).replace(/\//g, '-') });
    }
  }
  return items;
}

// ===================== 详情页解析（多策略提取链） =====================
function parseDetailPage(html) {
  let content = '';

  // 策略 1: 精确选择器 <div class="Content">
  const contentMatch = html.match(/<div\s+class="Content"[^>]*>([\s\S]*?)(?=<\/div>\s*<\/div>\s*<!--)/);
  if (contentMatch) {
    content = stripHtml(contentMatch[1]);
  }

  // 策略 2: 提取所有 <p> 标签
  if (!content || content.length < 200) {
    const paragraphs = [];
    const pMatches = html.match(/<p[^>]*>([\s\S]*?)<\/p>/gi) || [];
    for (const p of pMatches) {
      const text = stripHtml(p).trim();
      if (text.length > 20) paragraphs.push(text);
    }
    if (paragraphs.length > 0) content = paragraphs.join('\n\n');
  }

  // 验证内容长度
  if (content.length < 200) {
    console.warn('    ⚠ 提取的内容过短，可能提取失败');
  }

  return content;
}

// ===================== 日期工具 =====================
function formatDate(d) { /* ... */ }
function getYesterday() { /* ... */ }
function formatScrapeTime() { /* 用本地时间 */ }

// ===================== 主流程 =====================
async function main() {
  const args = process.argv.slice(2);

  if (args.includes('--info')) {
    console.log(JSON.stringify({
      name: 'cdb',
      description: '国家开发银行采购网 (CDB) 结果公告爬虫',
      modes: ['latest', 'yesterday', 'date'],
      outputFile: 'raw_data/cdb_data.json',
    }));
    return;
  }

  // ... 参数解析同上 ...

  // 初始化增量写入器
  const writer = new JsonWriter(OUTPUT_JSON, { source: '国开采购网', scrapeTime: formatScrapeTime() });

  // 逐条爬取详情
  for (let i = 0; i < allItems.length; i++) {
    const item = allItems[i];
    if (i > 0) await sleep(1500 + Math.random() * 1000);

    const html = await requestWithBackoff(() => httpGet(item.url), `详情${i + 1}`);
    const content = parseDetailPage(html);

    writer.addRow({
      title: item.title,
      noticeType: '结果公告',             // ★ CDB 只有结果公告，固定值
      publishTime: item.date,             // 发布时间
      url: item.url,                      // 详情页 URL
      content: content || item.title,     // 正文
    });
  }

  console.log(`\n✓ cdb (${writer.count}/${writer.count})`);
}

main().catch((e) => { console.error('失败:', e.message); process.exit(1); });
```

**要点：**
- 纯 HTML 解析，用正则提取列表项和详情正文
- **多策略提取链**：先精确选择器，再 fallback 到 `<p>` 标签
- `noticeType: '结果公告'` —— CDB 只爬结果公告，用固定值
- 日期从列表页或详情页中提取

---

### 示例 3：HTML 列表页翻页 + 日期过滤（中国邮政 ChinaPost）

**适用场景：** 目标网站是静态 HTML 列表页，需要翻页查找，按日期过滤。

```javascript
/**
 * 中国邮政集团有限公司招标公告爬虫
 *
 * Usage:
 *   node scrape_chinapost.js --latest 5
 *   node scrape_chinapost.js --yesterday
 */

const https = require('https');
const zlib = require('zlib');
const path = require('path');
const { stripHtml } = require('./utility/stripHtml');
const { JsonWriter } = require('./utility/JsonWriter');

const OUTPUT_JSON = path.join(__dirname, '..', 'raw_data', 'chinapost_data.json');

// ===================== HTTP 请求（支持 gzip 解压） =====================
function request(url, options = {}) {
  return new Promise((resolve, reject) => {
    const req = https.get(url, {
      headers: {
        'User-Agent': 'Mozilla/5.0 ...',
        'Accept-Encoding': 'gzip, deflate',  // 支持压缩
        ...options.headers
      },
      timeout: 30000
    }, (res) => {
      if ([301, 302, 307, 308].includes(res.statusCode)) {
        return resolve(request(res.headers.location, options));  // 自动跟踪重定向
      }
      const chunks = [];
      let stream = res;
      const encoding = res.headers['content-encoding'];
      if (encoding === 'gzip') stream = res.pipe(zlib.createGunzip());
      else if (encoding === 'deflate') stream = res.pipe(zlib.createInflate());
      stream.on('data', chunk => chunks.push(chunk));
      stream.on('end', () => resolve(Buffer.concat(chunks).toString('utf-8')));
    });
    req.on('error', reject);
    req.setTimeout(30000, () => { req.destroy(); reject(new Error('timeout')); });
  });
}

// ===================== 列表页解析 =====================
function parseListPage(html) {
  const items = [];
  const listMatch = html.match(/<div class="new_list">[\s\S]*?<ul>([\s\S]*?)<\/ul>/);
  if (!listMatch) return items;
  const liRegex = /<li>[\s\S]*?<a href=([^ >]+)[^>]*>([\s\S]*?)<\/a>[\s\S]*?<span id=ReportIDIssueTime>(\d{4}-\d{2}-\d{2})<\/span>/g;
  let match;
  while ((match = liRegex.exec(listMatch[1])) !== null) {
    items.push({ detailUrl: match[1], title: match[2].trim(), date: match[3] });
  }
  return items;
}

// ===================== 详情页解析（多策略） =====================
function parseDetailPage(html) {
  let content = '';
  // 策略1: 精确选择器
  const m = html.match(/<span id=ReportIDtext>([\s\S]*?)<\/span>/);
  if (m) content = stripHtml(m[1]);
  // 策略2: 所有 <p> 标签
  if (!content || content.length < 200) {
    const paragraphs = [];
    (html.match(/<p[^>]*>([\s\S]*?)<\/p>/gi) || []).forEach(p => {
      const text = stripHtml(p).trim();
      if (text.length > 20) paragraphs.push(text);
    });
    if (paragraphs.length > 0) content = paragraphs.join('\n\n');
  }
  if (content.length < 200) console.warn('    ⚠ 内容过短');
  return content;
}

// ===================== 主流程 =====================
async function main() {
  const args = process.argv.slice(2);
  if (args.includes('--info')) {
    console.log(JSON.stringify({ name: 'chinapost', description: '中国邮政招标公告', modes: ['latest', 'yesterday'], outputFile: 'raw_data/chinapost_data.json' }));
    return;
  }

  // ... 参数解析 ...

  const writer = new JsonWriter(OUTPUT_JSON, { source: '中国邮政', scrapeTime: formatScrapeTime() });

  // 翻页爬取列表
  let items = [], page = 1;
  while (items.length < count && page <= 10) {
    const url = `https://www.chinapost.com.cn/cn/category/1813/137338-${page}.htm`;
    const html = await requestWithBackoff(() => request(url), `列表页${page}`);
    const listItems = parseListPage(html);
    if (listItems.length === 0) break;

    if (targetDate) {
      items.push(...listItems.filter(item => item.date === targetDate));
      if (listItems[listItems.length - 1].date < targetDate) break;  // 已超过目标日期
    } else {
      items.push(...listItems);
    }
    page++;
    await sleep(2000 + Math.random() * 3000);
  }
  if (!targetDate) items = items.slice(0, count);

  // 逐条爬取详情
  for (let i = 0; i < items.length; i++) {
    const item = items[i];
    const detailUrl = `https://www.chinapost.com.cn${item.detailUrl}`;
    const html = await requestWithBackoff(() => request(detailUrl), `详情${i + 1}`);
    const content = parseDetailPage(html);

    writer.addRow({
      title: item.title,
      publishTime: item.date,
      url: detailUrl,
      content: content,
    });
  }
}

main().catch((e) => { console.error('失败:', e.message); process.exit(1); });
```

**要点：**
- 支持 gzip/deflate 解压 + 自动重定向跟踪
- 翻页 URL 模式：`137338-{page}.htm`
- 日期过滤：翻到目标日期之前的数据就停止翻页
- 详情页 URL 需要拼接域名前缀

---

### 示例 4：cycletls TLS 指纹绕过 WAF（农银e采 ABC_PUC）

**适用场景：** 目标网站有 WAF（JA3 指纹检测），需要 `cycletls` 模拟浏览器 TLS 指纹。

```javascript
/**
 * 农银e采 (ABC PUC) 招标公告爬虫
 *
 * 使用 cycletls 模拟 Chrome TLS 指纹，绕过 WAF 的 JA3 检测。
 * 依赖：npm install cycletls
 */

const initCycleTLS = require('cycletls');
const path = require('path');
const { stripHtml } = require('./utility/stripHtml');
const { JsonWriter } = require('./utility/JsonWriter');

const OUTPUT_JSON = path.join(__dirname, '..', 'raw_data', 'abc_puc_data.json');

// Chrome TLS 指纹 (JA3)
const JA3 = '771,4865-4866-4867-49195-49199-49196-49200-52393-52392-49171-49172-156-157-47-53,...';
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) ...';

async function apiRequest(cycleTLS, apiPath, reqBody) {
  const resp = await cycleTLS(`https://jc.abchina.com.cn${apiPath}`, {
    body: JSON.stringify(reqBody),
    headers: { 'Content-Type': 'application/json', Referer: '...', Origin: '...' },
    ja3: JA3,
    userAgent: UA,
    timeout: 15,
  }, 'post');
  return JSON.parse(resp.body);
}

// 主流程中使用 noticeType
// ★ 平台 API 返回了 MESSAGE_TYPE，映射为中文公告类型
const MESSAGE_TYPE_MAP = {
  '1': '招标(资审)公告',
  '2': '变更公告',
  '3': '结果公告',
};

// ... 爬取逻辑 ...

writer.addRow({
  title: item.title,
  noticeType: MESSAGE_TYPE_MAP[item.messageType] || '其他',  // ★ 保留平台原始类型
  publishTime: item.publishDate,
  url: `https://jc.abchina.com.cn/puc/#/notice/detail/${item.id}`,
  content: stripHtml(item.content),
});
```

**要点：**
- 需要 `cycletls` 额外依赖（`npm install cycletls`）
- `ja3` 指纹 + `userAgent` 模拟 Chrome
- **noticeType 映射**：平台返回数字码，用 MAP 映射为中文类型名

---

## 五、常见问题 Checklist

| 问题 | 解决方案 |
|------|----------|
| OUTPUT_JSON 路径 ENOENT | 检查是否多了一层 `..`，正确写法：`path.join(__dirname, '..', 'raw_data', ...)` |
| scrapeTime 时间不对 | 用 `new Date()` 本地时间，不要用 `toISOString()`（UTC） |
| content 等于 title | 详情页解析失败，需要用 curl 检查真实 HTML 结构，调整选择器 |
| content 过短 (<200字) | 实现多策略提取链，fallback 到 `<p>` 标签提取 |
| noticeType 丢失 | 如果平台 API/HTML 中有类型信息，务必保留在 row 中 |
| 被 WAF 拦截 | 考虑使用 `cycletls` 模拟 TLS 指纹 |
| 日期过滤不生效 | 检查 API 是否支持日期参数，不支持则在客户端过滤 |
