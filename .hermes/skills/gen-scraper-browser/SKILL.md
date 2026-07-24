---
name: gen-scraper-browser
description: "浏览器兜底爬虫生成。当 gen-scraper 失败后，用真实 Chrome + CDP 协议绕过反爬/WAF。注意：批量运行时 Playwright 爬虫受互斥锁限制，同一时刻只能1个浏览器实例运行。详见 gen-scraper skill 的 references/two-layer-architecture.md。"
version: 2.1.0
---

# 浏览器兜底爬虫生成（Chrome CDP 方案）

## 触发条件

**仅作为 gen-scraper 的兜底方案**。当 gen-scraper（HTTP API / headless Playwright）失败后才使用此 skill。

失败原因通常是：
- 网站有 WAF/反爬，headless 浏览器被拦截
- 需要真实浏览器环境（Cookie/Session/JS 指纹）
- API 需要复杂认证，但浏览器已登录

## 核心方案：Chrome CDP（Chrome DevTools Protocol）

**不用 headless Playwright**（那个 gen-scraper 已经试过了）。
**用真实 Chrome 浏览器 + 远程调试端口**，这是光大银行（cebbank）和徽商银行（hfbank）验证过的方案。

原理：
1. 启动一个真实的 Chrome 浏览器进程（带 `--remote-debugging-port`）
2. Playwright 通过 CDP 协议连接到这个 Chrome
3. 对网站来说，这就是一个普通用户打开的 Chrome，不是自动化工具
4. 可以绕过绝大多数反爬/WAF/指纹检测

## 项目架构（必须遵守）

项目已按职责分层重构，你只关心爬虫相关部分：

```
ai_yuangong/
├── scrapers/              # 爬虫文件（Node.js）← 你生成的爬虫放这里
│   ├── utility/
│   │   ├── stripHtml.js   # HTML → 纯文本工具
│   │   └── JsonWriter.js  # 增量 JSON 写入器
│   └── scrape_<name>.js   # 每个站点一个爬虫脚本
├── raw_data/              # 爬虫原始输出 JSON ← 你的数据输出到这里
│   └── <name>_data.json
├── services/              # 业务服务层（你不需要改这里）
│   ├── scraper_generator.py  # 调用 Hermes 生成爬虫
│   └── llm_extractor.py   # LLM 字段提取
├── routers/               # FastAPI 薄路由
│   ├── scraper.py         # 爬虫生成路由
│   └── admin.py           # 管理员路由（含批量爬取）
├── scripts/               # CLI 脚本
│   └── run_scrapers.py    # 爬虫批量运行入口
└── server.py              # FastAPI 主服务入口
```

**数据流水线：**
```
爬虫 (Node.js) → raw_data/<name>_data.json → LLM提取 (services/llm_extractor.py) → extracted_data/{notice_type}/{date}.json
```

## 预设决策

| 决策项 | 预设值 |
|--------|--------|
| 浏览器方案 | Chrome CDP（真实 Chrome + remote-debugging-port） |
| 爬虫语言 | Node.js + Playwright（connectOverCDP 模式） |
| 输出格式 | JSON，增量写入 |
| CLI 接口 | `--info` / `--latest N` / `--yesterday` / `--date YYYY-MM-DD` |
| 工具函数 | `JsonWriter`（项目已有） |
| 爬虫名称 | 从域名推导 |
| 爬虫文件路径 | `scrapers/scrape_<name>.js` |
| 数据输出路径 | `raw_data/<name>_data.json` |

## 执行流程

### Phase 1: 用浏览器探索网站（必须详细分析）

**1.1 打开目标网站**

```
browser_navigate(url=<目标URL>)
browser_snapshot(full=true)
```

**1.2 分析列表页结构（必须记录以下信息）**

观察并记录：
- **列表容器选择器**：如 `div.gg_nr`、`#imgArticleList`、`ul.news-list`
- **列表项选择器**：如 `div.item`、`li.news-item`、`tr`
- **标题选择器**：如 `a.title`、`h3`、`.news-title`
- **链接选择器**：如 `a`（从列表项中获取 href）
- **日期选择器**：如 `span.date`、`em`、`.publish-time`
- **日期格式**：如 `2026-07-24`、`2026年7月24日`、`2026/07/24`
- **翻页机制**：
  - URL 分页：`index_2.shtml`、`?page=2`
  - JS 翻页：点击"下一页"按钮
  - 翻页按钮选择器：如 `a:has-text("下一页")`、`.next-page`
