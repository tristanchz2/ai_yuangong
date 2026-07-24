---
name: gen-scraper
description: "URL → 全自动爬虫生成。Hermes 用浏览器探索网站，生成代码，测试，修复。不问问题。"
version: 5.2.0
---

# URL → 全自动爬虫生成

用户发一个 URL，Hermes 全自动完成：浏览器探索 → 代码生成 → 测试 → 修复 → 注册。
**全程不问用户任何问题。所有决策预设。**

**🚨 严格限制：本 skill 只生成 HTTP/HTTPS 爬虫。绝对禁止使用 Playwright 或任何浏览器自动化。**
如果 HTTP 方案失败，明确报告"HTTP 方案不可行"，退出让 gen-scraper-browser（第二层）处理。

## 两层架构说明

- **第一层（gen-scraper，本 skill）**：只做 HTTP 方案
  - API 请求、HTML 解析、加密响应解密、TLS 指纹
  - 必须尝试所有 HTTP 手段后才能判定失败
- **第二层（gen-scraper-browser）**：Chrome CDP 方案
  - 真实浏览器 + 远程调试端口
  - 处理瑞数 WAF、需要执行 JS 挑战等场景

## 触发条件

用户发了一个 URL 并说"帮我爬"/"生成爬虫"之类的话。

**可能附带参考详情页 URL：**
- 用户可能说："帮我爬 https://xxx.com，参考这几个页面：https://xxx.com/detail/123, https://xxx.com/detail/456"
- 或者前端表单里有"参考 URL"输入框，用户填了多个详情页链接
- **重要**：参考 URL 是**同一目标网站的多个详情页**，用于学习该网站的页面结构和选择器，**不是**多个不同网站
- 如果提供了参考 URL，在 Phase 0 先学习这些页面的结构

## 项目架构（必须遵守）

项目于 2026-07-22 完成模块化重构，按职责分层：

```
ai_yuangong/
├── config/                # 配置层
│   ├── settings.py        # 环境变量、路径常量（PROJECT_ROOT, SCRAPERS_DIR 等）
│   └── constants.py       # 静态常量（批次大小、请求间隔等）
├── core/                  # 核心基础设施
│   ├── database.py        # 数据库连接池
│   ├── schema.py          # 建表迁移
│   └── utils.py           # 通用工具（字段映射、类型推断、noticeType 规范化）
├── models/                # 数据模型
│   └── schemas.py         # Pydantic 模型（GenerateRequest, ExtractedFields 等）
├── services/              # 业务服务层（核心逻辑所在）
│   ├── scraper_generator.py  # Hermes 爬虫生成逻辑（调用 hermes chat -q）
│   ├── batch_task.py      # 批量任务模型与管理
│   ├── llm_extractor.py   # LLM 字段提取核心逻辑（从 raw_data 到 extracted_data）
│   ├── site_repo.py       # 站点表 CRUD
│   ├── bid_repo.py        # 标书主表 CRUD
│   └── ...                # region.py, subscription.py, province_index.py 等
├── scripts/               # CLI 脚本（实际逻辑所在）
│   ├── run_scrapers.py    # 爬虫批量运行入口
│   ├── extract_fields.py  # LLM 字段提取 CLI 入口
│   └── excel_parser.py    # Excel 解析器
├── routers/               # FastAPI 薄路由（委托 services 处理业务）
│   ├── scraper.py         # 爬虫生成路由（调用 services/scraper_generator.py）
│   ├── admin.py           # 管理员路由（含批量爬取调度）
│   └── data.py            # 数据查询路由
├── scrapers/              # 爬虫文件（Node.js）← 你生成的爬虫放这里
│   ├── utility/
│   │   ├── stripHtml.js   # HTML → 纯文本工具
│   │   └── JsonWriter.js  # 增量 JSON 写入器
│   └── scrape_<name>.js   # 每个站点一个爬虫脚本
├── raw_data/              # 爬虫原始输出 JSON ← 你的数据输出到这里
│   └── <name>_data.json
├── extracted_data/        # LLM 提取后的结构化数据（按公告类型+日期分文件）
│   ├── 采购公告/
│   ├── 结果公告/
│   └── 其他/
├── server.py              # FastAPI 主服务入口
├── run_scrapers.py        # 兼容 shim → scripts/run_scrapers.py
└── extract_fields.py      # 兼容 shim → scripts/extract_fields.py
```

**数据流水线：**
```
爬虫 (Node.js) → raw_data/<name>_data.json → LLM提取 (services/llm_extractor.py) → extracted_data/{notice_type}/{date}.json
```

