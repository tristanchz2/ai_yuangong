---
name: gen-scraper-browser
description: "浏览器兜底爬虫生成。当 gen-scraper 失败后，用真实 Chrome + CDP 协议绕过反爬/WAF。"
version: 1.0.0
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
**用真实 Chrome 浏览器 + 远程调试端口**，这是光大银行（cebbank）验证过的方案。

原理：
1. 启动一个真实的 Chrome 浏览器进程（带 `--remote-debugging-port`）
2. Playwright 通过 CDP 协议连接到这个 Chrome
3. 对网站来说，这就是一个普通用户打开的 Chrome，不是自动化工具
4. 可以绕过绝大多数反爬/WAF/指纹检测

## 项目架构（必须遵守）

```
ai_yuangong/
├── scrapers/              # 爬虫文件（Node.js）
│   ├── utility/
│   │   ├── stripHtml.js   # HTML → 纯文本工具
│   │   └── JsonWriter.js  # 增量 JSON 写入器
│   └── scrape_<name>.js   # 每个站点一个爬虫脚本
├── raw_data/              # 爬虫原始输出 JSON
│   └── <name>_data.json
└── server.py              # FastAPI 主服务
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

### Phase 1: 用浏览器探索网站

**1.1 先在 Hermes 里打开网站**

```
browser_navigate(url=<目标URL>)
browser_snapshot(full=true)
```

观察页面结构：列表选择器、详情链接格式、正文区域。

**1.2 如果浏览器能看到数据，记录选择器**

重点记录：
- 列表项的 CSS 选择器（如 `div.gg_nr a`）
- 详情页的正文选择器（如 `div.xilan_con`、`div.article-content`）
- 日期格式和位置
- 详情 URL 模式

**1.3 点击一个详情链接，进入详情页**

```
browser_click(ref=<详情链接ref>)
browser_snapshot(full=true)
```

记录详情页的正文提取选择器。

### Phase 2: 生成爬虫代码

用 `write_file` 写入 `scrapers/scrape_<name>.js`。

**🚨 必须使用 Chrome CDP 模式，参考模板 `templates/playwright-cdp-scraper.js`。**

**关键代码结构：**

```javascript
const { chromium } = require('playwright');
const { JsonWriter } = require('./utility/JsonWriter');
const { execSync, spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const OUTPUT_FILE = path.join(__dirname, '..', 'raw_data', '<name>_data.json');

// ====== 找到真实 Chrome ======
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

// ====== 主流程 ======
async function scrape(options = {}) {
  const { latest = 0, date = null } = options;
  
  const chromePath = findChrome();
  if (!chromePath) {
    console.error('找不到 Chrome 浏览器');
    process.exit(1);
  }

  // 启动 Chrome（随机端口避免冲突）
  const debugPort = 9222 + Math.floor(Math.random() * 1000);
  const userDataDir = `/tmp/<name>-chrome-${Date.now()}`;

  const chromeProcess = spawn(chromePath, [
    `--remote-debugging-port=${debugPort}`,
    `--user-data-dir=${userDataDir}`,
    '--no-first-run',
    '--no-default-browser-check',
  ], {
    stdio: 'ignore',
    detached: true,
  });

  await sleep(3000);  // 等 Chrome 启动

  let browser = null;
  try {
    // 通过 CDP 连接到 Chrome
    browser = await chromium.connectOverCDP(`http://localhost:${debugPort}`);
    const contexts = browser.contexts();
    const context = contexts[0] || await browser.newContext();
    const page = context.pages()[0] || await context.newPage();

    // 访问列表页
    await page.goto(LIST_URL, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await sleep(5000);  // 等页面渲染完成

    // 提取列表（根据 Phase 1 找到的选择器）
    const links = await page.evaluate(() => {
      const results = [];
      document.querySelectorAll('<列表选择器>').forEach(el => {
        // ... 提取 title, url
      });
      return results;
    });

    // 逐条访问详情页
    const writer = new JsonWriter(OUTPUT_FILE, { source: '<name>', scrapeTime: formatScrapeTime() });

    for (let i = 0; i < links.length; i++) {
      await page.goto(links[i].url, { waitUntil: 'domcontentloaded', timeout: 30000 });
      await sleep(2000);

      const detail = await page.evaluate(() => {
        // 根据 Phase 1 找到的正文选择器提取
        const contentEl = document.querySelector('<正文选择器>');
        let content = '';
        if (contentEl) {
          content = Array.from(contentEl.querySelectorAll('p'))
            .map(p => p.innerText.trim())
            .filter(t => t.length > 0)
            .join('\n\n');
        }
        return { content, /* title, date */ };
      });

      writer.addRow({ publishTime, title, url, content });
    }

  } finally {
    if (browser) await browser.close();
    try { chromeProcess.kill(); } catch {}
    try { execSync(`rm -rf "${userDataDir}"`); } catch {}
  }
}
```

**代码生成规则：**

1. 必须用 `findChrome()` 查找真实 Chrome 路径
2. 必须用 `chromium.connectOverCDP()` 连接，不要用 `chromium.launch()`
3. Chrome 数据目录用临时目录（`/tmp/<name>-chrome-${Date.now()}`），用完后清理
4. 调试端口用随机值（`9222 + Math.random() * 1000`），避免端口冲突
5. `waitUntil: 'domcontentloaded'`（不用 `networkidle`，有些网站永远 networkidle 不了）
6. 列表页加载后 `await sleep(5000)` 等 JS 渲染
7. 详情页之间 `await sleep(1000~2000)` 避免太快
8. `--info` 必须输出合法 JSON
9. `--yesterday` / `--date` 模式必须客户端日期过滤
10. 日期解析支持多种格式：`2025年1月10日`、`2025-01-10`、`2025/01/10`
11. 每条 row 必须包含: `publishTime`, `title`, `url`, `content`
12. finally 块必须清理：关闭 browser、kill Chrome 进程、删除临时数据目录

### Phase 3: 测试

```bash
node scrapers/scrape_<name>.js --info
node scrapers/scrape_<name>.js --latest 1
```

验证：
1. `--info` 输出合法 JSON
2. `--latest 1` 能成功爬取至少 1 条数据
3. `raw_data/<name>_data.json` 存在且 `rows` 非空
4. content 字段有实际内容（不是空或只有标题）

## 常见陷阱

### Chrome 找不到
- macOS: `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`
- Linux: `google-chrome` 或 `chromium-browser`
- 如果都没装，`process.exit(1)` 退出

### CDP 连接失败
- Chrome 启动需要 3 秒，`sleep(3000)` 不能省
- 端口冲突：用随机端口
- 如果 `connectOverCDP` 失败，检查 Chrome 是否真的启动了：`ps aux | grep chrome`

### 页面内容过短
- 可能是 WAF 拦截了 Chrome（少见但有可能）
- 检查：`page.content().length < 2000` → 保存到 `/tmp/<name>_debug.html` 用于调试

### 临时目录没清理
- 每次运行创建 `/tmp/<name>-chrome-<timestamp>`
- finally 块必须 `rm -rf` 清理
- 否则磁盘会被撑满

## 全程不问用户任何问题

所有决策预设。遇到错误自己修复。
