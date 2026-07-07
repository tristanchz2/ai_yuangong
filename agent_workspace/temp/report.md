# 网页侦察报告：中国邮政储蓄银行采购平台

**目标 URL**: `https://cg.psbc.com/cms/default/webfile/1ywgg2/index.html`  
**侦察时间**: 2026-07-07  
**侦察工具**: browser-use MCP (Playwright Chromium)

---

## 1. 页面基本信息

| 项目 | 值 |
|------|-----|
| URL | `https://cg.psbc.com/cms/default/webfile/1ywgg2/index.html` |
| 域名 | `cg.psbc.com`（中国邮政储蓄银行采购平台） |
| Web 服务器 | **nginx** |
| 页面标题 | 空（未返回有效 HTML） |
| 页面内容 | 空（body 无任何 DOM 元素） |
| HTTP 状态码 | **400 Bad Request**（浏览器访问）/ **412 Precondition Failed**（curl 访问） |

---

## 2. 反爬机制分析

### 2.1 WAF 类型：**瑞数信息 (Ruishu Information) 动态防护**

该网站使用了**瑞数信息**的 JS 挑战（JS Challenge）反爬方案，这是国内金融/政企网站常用的 WAF 产品。

### 2.2 防护流程

```
客户端请求 → 服务器返回 412 + JS 挑战页面
                ↓
        浏览器执行混淆 JS（~241KB）
                ↓
        JS 收集浏览器指纹 + 环境检测
                ↓
        生成验证 Cookie（V3iEwBUtWULVO=...）
                ↓
        携带 Cookie 重新请求 → 服务器验证通过 → 返回真实页面
```

### 2.3 关键证据

| 指标 | 详情 |
|------|------|
| **WAF Cookie** | `V3iEwBUtWULVO` / `V3iEwBUtWULVP`（名称动态变化） |
| **Cookie 属性** | `Path=/; expires=10年后; Secure; HttpOnly` |
| **JS 挑战脚本** | `/guVs64CoM36R/6DSo9w8Prxo9.2a95215.js`（~241KB，路径动态变化） |
| **全局变量** | `$_ts`（瑞数特征变量） |
| **入口函数** | `_$bt()`（瑞数特征函数） |
| **混淆特征** | 变量名如 `_$im`, `$_Z`, `_$bX`, `_$lD` 等，典型的瑞数混淆风格 |
| **响应头** | `Cache-Control: no-store`, `Pragma: no-cache`, `Expires: 当前时间` |

### 2.4 JS 挑战脚本特征

```javascript
// 瑞数特征代码片段（来自挑战页面）
$_ts = window['$_ts'];
if (!$_ts) $_ts = {};
$_ts.nsd = 71464;
$_ts.cd = "qtmxrpAloALrWkZccGAaHaVEqqQncqGqruE5cqqtqGQnm1VB...";
if ($_ts.lcd) $_ts.lcd();

// 外部加载混淆 JS
<script src="/guVs64CoM36R/6DSo9w8Prxo9.2a95215.js"></script>

// 最终执行
_$bt();
```

### 2.5 浏览器指纹检测

瑞数 JS 挑战会检测以下环境信息：
- `navigator.userAgent`
- `navigator.platform`
- `screen.width/height`
- `window` 对象完整性
- Canvas/WebGL 指纹
- 浏览器插件列表
- 时区、语言设置
- 鼠标/键盘事件行为

---

## 3. 网络请求分析

| 请求 | 状态 | 说明 |
|------|------|------|
| `GET /cms/default/webfile/1ywgg2/index.html` | 400/412 | 主页面请求被 WAF 拦截 |
| `GET /guVs64CoM36R/6DSo9w8Prxo9.2a95215.js` | 200 | JS 挑战脚本（241KB） |
| `GET data:image/png;base64,...` | 200 | 1x1 透明像素（追踪用） |

---

## 4. 当前浏览器访问结果

- **截图**: 完全空白页面（白色）
- **DOM**: 无任何元素（`<body>` 为空）
- **Console**: 3 条 `Failed to load resource: 400 (Bad Request)` 错误
- **原因**: browser-use 的 Playwright 环境中，瑞数 JS 挑战可能因以下原因未通过：
  1. User-Agent 包含 `QoderCN/1.5.0 Electron/37.7.0`，被识别为非标准浏览器
  2. JS 挑战检测到自动化环境（Playwright）
  3. 缺少真实用户交互行为

---

## 5. 爬虫开发建议

### 5.1 方案 A：Playwright + 真实浏览器（推荐）

```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)  # 有头模式
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/138.0.0.0 Safari/537.36",
        viewport={"width": 1920, "height": 1080},
    )
    page = context.new_page()
    page.goto("https://cg.psbc.com/cms/default/webfile/1ywgg2/index.html")
    page.wait_for_timeout(5000)  # 等待 JS 挑战完成
    # 等待真实内容加载
    page.wait_for_selector("目标选择器", timeout=10000)
    content = page.content()
```

**关键点**：
- 使用**有头模式**（`headless=False`），瑞数会检测 headless 环境
- 使用标准 Chrome UA，避免 Electron/自动化工具标识
- 等待足够时间让 JS 挑战完成（通常 2-5 秒）
- 可能需要 `playwright-stealth` 插件来隐藏自动化特征

### 5.2 方案 B：逆向 JS 挑战（高难度）

逆向瑞数 JS 挑战需要：
1. 分析 241KB 混淆代码的执行逻辑
2. 模拟浏览器环境执行 JS
3. 提取生成的 Cookie 值
4. 携带 Cookie 请求真实页面

**不推荐**，瑞数会定期更新混淆逻辑和检测规则。

### 5.3 方案 C：使用 browser-use Agent

利用已配置好的 `browser_executor.py`，让 AI Agent 自动操作浏览器：

```bash
echo "打开 https://cg.psbc.com/cms/default/webfile/1ywgg2/index.html，等待页面加载完成后，提取页面中的公告列表数据" > prompt.txt
python3 agent_workspace/tools/browser_executor.py \
  --prompt-file prompt.txt \
  --output-file result.txt
```

**注意**：需要在 `browser_executor.py` 中配置标准 Chrome UA，避免被识别为自动化工具。

### 5.4 必须处理的反爬要点

| 要点 | 处理方式 |
|------|---------|
| User-Agent | 使用真实 Chrome UA，不含自动化标识 |
| JS 挑战 | 必须等待 JS 执行完成（2-5秒） |
| Headless 检测 | 使用有头模式或 stealth 插件 |
| Cookie 管理 | 自动处理 WAF Cookie 的生成和携带 |
| 请求频率 | 控制请求间隔，避免触发频率限制 |
| IP 限制 | 可能需要代理 IP 池 |

---

## 6. 截图

- 目标页面截图: [screenshot.png](./screenshot.png)（空白页面，被 WAF 拦截）
- 根页面截图: [screenshot_root.png](./screenshot_root.png)（同样被拦截）

---

## 7. 总结

该网站使用**瑞数信息 WAF** 进行动态防护，核心机制是 **JS 挑战 + 浏览器指纹检测**。直接 HTTP 请求（curl/requests）无法获取内容，必须使用真实浏览器环境执行 JS 挑战后才能访问。建议采用 **Playwright 有头模式 + stealth 插件** 或 **browser-use Agent** 方案进行爬虫开发。