**注意：** 根目录的 `run_scrapers.py` 和 `extract_fields.py` 现在只是兼容 shim，实际逻辑分别在 `scripts/run_scrapers.py` 和 `scripts/extract_fields.py`。你只需要关心 `scrapers/` 和 `raw_data/` 目录。

## 预设决策（不需要问用户）

| 决策项 | 预设值 |
|--------|--------|
| 爬虫语言 | Node.js（只用内置 http/https 模块，禁止 Playwright） |
| 输出格式 | JSON，增量写入 |
| CLI 接口 | `--info` / `--latest N` / `--yesterday` / `--date YYYY-MM-DD` |
| 工具函数 | `stripHtml` + `JsonWriter`（项目已有） |
| 爬虫名称 | 从域名推导 |
| 爬虫文件路径 | `scrapers/scrape_<name>.js` |
| 数据输出路径 | `raw_data/<name>_data.json` |
| 错误处理 | `requestWithBackoff`（限频退避） |
| 请求间隔 | 2-5 秒 |

### HTTP 方案失败判定标准

**本 skill 只做 HTTP 方案。** 必须深入尝试以下所有手段，全部失败后才能退出：

1. **不同 User-Agent**（Chrome/Firefox/Safari/Mobile）
2. **完整 Header 组合**：
   - Referer（从目标网站首页）
   - Origin
   - X-Requested-With: XMLHttpRequest
   - Accept/Accept-Language/Accept-Encoding
3. **Cookie 模拟**：先请求首页获取 Cookie，再请求 API
4. **TLS 指纹**：使用 cycletls 绕过 TLS 检测
5. **Content-Type 切换**：application/json vs application/x-www-form-urlencoded
6. **HTTP 方法**：GET/POST 互换
7. **URL 变体**：检查是否有 /api/、/v1/、/rest/ 等前缀

**只有以上全部试过仍失败，才能判定 HTTP 方案不可行。**

**常见陷阱：**
- API 返回 403 → 不一定是反爬，可能只是缺少 Referer
- 页面返回空 HTML → 可能是 SPA，但底层 API 仍可用
- 需要 JS 渲染 → 优先找 API，不要直接放弃
- API 返回加密数据（AES/DES） → 仍然可以用 HTTP 方案解密！参考 scrape_spdb.js

**🚨 页面观察陷阱（必须读）：**

很多网站（特别是银行采购平台）**同一个页面既有登录框又有公开数据**。不要看到登录框就判定"需要登录"。先观察 10 秒：
- 页面左侧有公告列表 + 右侧有登录框 → 公告是公开的，底层 API 可直接请求
- 页面空白或被遮挡 → 真的需要登录，HTTP 方案失败，退出让第二层处理

详见 `references/page-observation-pitfalls.md`。

## 执行流程

### Phase 0: 学习参考页面（如果有）

如果用户提供了参考详情页 URL（reference_urls），先学习这些页面的结构。

**0.1 逐个打开参考页面**
```
browser_navigate(url=<参考URL_1>)
```

**0.2 分析页面结构**
```
browser_snapshot(full=true)
```
仔细记录：
- 正文在哪个 div/class 里？
- 标题、发布时间、附件等字段的位置
- 详情页的 URL 结构模式

**0.3 用 curl 获取真实 HTML 验证选择器**
```bash
curl -s '<参考URL_1>' -o /tmp/ref1.html
cat /tmp/ref1.html | python3 -c "
import sys, re
html = sys.stdin.read()
for cls in ['article-content', 'news_content', 'TRS_Editor', 'content', 'detail-content']:
    m = re.search(f'<div class=\\\\\"[^\\\\\"]*{cls}[^\\\\\"]*\\\\\">([\\\\s\\\\S]*?)</div>', html, re.IGNORECASE)
    if m:
        print(f'找到选择器: .{cls}')
        break
"
```

**0.4 打开第 2-3 个参考页面，对比结构**
确认选择器是否通用，记录差异。

**0.5 总结学到的选择器**
在 Phase 1.6 探索时，优先使用这些从参考页面学到的选择器。

**🚨 重要：**
- 参考页面是"答案"，比你自己猜的选择器更可靠
- 如果参考页面的选择器和你自己找的不一样，以参考页面为准
- 参考页面只用于学习详情页结构，列表页和 API 仍需自己探索

### Phase 1: 浏览器探索网站

**1.1 打开网页**
```
browser_navigate(url=<用户的URL>)
```