- **noticeType 信息**：是否有公告类型标签（如"招标公告"、"结果公告"）

**1.3 点击一个详情链接，分析详情页结构**

```
browser_click(ref=<详情链接ref>)
browser_snapshot(full=true)
```

记录：
- **标题选择器**：如 `h3.title`、`div.title`
- **日期选择器**：如 `div.creatDate`、`em.publish-time`
- **正文选择器**：如 `div.xilan_con`、`div.article-content`、`.TRS_Editor`
- **正文提取策略**：
  - 直接获取：`element.innerText`
  - 提取段落：`Array.from(element.querySelectorAll('p')).map(p => p.innerText).join('\n\n')`
- **noticeType 选择器**：如 `.tag`、`.notice-type`

**1.4 测试翻页（如果有）**

如果列表有多页，测试翻页是否正常：
```
browser_click(ref=<下一页按钮>)
browser_snapshot(full=true)
```
确认翻页后列表内容变化。

### Phase 2: 生成完整爬虫代码

用 `write_file` 写入 `scrapers/scrape_<name>.js`。

**🚨 必须使用完整的代码模板，包含所有必需功能。**

#### 完整代码模板

```javascript
/**
 * <网站中文名> (<name>) 爬虫
 * 目标页面: <列表URL>
 * 
 * 使用方法:
 *   node scrape_<name>.js --info              # 输出爬虫信息
 *   node scrape_<name>.js --latest 5          # 爬取最新 5 条
 *   node scrape_<name>.js --yesterday         # 爬取昨天的数据
 *   node scrape_<name>.js --date 2026-07-24   # 爬取指定日期的数据
 * 
 * 使用 Chrome CDP 绕过 WAF 检测
 */

const { chromium } = require('playwright');
const { JsonWriter } = require('./utility/JsonWriter');
const { execSync, spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const BASE_URL = '<网站根URL>';
const LIST_URL = '<列表页URL>';
const OUTPUT_FILE = path.join(__dirname, '..', 'raw_data', '<name>_data.json');
const MAX_PAGES = 15; // 翻页上限，防止死循环

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

function formatScrapeTime() {
  const now = new Date();
  const pad = n => String(n).padStart(2, '0');
  return `${now.getFullYear()}-${pad(now.getMonth()+1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}`;
}

function formatDate(d) {
  const pad = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`;
}

function getYesterday() {
  const d = new Date();
  d.setDate(d.getDate() - 1);
  return formatDate(d);
}

// 日期解析：支持多种格式
function parseDate(dateStr) {
  if (!dateStr) return null;
  // 2026年7月24日
  const m1 = dateStr.match(/(\d{4})年(\d{1,2})月(\d{1,2})日/);
  if (m1) return `${m1[1]}-${m1[2].padStart(2,'0')}-${m1[3].padStart(2,'0')}`;
  // 2026-07-24
  const m2 = dateStr.match(/(\d{4})-(\d{1,2})-(\d{1,2})/);
  if (m2) return `${m2[1]}-${m2[2].padStart(2,'0')}-${m2[3].padStart(2,'0')}`;
  // 2026/07/24
  const m3 = dateStr.match(/(\d{4})\/(\d{1,2})\/(\d{1,2})/);
  if (m3) return `${m3[1]}-${m3[2].padStart(2,'0')}-${m3[3].padStart(2,'0')}`;
  return null;
}

// 查找真实 Chrome 路径
function findChrome() {
  const paths = [
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/usr/bin/google-chrome',
    '/usr/bin/chromium-browser',
  ];
  for (const p of paths) {
    if (fs.existsSync(p)) return p;
  }
  try {
    return execSync('which google-chrome || which chromium-browser || which chromium 2>/dev/null', { encoding: 'utf8' }).trim();
  } catch { return null; }
}

// 提取列表页链接（根据 Phase 1 分析的选择器）
async function extractListLinks(page) {
  return await page.evaluate(() => {
    const results = [];
    // 🚨 根据实际页面结构调整选择器
    document.querySelectorAll('<列表项选择器>').forEach(el => {
      const a = el.querySelector('a');
      if (!a) return;
      
      const href = a.getAttribute('href');
      const title = (a.getAttribute('title') || a.textContent || '').trim();
      
      if (!href || !title || title.length < 5) return;
      
      // 相对路径转绝对路径
      let url = href;
      if (href.startsWith('http')) {
        url = href;
      } else if (href.startsWith('/')) {
        url = `${BASE_URL}${href}`;
      } else {
        // 处理相对路径
        url = `${BASE_URL}/${href.replace(/^\.\//, '')}`;
      }
      
      // 去重
      if (!results.some(r => r.url === url)) {
        results.push({ url, title });
      }
    });
    return results;
  });
}

