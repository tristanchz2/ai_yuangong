---
name: gen-scraper
description: "URL → 全自动爬虫生成。Hermes 用浏览器探索网站，生成代码，测试，修复。不问问题。"
version: 4.0.0
---

# URL → 全自动爬虫生成

用户发一个 URL，Hermes 全自动完成：浏览器探索 → 代码生成 → 测试 → 修复 → 注册。
**全程不问用户任何问题。所有决策预设。**

## 触发条件

用户发了一个 URL 并说"帮我爬"/"生成爬虫"之类的话。

## 项目架构（必须遵守）

```
ai_yuangong/
├── scrapers/              # 爬虫文件（Node.js）← 你的爬虫放这里
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
├── sites.json             # 站点注册表 ← 你需要在这里注册新站点
├── extract_fields.py      # LLM 字段提取器
├── run_scrapers.py        # CLI 运行入口（自动发现 scrapers/scrape_*.js）
├── routers/
│   ├── batch_scraper.py   # 批量爬取调度（依赖 sites.json）
│   └── scraper.py         # 爬虫自动生成（调用你的 Hermes）
└── server.py              # FastAPI 主服务
```

**数据流水线：**
```
爬虫 (Node.js) → raw_data/<name>_data.json → LLM提取 (extract_fields.py) → extracted_data/{notice_type}/{date}.json
```

## 预设决策（不需要问用户）

| 决策项 | 预设值 |
|--------|--------|
| 爬虫语言 | Node.js（只用内置 http/https 模块） |
| 输出格式 | JSON，增量写入 |
| CLI 接口 | `--info` / `--latest N` / `--yesterday` / `--date YYYY-MM-DD` |
| 工具函数 | `stripHtml` + `JsonWriter`（项目已有） |
| 爬虫名称 | 从域名推导 |
| 爬虫文件路径 | `scrapers/scrape_<name>.js` |
| 数据输出路径 | `raw_data/<name>_data.json` |
| 错误处理 | `requestWithBackoff`（限频退避） |
| 请求间隔 | 2-5 秒 |