**1.2 截取页面网络请求（找 API）**
```
browser_console(expression=`
  JSON.stringify(
    performance.getEntriesByType('resource')
      .filter(r => r.initiatorType === 'xmlhttprequest' || r.initiatorType === 'fetch')
      .map(r => ({ url: r.name, type: r.initiatorType }))
  )
`)
```
分析结果：
- URL 含 `list`/`query`/`search`/`page`/`notice`/`data`/`api` → 高优先级 API
- URL 含 `.js`/`.css`/`.png`/`.jpg`/`.woff` → 忽略

**1.3 获取页面文本结构**
```
browser_snapshot(full=true)
```
分析：标题、列表项、分页、搜索框、日期选择器。

**1.4 逐个分析可疑 API**

对于每个可疑 API，在浏览器 console 里直接调用：

GET 请求：
```
browser_console(expression=`fetch('<API_URL>').then(r => r.text()).then(t => t.substring(0, 3000))`)
```

POST 请求（先尝试 GET，如果失败构造 POST）：
```
browser_console(expression=`
  fetch('<API_URL>', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({pageNo: 1, pageSize: 10})
  }).then(r => r.text()).then(t => t.substring(0, 3000))
`)
```

如果 POST 参数未知，从页面 JS 找线索：
```
browser_console(expression=`
  JSON.stringify(
    Array.from(document.querySelectorAll('script'))
      .map(s => s.textContent)
      .filter(t => t.length > 10 && t.length < 5000)
      .filter(t => t.includes('pageNo') || t.includes('pageSize') || t.includes('api') || t.includes('/list'))
      .slice(0, 3)
  )
`)
```

**1.5 交互探索（如需要）**

如果数据需要翻页/点击才能加载：
```
browser_click(ref=<翻页按钮ref>)
browser_console(expression=`
  JSON.stringify(
    performance.getEntriesByType('resource')
      .filter(r => r.initiatorType === 'fetch' || r.initiatorType === 'xmlhttprequest')
      .map(r => r.name)
      .slice(-5)
  )
`)
```
对比翻页前后的请求差异 → 找到分页参数。

### **1.6 详情页探索（最关键！必须做！）**

**🚨 优先级规则：**
- 如果 Phase 0 已经从参考 URL 学到了选择器，**直接使用那些选择器**，跳过 Step 1-4
- 如果没有参考 URL 或参考 URL 的选择器不适用，才执行下面的完整流程

**这一步决定 content 字段质量。跳过 = content 只有标题。**

**Step 1: 在列表中找到一个详情链接，点击进去**

```
browser_click(ref=<第一个列表项的链接ref>)
```

**Step 2: 用 browser_snapshot 看详情页内容**

```
browser_snapshot(full=true)
```

仔细分析：
- 正文在哪个 div/class 里？（常见的：`article-content`, `news_content`, `TRS_Editor`, `content`, `detail-content`, `post-content`）
- 正文包含哪些段落？长度大概多少字？
- 是否有附件下载链接？

**Step 3: 用 browser_console 验证 HTML 结构**

```
browser_console(expression=`
  JSON.stringify({
    html: document.documentElement.outerHTML.substring(0, 500),
    paragraphs: Array.from(document.querySelectorAll('p')).slice(0, 10).map(p => p.textContent.substring(0, 100)),
    mainContent: document.querySelector('.article-content, .news_content, .TRS_Editor, .content, .detail-content, [class*=content]')?.innerHTML?.substring(0, 1000) || 'NOT FOUND'
  })
`)
```

**关键问题：如果 browser_console 被安全策略拦截**

浏览器工具的安全策略会拦截包含 `fetch/XMLHttpRequest` 的表达式。
如果遇到 `[Blocked: browser_console(expression=...)]`，**立即换用 terminal + curl**：

```bash
terminal(command="curl -s 'https://example.com/detail/123' -o /tmp/detail.html && wc -l /tmp/detail.html")
terminal(command="grep -oE '<div class=\\\"[^\\\"]*content[^\\\"]*\\\"' /tmp/detail.html | head -5")
terminal(command="sed -n '/<div class=\\\"article-content\\\"/,/<\\/div>/p' /tmp/detail.html | head -30")
```

这是**最可靠的方式**，可以直接看真实 HTML 结构。

**Step 4: 从 HTML 中找到正文的精确选择器**

**不要只猜，必须实际找到！** 执行：