// 访问详情页，提取完整信息
async function fetchDetail(page, link) {
  await page.goto(link.url, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await sleep(2000);
  
  const detail = await page.evaluate(() => {
    // 🚨 根据实际页面结构调整选择器
    
    // 标题
    const titleEl = document.querySelector('<详情页标题选择器>');
    const title = titleEl ? titleEl.innerText.trim() : '';
    
    // 日期
    const dateEl = document.querySelector('<详情页日期选择器>');
    const dateText = dateEl ? dateEl.innerText.trim() : '';
    
    // 公告类型（如果有）
    const typeEl = document.querySelector('<公告类型选择器>');
    const noticeType = typeEl ? typeEl.innerText.trim() : '';
    
    // 正文
    const contentEl = document.querySelector('<正文容器选择器>');
    let content = '';
    if (contentEl) {
      // 策略1：直接获取 innerText
      content = contentEl.innerText || contentEl.textContent || '';
      
      // 策略2：如果内容太短，尝试提取段落
      if (content.length < 200) {
        const paragraphs = Array.from(contentEl.querySelectorAll('p'))
          .map(p => p.innerText.trim())
          .filter(t => t.length > 0)
          .join('\n\n');
        if (paragraphs.length > content.length) {
          content = paragraphs;
        }
      }
    }
    
    return { title, dateText, noticeType, content };
  });
  
  return {
    title: detail.title || link.title,
    publishTime: parseDate(detail.dateText) || '',
    url: link.url,
    content: detail.content || link.title, // fallback
    noticeType: detail.noticeType || ''
  };
}

// 翻页逻辑（根据实际翻页机制选择）
async function goToNextPage(page) {
  // 🚨 根据实际翻页机制实现
  
  // 方式1：JS 翻页（点击"下一页"按钮）
  const clicked = await page.evaluate(() => {
    const anchors = Array.from(document.querySelectorAll('a'));
    const next = anchors.find(a => {
      const t = (a.innerText || '').trim();
      return t === '下一页' || t === '下页' || t === '>';
    });
    if (!next) return false;
    
    // 检查是否禁用
    const cls = (next.className || '') + ' ' + (next.parentElement?.className || '');
    if (next.hasAttribute('disabled') || /disabled|noMore|last|cur/i.test(cls)) return false;
    
    next.click();
    return true;
  });
  
  if (!clicked) return false;
  
  await sleep(3000);
  return true;
}

// 主爬取逻辑
async function scrape(options = {}) {
  const { mode = 'latest', count = 0, targetDate = null } = options;
  console.log(`[<网站名>] 启动爬虫... (模式: ${mode}${targetDate ? ', 目标日期: ' + targetDate : ''}${mode === 'latest' ? ', 最新 ' + count + ' 条' : ''})`);

  const chromePath = findChrome();
  if (!chromePath) {
    console.error('找不到 Chrome 浏览器');
    process.exit(1);
  }
  console.log(`Chrome 路径: ${chromePath}`);

  // 启动 Chrome（随机端口避免冲突）
  const debugPort = 9222 + Math.floor(Math.random() * 1000);
  const userDataDir = `/tmp/<name>-chrome-${Date.now()}`;

  console.log(`启动 Chrome (调试端口: ${debugPort})...`);
  const chromeProcess = spawn(chromePath, [
    `--remote-debugging-port=${debugPort}`,
    `--user-data-dir=${userDataDir}`,
    '--no-first-run',
    '--no-default-browser-check',
  ], {
    stdio: 'ignore',
    detached: true,
  });

  await sleep(3000); // 等 Chrome 启动

  let browser = null;
  try {
    browser = await chromium.connectOverCDP(`http://localhost:${debugPort}`);
    const contexts = browser.contexts();
    const context = contexts[0] || await browser.newContext();
    const page = context.pages()[0] || await context.newPage();

    console.log('[<网站名>] 访问列表页...');
    await page.goto(LIST_URL, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await sleep(5000); // 等 JS 渲染

    // WAF 检测
    const content = await page.content();
    console.log(`页面长度: ${content.length}`);
    if (content.length < 2000) {
      console.error('页面内容过短，可能被 WAF 拦截');
      fs.writeFileSync(`/tmp/<name>_debug.html`, content);
      return;
    }

    const writer = new JsonWriter(OUTPUT_FILE, { source: '<网站中文名>', scrapeTime: formatScrapeTime() });
    const seen = new Set();
    let stop = false;

    // 逐页处理
    for (let pageNo = 1; pageNo <= MAX_PAGES && !stop; pageNo++) {
      const links = await extractListLinks(page);
      const newLinks = links.filter(l => !seen.has(l.url));
      newLinks.forEach(l => seen.add(l.url));
      
      console.log(`\n第 ${pageNo} 页: ${links.length} 条（新增 ${newLinks.length} 条）`);

      if (newLinks.length === 0) {
        console.log('  本页无新增公告，停止');
        break;
      }

      let pageMinDate = null;

      // 逐条处理详情
      for (const link of newLinks) {
        console.log(`  [${writer.count + 1}] ${link.title.substring(0, 50)}...`);
        
        try {
          const row = await fetchDetail(page, link);
          const d = row.publishTime;
          
          if (d && (!pageMinDate || d < pageMinDate)) pageMinDate = d;

          // date 模式：只保存目标日期的数据
          if (mode === 'date') {
            if (d === targetDate) {
              writer.addRow(row);
              console.log(`    ✓ 命中 ${d}，已保存`);
            } else {
              console.log(`    · 日期 ${d || '未知'}，跳过`);
            }
          } else {
            // latest 模式：保存所有数据
            writer.addRow(row);
            console.log(`    ✓ 已保存 (日期: ${d || '未知'}, 内容: ${row.content.length} 字符)`);
            
            if (count > 0 && writer.count >= count) {
              stop = true;
              break;
            }
          }
          
          await sleep(1000); // 请求间隔
        } catch (err) {
          console.log(`    ✗ 失败: ${err.message}`);
        }
      }

      if (stop) break;

      // date 模式：本页最早日期已早于目标日期，停止翻页
      if (mode === 'date' && pageMinDate && pageMinDate < targetDate) {
        console.log(`  ✓ 本页最早 ${pageMinDate} 已早于 ${targetDate}，停止翻页`);
        break;
      }

      // 翻页
      if (!(await goToNextPage(page))) {
        console.log('  已到最后一页');
        break;
      }
    }

    console.log(`\n✅ 爬取完成，共 ${writer.count} 条`);
    console.log(`数据已保存到: ${OUTPUT_FILE}`);

  } finally {
    // 资源清理
    if (browser) await browser.close();
    try { chromeProcess.kill(); } catch {}
    await sleep(1500); // 等 Chrome 释放文件句柄
    try { execSync(`rm -rf "${userDataDir}"`); } catch {}
  }
}

// CLI 入口
if (require.main === module) {
  const args = process.argv.slice(2);

  if (args.includes('--info')) {
    console.log(JSON.stringify({
      name: '<name>',
      description: '<网站中文名>爬虫 (Chrome CDP)',
      modes: ['latest', 'yesterday', 'date'],
      outputFile: 'raw_data/<name>_data.json',
      antiBot: 'chrome-cdp'
    }));
    process.exit(0);
  }

  let mode = 'latest';
  let count = 0;
  let targetDate = null;

  const latestIdx = args.indexOf('--latest');
  const yesterdayIdx = args.indexOf('--yesterday');
  const dateIdx = args.indexOf('--date');

  if (yesterdayIdx >= 0) {
    mode = 'date';
    targetDate = getYesterday();
  } else if (dateIdx >= 0) {
    mode = 'date';
    targetDate = args[dateIdx + 1];
    if (!targetDate || !/^\d{4}-\d{2}-\d{2}$/.test(targetDate)) {
      console.error('错误: --date 参数格式必须是 YYYY-MM-DD');
      process.exit(1);
    }
  } else if (latestIdx >= 0) {
    mode = 'latest';
    count = parseInt(args[latestIdx + 1]) || 0;
    if (count <= 0) {
      console.error('错误: --latest 参数必须是正整数');
      process.exit(1);
    }
  } else {
    console.error('错误: 必须指定 --latest、--yesterday 或 --date 参数');
    process.exit(1);
  }

  scrape({ mode, count, targetDate }).catch(err => {
    console.error('爬虫执行失败:', err.message);
    process.exit(1);
  });
}
```

#### 代码生成规则（必须全部遵守）

1. **必须用 `findChrome()` 查找真实 Chrome 路径**
2. **必须用 `chromium.connectOverCDP()` 连接**，不要用 `chromium.launch()`
3. **Chrome 数据目录用临时目录**（`/tmp/<name>-chrome-${Date.now()}`），用完后清理
4. **调试端口用随机值**（`9222 + Math.floor(Math.random() * 1000)`），避免端口冲突
5. **`waitUntil: 'domcontentloaded'`**（不用 `networkidle`，有些网站永远 networkidle 不了）
6. **列表页加载后 `await sleep(5000)`** 等 JS 渲染
7. **详情页之间 `await sleep(1000~2000)`** 避免太快
8. **`--info` 必须输出合法 JSON**
9. **`--yesterday` / `--date` 模式必须客户端日期过滤**
10. **日期解析支持多种格式**：`2025年1月10日`、`2025-01-10`、`2025/01/10`
11. **每条 row 必须包含**: `publishTime`, `title`, `url`, `content`
12. **finally 块必须清理**：关闭 browser、kill Chrome 进程、删除临时数据目录
13. **WAF 检测**：检查页面长度，如果 < 2000 字符，保存到调试文件
14. **翻页上限**：设置 `MAX_PAGES = 15`，防止死循环
15. **URL 去重**：使用 `Set` 记录已访问的 URL
16. **提前终止**：date 模式下，如果本页最早日期已早于目标日期，停止翻页

### Phase 3: 测试验证（必须全部通过）

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
| 输出文件不存在 | 检查 Chrome 是否启动成功，检查 CDP 连接是否正常 |
| 缺少必需字段 | 检查 `fetchDetail()` 函数，确保返回所有必需字段 |
| content 过短 | 检查正文选择器是否正确，尝试其他提取策略 |
| content 等于 title | 详情页解析失败，用 `browser_snapshot` 重新分析页面结构 |
| scrapeTime 格式错误 | 使用 `formatScrapeTime()` 函数 |

**修复后必须重新运行验证脚本（3.2 + 3.3），直到全部通过。**

**3.5 最终测试**

验证通过后，再测试批量模式：

```bash
cd /Users/tristcz/project/ai_yuangong/scrapers
node scrape_<name>.js --latest 3
```

确保能正常爬取多条数据。

## 常见陷阱

### Chrome 找不到
- macOS: `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`
- Linux: `/usr/bin/google-chrome` 或 `/usr/bin/chromium-browser`
- 如果都没装，`process.exit(1)` 退出

### CDP 连接失败
- Chrome 启动需要 3 秒，`sleep(3000)` 不能省
- 端口冲突：用随机端口
- 如果 `connectOverCDP` 失败，检查 Chrome 是否真的启动了：`ps aux | grep chrome`

### 页面内容过短（WAF 拦截）
- 检查：`page.content().length < 2000`
- 保存到 `/tmp/<name>_debug.html` 用于调试
- 尝试增加等待时间：`await sleep(8000)`

### 临时目录没清理
- 每次运行创建 `/tmp/<name>-chrome-<timestamp>`
- finally 块必须 `rm -rf` 清理
- 清理前 `await sleep(1500)` 等 Chrome 释放文件句柄
- 否则磁盘会被撑满

### 批量运行时的浏览器争抢问题
- 多个 Playwright/CDP 爬虫并行运行时，会争抢浏览器实例
- 症状：批量运行时看到浏览器窗口在不同网站之间快速切换，导致点击操作失效
- 原因：多个爬虫共享浏览器实例或端口冲突
- 解决：`batch_task.py` 已添加 `PLAYWRIGHT_SEM` 互斥锁，确保同一时刻只有一个 Playwright 爬虫运行
- 注意：HTTP 爬虫不受此限制，可以并行运行

### 翻页失败
- JS 翻页：检查按钮选择器是否正确，检查是否被禁用
- URL 分页：检查分页 URL 格式（如 `index_2.shtml`）
- 设置翻页上限 `MAX_PAGES = 15`，防止死循环
- 翻页后检查列表内容是否变化

### 日期解析失败
- 支持多种格式：`2026年7月24日`、`2026-07-24`、`2026/07/24`
- 如果日期格式特殊，在 `parseDate()` 中添加新的正则表达式

## 全程不问用户任何问题

所有决策预设。遇到错误自己修复。