## 执行流程

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
terminal(command="grep -oE '<div class=\"[^\"]*content[^\"]*\"' /tmp/detail.html | head -5")
terminal(command="sed -n '/<div class=\"article-content\"/,/<\\/div>/p' /tmp/detail.html | head -30")
```

这是**最可靠的方式**，可以直接看真实 HTML 结构。

**Step 4: 从 HTML 中找到正文的精确选择器**

**不要只猜，必须实际找到！** 执行：

```bash
terminal(command="cat /tmp/detail.html | python3 -c \"
import sys, re
html = sys.stdin.read()
# 尝试多种选择器
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
# 提取所有段落
paragraphs = re.findall(r'<p[^>]*>([\\s\\S]*?)</p>', html, re.IGNORECASE)
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
4. 如果有日期过滤参数 → 用它实现 `--yesterday`
5. 没有 API → 用 HTML 解析 + https.get + 正则
6. 所有请求用 `requestWithBackoff` 包装
7. 用 `JsonWriter` 增量写入（每条详情写完立即写磁盘）
8. 用 `stripHtml()` 处理 HTML 内容
9. 请求间隔 `sleep(1500~5000)` + 随机抖动
10. console.log 输出进度，如 `[1/10] 标题前40字... ✓`

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

### Phase 3: 测试验证

**3.1 验证 --info**
```bash
cd /Users/tristcz/project/ai_yuangong/scrapers
node scrape_<name>.js --info
```
必须输出合法 JSON。

**3.2 验证 --latest 1（单条测试，快速发现问题）**
```bash
node scrape_<name>.js --latest 1
```

**🚨 3.3 验证 content 质量（必须做！）**

测试完成后，立即检查输出的 JSON：

```bash
cd /Users/tristcz/project/ai_yuangong
python3 -c "
import json
with open('raw_data/<name>_data.json') as f:
    data = json.load(f)
row = data['rows'][0]
print(f'Title: {row[\"title\"]}')
print(f'Content length: {len(row[\"content\"])} chars')
print(f'Content preview: {row[\"content\"][:200]}')
print()
if len(row['content']) < 200:
    print('❌ FAIL: Content too short (< 200 chars)')
    print('Need to fix detail parsing!')
elif row['content'].strip() == row['title'].strip():
    print('❌ FAIL: Content equals title (extraction failed)')
    print('Need to fix detail parsing!')
else:
    print('✅ PASS: Content looks good')
"
```

**如果 content 验证失败：**

1. 回到 Phase 1.6，重新分析详情页 HTML
2. 用 terminal + curl 查看真实 HTML：`curl -s <detail_url> | head -200`
3. 找到正确的正文选择器
4. 用 patch 修复 parseDetailPage 函数
5. 重新测试，直到 content 验证通过

**3.4 验证 --latest 3（批量测试）**
```bash
node scrape_<name>.js --latest 3
```
检查所有条目的 content 都正常。

**3.5 验证自动发现**
```bash
cd /Users/tristcz/project/ai_yuangong
python3 run_scrapers.py --list
```
新爬虫必须出现在列表中。

### Phase 4: 失败修复

如果测试失败：

1. 分析错误（terminal 输出的 stderr）
2. 常见问题：
   - API URL 错误 → 回浏览器重新验证
   - 字段名错误 → 对比 API 真实响应
   - 网络错误 → 检查请求头（Referer/User-Agent）
   - 解析错误 → 回浏览器重新看页面结构
   - **content 只有标题** → 详情页 HTML 结构分析错误，重新用 curl 查看真实 HTML
   - **OUTPUT_JSON 路径 ENOENT** → 检查是否多了一层 `..`，正确：`path.join(__dirname, '..', 'raw_data', ...)`
   - **scrapeTime 时间不对** → 检查是否误用了 `toISOString()`（UTC）
3. 用 `patch` 修复代码
4. 重新测试
5. 最多修复 3 轮

**修复详情页解析时，用 curl + python 验证：**
```bash
curl -s '<detail_url>' | python3 -c "
import sys, re
html = sys.stdin.read()
# 尝试多种选择器
for cls in ['article-content', 'news_content', 'TRS_Editor', 'content']:
    m = re.search(f'<div class=\\\\\"[^\\\\\"]*{cls}[^\\\\\"]*\\\\\">([\\\\s\\\\S]*?)</div>', html, re.IGNORECASE)
    if m:
        text = re.sub(r'<[^>]+>', ' ', m.group(1))
        text = re.sub(r'\\\\s+', ' ', text).strip()
        print(f'{cls}: {len(text)} chars')
        print(f'Preview: {text[:300]}')
        break
"
```

### Phase 5: 注册到 sites.json

**测试全部通过后**，将新爬虫注册到 `sites.json`，使批量爬取系统能够发现它。

**5.1 读取当前 sites.json**
```bash
cat sites.json
```

**5.2 找到当前最大 id**
查看 `sites.json` 中 `sites` 数组里最大的 `id` 值。

**5.3 添加新站点条目**
用 `patch` 在 `sites` 数组末尾添加：
```json
{
  "id": <当前最大id + 1>,
  "name": "<网站中文名>",
  "url": "<目标网站URL>",
  "scraper_name": "<name>",
  "description": "<网站描述>",
  "status": "active",
  "hidden": false
}
```

**字段说明：**
- `id`：当前最大 id + 1（不能重复）
- `name`：网站中文名称（用于前端显示）
- `url`：网站首页 URL
- `scraper_name`：**必须和爬虫文件名一致**（`scrape_<scraper_name>.js`）
- `description`：简短描述
- `status`：固定 `"active"`
- `hidden`：设为 `false` 才会在批量爬取中被执行

**5.4 验证 JSON 合法性**
```bash
python3 -c "import json; json.load(open('sites.json')); print('✅ sites.json 格式正确')"
```

---

## 参考文件

生成代码时参考现有爬虫：
- `scrape_icbc.js` — POST API + 分页 + 详情
- `scrape_cfcpn.js` — POST API + 分页 + 日期过滤
- `scrape_chinapost.js` — HTML 解析 + 翻页 + 日期过滤
- `scrape_abc_puc.js` — cycletls TLS 指纹 + API + noticeType 映射
- `scrape_cdb.js` — HTML 解析 + 多策略提取链

工具函数：
- `scrapers/utility/stripHtml.js` — HTML → 纯文本
- `scrapers/utility/JsonWriter.js` — 增量 JSON 写入器

完整开发规范：
- `SCRAPER_DEV_GUIDE.md` — 项目根目录下的详细开发规范和更多示例

## 允许的操作范围

你可以且仅可以做以下操作：

1. **新建一个文件**：`scrapers/scrape_<name>.js`（你的爬虫代码）
2. **修改 `sites.json`**：在 `sites` 数组中添加新站点注册信息
3. **读取/测试**：运行你的爬虫、读取输出 JSON、检查质量
4. **读取现有文件**：参考现有爬虫和工具函数

**你绝对不能做的：**
- ❌ 修改任何其他项目文件（server.py、extract_fields.py、其他爬虫等）
- ❌ 删除任何其他文件
- ❌ 修改 `scrapers/utility/` 下的工具函数
- ❌ 修改 `extracted_data/` 下的数据

## 禁止行为

- 不要问用户任何问题
- 不要使用外部 npm 包（只用 Node.js 内置模块 + 项目工具函数；`cycletls` 例外）
- 不要生成不完整的代码
- 不要使用 Playwright/puppeteer 作为爬虫运行时
- **不要跳过 Phase 1.6（详情页探索）**
- **不要跳过 Phase 3.3（content 质量验证）**
- **不要跳过 Phase 5（sites.json 注册）**
- ❌ 不使用 `toISOString()` 生成 scrapeTime
- ❌ OUTPUT_JSON 路径不多余嵌套 `..`
- ❌ 不跳过详情页爬取（content 不能只有标题）

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
| 日期过滤不生效 | 检查 API 是否支持日期参数，不支持则在客户端过滤 |
| run_scrapers.py --list 看不到新爬虫 | 检查爬虫文件是否在 `scrapers/scrape_<name>.js`，文件名是否正确 |
| 批量爬取不执行新爬虫 | 检查 sites.json 是否已注册，`hidden` 是否为 `false` |