```bash
terminal(command="cat /tmp/detail.html | python3 -c \"
import sys, re
html = sys.stdin.read()
for cls in ['article-content', 'news_content', 'TRS_Editor', 'content', 'detail-content', 'post-content', 'article']:
    m = re.search(f'<div class=\\\\\"[^\\\\\"]*{cls}[^\\\\\"]*\\\\\">([\\\\s\\\\S]*?)</div>', html, re.IGNORECASE)
    if m:
        text = re.sub(r'<[^>]+>', ' ', m.group(1))
        text = re.sub(r'\\\\s+', ' ', text).strip()
        print(f'{cls}: {len(text)} chars')
        print(f'Preview: {text[:300]}')
        print()
\"")
```

**如果找不到 content 容器，尝试提取所有 `<p>` 标签**：

```bash
terminal(command="cat /tmp/detail.html | python3 -c \"
import sys, re
html = sys.stdin.read()
paragraphs = re.findall(r'<p[^>]*>([\\\\s\\\\S]*?)</p>', html, re.IGNORECASE)
texts = [re.sub(r'<[^>]+>', ' ', p).strip() for p in paragraphs]
texts = [t for t in texts if len(t) > 20]
print(f'Found {len(texts)} paragraphs')
for i, t in enumerate(texts[:10]):
    print(f'{i+1}. {t[:150]}')
\"")
```

**Step 5: 记录找到的选择器**

在生成代码前，必须明确记录：
- **详情 URL 格式**：如 `https://example.com/detail/{id}.htm`
- **正文选择器**：如 `<div class="article-content">` 或所有 `<p>` 标签
- **正文提取正则**：如 `/<div class="article-content">([\s\S]*?)<\/div>/`
- **附件选择器**（如有）
- **noticeType**：如果页面/API 有公告类型信息（采购公告/结果公告/招标公告/变更公告），记录下来

---

### Phase 2: 生成爬虫代码

用 `write_file` 写入 `scrapers/scrape_<name>.js`。

**🚨 关键路径规则：**
- 爬虫文件：`scrapers/scrape_<name>.js`
- OUTPUT_JSON：`path.join(__dirname, '..', 'raw_data', '<name>_data.json')` — **只用一层 `..`**，因为爬虫在 `scrapers/` 目录下运行

**代码必须包含：**

```javascript
/**
 * <网站名称> (<缩写>) <描述>
 *
 * Usage:
 *   node scrape_<name>.js --info             # 输出元数据 JSON
 *   node scrape_<name>.js --latest 5         # 爬取最新 N 条
 *   node scrape_<name>.js --yesterday        # 爬取昨天数据
 *   node scrape_<name>.js --date YYYY-MM-DD  # 爬取指定日期
 */

const http = require('http');  // 或 https
const fs = require('fs');
const path = require('path');
const { stripHtml } = require('./utility/stripHtml');
const { JsonWriter } = require('./utility/JsonWriter');

// ★ 路径只用一层 ..，因为爬虫在 scrapers/ 下运行
const OUTPUT_JSON = path.join(__dirname, '..', 'raw_data', '<name>_data.json');

// ===================== HTTP 请求 =====================
// 根据目标网站选 http 或 https
// 必须包含：重试、超时(15-30s)、错误处理
// 如果需要 SSL 遗留重协商：
// rejectUnauthorized: false, secureProtocol: 'TLS_method',
// secureOptions: require('constants').SSL_OP_LEGACY_SERVER_CONNECT

// ===================== 限频退避 =====================
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function requestWithBackoff(requestFn, label) {
  let delay = 5000;  // 初始 3-5s
  const MAX_ATTEMPTS = 6;  // 最多 4-6 次重试
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
        return { result: false, message: e.message };
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
// ★ 必须用本地时间，禁止 toISOString()（那是 UTC）
function formatScrapeTime() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}`;
}

// ===================== 详情解析（关键！） =====================
function parseDetailPage(html) {
  // **必须实现多策略提取链！**
  // 策略 1: 精确选择器（从 Phase 1.6 验证得到的）
  let content = '';
  const selectors = [
    /<div class="article-content">([\s\S]*?)<\/div>/i,
    /<div class="news_content">([\s\S]*?)<\/div>/i,
    /<div class="TRS_Editor">([\s\S]*?)<\/div>/i,
    /<div[^>]*class="[^"]*content[^"]*"[^>]*>([\s\S]*?)<\/div>/i,
  ];
  
  for (const sel of selectors) {
    const m = html.match(sel);
    if (m) {
      content = stripHtml(m[1]);
      break;
    }
  }
  
  // 策略 2: 提取所有 <p> 标签（当找不到 content 容器时）
  if (!content || content.length < 200) {
    const paragraphs = [];
    const pMatches = html.match(/<p[^>]*>([\s\S]*?)<\/p>/gi) || [];
    for (const p of pMatches) {
      const text = stripHtml(p).trim();
      if (text.length > 20) {  // 过滤空段落
        paragraphs.push(text);
      }
    }
    if (paragraphs.length > 0) {
      content = paragraphs.join('\n\n');
    }
  }
  
  // **必须验证内容长度！**
  if (content.length < 200) {
    console.warn('    ⚠ 提取的内容过短，可能提取失败');
  }
  
  return content;
}

// ===================== 主流程 =====================
async function main() {
  const args = process.argv.slice(2);

  // ★ --info 必须输出合法 JSON（被 run_scrapers.py 和 batch_scraper.py 解析）
  if (args.includes('--info')) {
    console.log(JSON.stringify({
      name: '<name>',
      description: '<描述>',
      modes: ['latest', 'yesterday', 'date'],
      outputFile: 'raw_data/<name>_data.json',
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

  const scrapeTime = formatScrapeTime();
  // ★ JsonWriter 正确用法：第二个参数是对象 { source, scrapeTime }
  // ★ JsonWriter 没有 close() 方法，不需要调用
  const writer = new JsonWriter(OUTPUT_JSON, { source: '<name>', scrapeTime });

  // 1. 获取列表数据（API 或 HTML 解析）
  // 2. 日期过滤（如果有 targetDate）
  // 3. 获取详情（如果需要）- 必须调用 parseDetailPage
  // 4. JsonWriter 增量写入
  // 5. 每条 row 必须包含: title, content, publishTime, url, noticeType(推荐)
}

main().catch((e) => { console.error('失败:', e.message); process.exit(1); });
```

**代码生成规则：**

1. 有 JSON API → 优先用 API（比 HTML 解析可靠）
2. 分析 API 的分页参数（pageNo/pageSize/curPage 等）
3. 分析响应结构（data/list/rows/records 等字段）
4. 如果有日期过滤参数 → 传给它，但**绝不能信任它**（见规则 11）
5. 没有 API → 用 HTML 解析 + https.get + 正则
6. 所有请求用 `requestWithBackoff` 包装
7. 用 `JsonWriter` 增量写入（每条详情写完立即写磁盘）
8. 用 `stripHtml()` 处理 HTML 内容
9. 请求间隔 `sleep(1500~5000)` + 随机抖动
10. console.log 输出进度，如 `[1/10] 标题前40字... ✓`

**🚨 规则 11: 日期过滤必须做客户端验证（强制！）**

很多网站的 API 会**静默忽略**日期过滤参数（接受参数但不报错，返回所有数据）。
这是已知的高频坑，已在多个银行/政府网站上验证。

**强制规则：** `--yesterday` 和 `--date` 模式下，必须实现客户端日期过滤，不能只依赖 API 参数。

实现方式（必须全部包含）：

```javascript
// 1. API 参数照传（如果有），但结果必须客户端二次过滤
const result = await fetchList(pageNo, pageSize, targetDate, targetDate);
const matchedItems = result.rows.filter(item => {
  const itemDate = (item.publishDate || '').substring(0, 10);
  return itemDate === targetDate;
});

// 2. 打印诊断信息，帮助发现 API 日期过滤是否生效
console.log(`  第 ${pageNo} 页: ${result.rows.length} 条，其中 ${matchedItems.length} 条是 ${targetDate} 的`);

// 3. 提前终止：如果当前页最后一条记录的日期比目标日期早，停止翻页
//    （数据通常按时间倒序排列，后面的只会更早）
const lastDate = (result.rows[result.rows.length - 1].publishDate || '').substring(0, 10);
if (lastDate && lastDate < targetDate) {
  console.log(`  ✓ 当前页最早数据 ${lastDate} 早于目标日期 ${targetDate}，停止翻页`);
  break;
}

// 4. 翻页上限：最多翻 N 页（如 10 页），防止无限循环
const MAX_PAGES = 10;
```

**验证 API 日期过滤是否生效的方法：**
- 固定一个日期调 API，看返回的 `total` 和实际匹配数
- 如果 `total` 远大于实际匹配数（比如 total=5000 但只有 5 条匹配）→ API 日期过滤不生效
- 这种情况下必须完全依赖客户端过滤

**🚨 Row 字段规范（严格遵守）：**

每条 row 必须包含：

| 字段 | 必填 | 类型 | 说明 |
|------|------|------|------|
| `title` | **是** | string | 公告标题 |
| `content` | **是** | string | 公告正文纯文本（用 `stripHtml()` 处理），**不能等于 title**，长度应 > 200 字 |
| `publishTime` | **是** | string | 发布时间，格式 `YYYY-MM-DD` 或 `YYYY-MM-DD HH:mm` |
| `url` | **是** | string | 公告详情页 URL |
| `noticeType` | **推荐** | string | 公告类型，如 `"采购公告"`、`"结果公告"`、`"招标公告"`、`"变更公告"` 等 |

**🚨 noticeType 的重要性：**
- `extract_fields.py` 会优先使用 raw_data 中已有的 `noticeType`/`bidType`/`method`，映射为严格枚举（`采购公告` / `结果公告` / `其他`）
- 如果爬虫不提供，会 fallback 到 LLM 分类或标题关键词推断，但准确率较低
- **如果平台 API/页面提供了类型信息，必须在 row 里保留！**
- 如果平台 API 返回数字码（如 `MESSAGE_TYPE=1`），用 MAP 映射为中文类型名

**🚨 scrapeTime 格式（重要）：**
- 必须用本地时间：`formatScrapeTime()` 返回 `YYYY-MM-DDTHH`
- **禁止使用 `toISOString()`**（那是 UTC 时间，和本地时间差 8 小时）

**🚨 详情解析规则（最重要！）：**

11. **必须实现多策略提取链**：先尝试精确选择器，失败则尝试通用选择器，最后尝试所有 `<p>` 标签
12. **必须验证内容长度**：提取后检查 content.length，如果 < 200 字符则警告
13. **content 不能等于 title**：这是最常见的 bug！如果 content 只是标题重复，说明提取失败
14. **从 Phase 1.6 获取的真实选择器必须用上**：不要用猜测的选择器

### Phase 3: 测试验证（必须全部通过，不能跳过）

**3.1 检查 --info 输出**

```bash
cd /Users/tristcz/project/ai_yuangong/scrapers
node scrape_<name>.js --info
```

必须输出合法 JSON，包含 `name` 和 `description` 字段。

**3.2 运行 --latest 1 生成测试数据**

```bash
cd /Users/tristcz/project/ai_yuangong/scrapers
node scrape_<name>.js --latest 1
```

必须成功执行，生成 `raw_data/<name>_data.json`。

**3.3 完整验证脚本（必须执行，不能手动跳过）**

运行以下验证脚本，检查所有必需条件：

```bash
cd /Users/tristcz/project/ai_yuangong
python3 -c "
import json, sys

# 1. 检查输出文件
try:
    with open('raw_data/<name>_data.json') as f:
        data = json.load(f)
except FileNotFoundError:
    print('❌ FAIL: 输出文件不存在')
    sys.exit(1)

# 2. 检查输出结构
if 'rows' not in data or not data['rows']:
    print('❌ FAIL: 输出为空或无 rows 字段')
    sys.exit(1)

# 3. 检查必需字段
row = data['rows'][0]
required = ['title', 'content', 'publishTime', 'url']
missing = [k for k in required if k not in row or not row[k]]
if missing:
    print(f'❌ FAIL: 缺少必需字段: {missing}')
    sys.exit(1)

# 4. 检查 content 质量
if len(row['content']) < 200:
    print(f'❌ FAIL: content 过短 ({len(row[\"content\"])} 字符，需要 >= 200)')
    sys.exit(1)

if row['content'].strip() == row['title'].strip():
    print('❌ FAIL: content 等于 title（说明详情页解析失败）')
    sys.exit(1)

# 5. 检查 scrapeTime 格式
if 'scrapeTime' in data:
    if 'T' not in data['scrapeTime']:
        print(f'❌ FAIL: scrapeTime 格式错误: {data[\"scrapeTime\"]}（应该是 YYYY-MM-DDTHH）')
        sys.exit(1)

print(f'✅ 输出结构正确（{len(data[\"rows\"])} 条记录）')
print(f'✅ content 质量合格（{len(row[\"content\"])} 字符）')
print('✅ 所有验证通过')
"
```

**如果验证失败，必须修复后重新运行，直到全部通过。**

**3.4 常见问题修复**

根据验证失败的原因，修复对应问题：

| 失败原因 | 修复方法 |
|---------|---------|
| 输出文件不存在 | 检查 OUTPUT_JSON 路径：`path.join(__dirname, '..', 'raw_data', '<name>_data.json')` |
| 缺少必需字段 | 检查 `writer.addRow()` 是否包含 title/content/publishTime/url |
| content 过短 | 详情页解析失败，用 `curl -s <detail_url>` 查看真实 HTML，调整选择器 |
| content 等于 title | 没有正确提取正文，只拿到了标题。检查详情页解析逻辑 |
| scrapeTime 格式错误 | 使用 `formatScrapeTime()` 函数，不要用 `toISOString()` |

**修复后必须重新运行验证脚本（3.2 + 3.3），直到全部通过。**

**3.5 最终测试**

验证通过后，再测试批量模式：

```bash
cd /Users/tristcz/project/ai_yuangong/scrapers
node scrape_<name>.js --latest 3
```

确保能正常爬取多条数据。

### Phase 4: 失败修复

如果测试失败：

1. 分析错误（terminal 输出的 stderr）
2. 常见问题：
   - API URL 错误 → 回浏览器重新验证
   - 字段名错误 → 对比 API 真实响应
   - 网络错误 → 检查请求头（Referer/User-Agent）
   - 解析错误 → 回浏览器重新看页面结构
   - **SSL 重协商错误** → 添加 `secureOptions: require('constants').SSL_OP_LEGACY_SERVER_CONNECT`
   - **content 只有标题** → 详情页 HTML 结构分析错误，重新用 curl 查看真实 HTML
   - **OUTPUT_JSON 路径 ENOENT** → 检查是否多了一层 `..`，正确：`path.join(__dirname, '..', 'raw_data', ...)`
   - **scrapeTime 时间不对** → 检查是否误用了 `toISOString()`（UTC）
   - **JsonWriter 报错** → 第二个参数必须是对象 `{source, scrapeTime}`，不是字符串
3. 用 `patch` 修复代码
4. 重新测试
5. 最多修复 3 轮

---

## 参考文件

生成代码时参考现有爬虫：
- `scrape_icbc.js` — POST API + 分页 + 详情
- `scrape_cfcpn.js` — POST API + 分页 + 日期过滤
- `scrape_chinapost.js` — HTML 解析 + 翻页 + 日期过滤
- `scrape_abc_puc.js` — cycletls TLS 指纹 + API + noticeType 映射
- `scrape_cdb.js` — HTML 解析 + 多策略提取链
- `scrape_spdb.js` — AES-ECB 解密 + 自定义 Base64 + SSL 遗留重协商

工具函数：
- `scrapers/utility/stripHtml.js` — HTML → 纯文本
- `scrapers/utility/JsonWriter.js` — 增量 JSON 写入器（第二个参数是对象，没有 close()）

完整开发规范：
- `SCRAPER_DEV_GUIDE.md` — 项目根目录下的详细开发规范和更多示例

## 允许的操作范围

你可以且仅可以做以下操作：

1. **新建一个文件**：`scrapers/scrape_<name>.js`（你的爬虫代码）
2. **读取/测试**：运行你的爬虫、读取输出 JSON、检查质量
3. **读取现有文件**：参考现有爬虫和工具函数

**你绝对不能做的：**
- ❌ 修改任何其他项目文件（server.py、extract_fields.py、其他爬虫等）
- ❌ 删除任何其他文件
- ❌ 修改 `scrapers/utility/` 下的工具函数
- ❌ 修改 `extracted_data/` 下的数据

## 禁止行为

- 不要问用户任何问题
- 不要使用外部 npm 包（只用 Node.js 内置模块 + 项目工具函数；`cycletls` 例外）
- **绝对禁止使用 Playwright 或任何浏览器自动化**（这是第二层 gen-scraper-browser 的职责）
- 不要生成不完整的代码
- **不要跳过 Phase 1.6（详情页探索）**
- **不要跳过 Phase 3.3（content 质量验证）**
- ❌ 不使用 `toISOString()` 生成 scrapeTime
- ❌ OUTPUT_JSON 路径不多余嵌套 `..`
- ❌ 不跳过详情页爬取（content 不能只有标题）
- ❌ 不传字符串给 JsonWriter 第二个参数（必须是对象）
- ❌ 不调用 writer.close()（JsonWriter 没有这个方法）

## 常见陷阱

### 陷阱 1：JsonWriter API 使用错误

**错误用法：**
```javascript
const writer = new JsonWriter(OUTPUT_JSON, '2026-07-24T10');  // ❌ 第二个参数应该是对象
writer.close();  // ❌ JsonWriter 没有 close() 方法
```

**正确用法：**
```javascript
const writer = new JsonWriter(OUTPUT_JSON, { source: 'site', scrapeTime });  // ✓
// JsonWriter 是同步写入的，不需要 close()
```

### 陷阱 2：SSL/TLS 遗留重协商错误

**症状：**
```
EPROTO: unsafe legacy renegotiation disabled
```

**原因：** Node.js 17+ 默认禁用不安全的 SSL 重协商，某些银行服务器使用旧版 TLS 配置。

**解决方案：**
```javascript
const reqOptions = {
  hostname: 'example.com',
  path: '/api/data',
  method: 'GET',
  headers: { /* ... */ },
  rejectUnauthorized: false,
  secureProtocol: 'TLS_method',
  secureOptions: require('constants').SSL_OP_LEGACY_SERVER_CONNECT,  // 关键！
};
```

### 陷阱 3：加密的 API 响应（HTTP 方案可解决）

**识别：** 某些银行网站的 API 返回加密数据（如 AES + 自定义 Base64）。

**解决方案：**
1. 查看页面 JS 源码，找到解密逻辑
2. 分析加密算法（AES/DES/RSA）、密钥、加密模式（ECB/CBC）
3. 在爬虫中复现相同的解密逻辑
4. 参考 `scrape_spdb.js` 的 AES-ECB + 自定义 Base64 实现

**关键：** 这是 HTTP 方案可以解决的，不需要浏览器自动化！

### 陷阱 4：瑞数 WAF（必须失败并交给第二层）

**症状：**
```
HTTP 412 Precondition Failed + JavaScript 挑战页面
```

**判断标准：**
- 即使使用了正确的 User-Agent、Referer、Cookie，仍然返回 412
- 页面返回的是 JS 挑战代码，需要执行才能生成正确的 cookie
- 尝试了 cycletls TLS 指纹模拟后仍然失败

**正确做法：**
- 明确报告：瑞数 WAF 需要浏览器环境执行 JS 挑战，HTTP 方案无法绕过
- **不要尝试使用 Playwright**，这是第二层 gen-scraper-browser 的职责
- 退出并让系统自动进入第二层

**参考案例：** `scrape_hfbank.js`（徽商银行）必须使用 Chrome CDP 方案。

## 自动化集成（server.py 调用）

当通过 `hermes chat -q` 作为子进程调用时：
- **必须使用 `--yolo`**：否则命令审批系统会拒绝 shell 命令 → agent 以为用户有顾虑 → 提问 → 无人回答 → 卡死
- **prompt 必须包含**："不要问我任何问题，所有决策你自己做，遇到错误自己修复"
- **20 分钟硬限制**：server.py 有总超时兜底，超过 20 分钟直接 kill。不要在某个步骤上死等
- **诊断 hang**：检查 `~/.hermes/logs/errors.log`，找 "Stream stale"（LLM 响应卡死）或 "User denied"（命令被审批拒绝）

详见 `references/automation-integration.md`。

## 常见问题 Checklist

| 问题 | 解决方案 |
|------|----------|
| OUTPUT_JSON 路径 ENOENT | 检查是否多了一层 `..`，正确写法：`path.join(__dirname, '..', 'raw_data', ...)` |
| scrapeTime 时间不对 | 用 `new Date()` 本地时间，不要用 `toISOString()`（UTC） |
| content 等于 title | 详情页解析失败，需要用 curl 检查真实 HTML 结构，调整选择器 |
| content 过短 (<200字) | 实现多策略提取链，fallback 到 `<p>` 标签提取 |
| noticeType 丢失 | 如果平台 API/HTML 中有类型信息，务必保留在 row 中 |
| 被 WAF 拦截 | 考虑使用 `cycletls` 模拟 TLS 指纹 |
| SSL 重协商错误 | 添加 `secureOptions: require('constants').SSL_OP_LEGACY_SERVER_CONNECT` |
| JsonWriter 报错 | 第二个参数必须是对象 `{source, scrapeTime}`，不是字符串；没有 `close()` 方法 |
| 日期过滤不生效 | 某些 API 的日期参数是**静默忽略**的（返回所有数据但不报错）。必须在客户端做日期过滤：翻页时检查每条记录的日期，找到比目标日期更早的数据时提前终止（数据通常按时间倒序）。验证方法：先用固定日期调 API，对比返回的 `total` 和实际匹配数。如果 `total` 远大于预期 → API 日期过滤不生效 |
| run_scrapers.py --list 看不到新爬虫 | 检查爬虫文件是否在 `scrapers/scrape_<name>.js`，文件名是否正确 |
| **Agent 停下来问问题** | **检查 scraper.py 是否使用了 `--yolo` 参数！** 没有这个参数，命令审批会拒绝 shell 命令，agent 以为用户拒绝，就会停下来问。这是最常见的挂起原因 |
