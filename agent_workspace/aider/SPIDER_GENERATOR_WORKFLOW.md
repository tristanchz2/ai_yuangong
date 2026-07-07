# 🕷️ 智能爬虫生成工作流

**目标**：给 Aider 一个网址，它就能全自动化写好完整的爬虫代码。

---

## 📋 工作流程（4 步）

### Step 1: 侦察页面结构 🔍

使用浏览器工具访问目标 URL，分析页面结构和反爬机制。

```bash
# 启动请求拦截（捕获 API 调用）
browser_intercept '{"resource_types": ["xhr", "fetch"]}'

# 导航到目标页面
browser_navigate '{"url": "TARGET_URL"}'

# 等待页面加载
browser_wait '{"selector": ".main-content", "timeout": 10000}'

# 滚动触发懒加载（如果有）
browser_scroll '{"to_bottom": true}'

# 查看拦截的 API 请求
browser_network '{"include_headers": true, "resource_types": ["xhr"]}'

# 获取页面文本内容
browser_get_text '{}'

# 截图（可选，用于视觉确认）
browser_screenshot '{"full_page": true}'
```

**侦察要点**：
- ✅ 页面是否有反爬机制（WAF、JS 挑战、验证码）
- ✅ 数据是通过 HTML 渲染还是 API 加载
- ✅ 列表项的选择器是什么（class/id）
- ✅ 分页是如何实现的（URL 参数 / 按钮点击）
- ✅ 是否有隐藏的 API 接口

---

### Step 2: 选择最佳抓取策略 🎯

根据侦察结果，选择以下策略之一：

#### 策略 A：API 直连（最优）
**适用条件**：
- `browser_network` 发现了返回 JSON 的 API 请求
- API 无需复杂认证或签名

**优势**：速度快、稳定性高、反爬风险低

**行动**：
```bash
# 直接测试 API
browser_http_request '{"url": "DISCOVERED_API_URL", "method": "GET"}'
```

如果成功 → 使用 `scrape_template_api_direct.js` 模板

---

#### 策略 B：浏览器自动化（次优）
**适用条件**：
- 数据嵌入在 HTML 中，无公开 API
- 或者 API 有复杂的签名/加密

**行动**：
- 识别列表项选择器
- 确定分页方式
- 使用 `scrape_template_list_page.js` 模板

---

#### 策略 C：混合模式（复杂场景）
**适用条件**：
- 列表页是 HTML，详情页需要调用 API
- 或者需要登录 + Cookie 保持

**行动**：
- 先用浏览器获取列表
- 再用 HTTP 请求获取详情

---

### Step 3: 生成爬虫代码 💻

根据选择的策略，复制对应模板并填充配置：

```bash
# 示例：基于列表页模板生成
cp templates/scrape_template_list_page.js scrapers/scrape_newsite.js

# 然后用 SearchReplace 修改 CONFIG 部分
```

**必须修改的配置**：
- `listUrl` — 列表页 URL（含分页参数）
- `itemSelector` — 列表项容器选择器
- `fields.*` — 各字段的 CSS 选择器
- `outputFile` — 输出文件路径

**注册到 run.py**：
```python
# 在 run.py 中添加注册
def newsite_run(args, capture=False):
    cmd = build_node_cmd('scrape_newsite.js')
    if args.yesterday:
        cmd.append('--yesterday')
    else:
        cmd += ['--latest', str(args.latest)]
    return run_script(cmd, 'newsite', capture=capture)

register('newsite', '新网站爬虫描述', newsite_run)
```

---

### Step 4: 测试运行 🧪

```bash
# 测试爬取最新 5 条
python3 run.py newsite --latest 5

# 检查输出文件
cat raw_data/newsite_data.json | head -50

# 如果成功，测试昨天数据模式
python3 run.py newsite --yesterday
```

**失败排查**：
- ❌ 选择器错误 → 用 `browser_eval` 重新验证选择器
- ❌ 反爬拦截 → 检查 User-Agent、添加延迟、使用 stealth
- ❌ 分页失效 → 调整分页逻辑（URL 参数 vs 按钮点击）

---

## 🛠️ 工具速查表

| 工具 | 用途 | 示例 |
|------|------|------|
| `browser_navigate` | 打开页面 | `{"url": "https://example.com"}` |
| `browser_intercept` | 启动 API 拦截 | `{"resource_types": ["xhr"]}` |
| `browser_network` | 查看拦截的请求 | `{"include_headers": true}` |
| `browser_get_text` | 提取页面文本 | `{}` |
| `browser_snapshot` | 获取 DOM 树 | `{}` |
| `browser_screenshot` | 截图 | `{"full_page": true}` |
| `browser_eval` | 执行 JS | `{"function": "() => document.title"}` |
| `browser_scroll` | 滚动页面 | `{"to_bottom": true}` |
| `browser_http_request` | 直接调 API | `{"url": "...", "method": "GET"}` |

---

## 📝 完整示例（从 URL 到爬虫）

**用户输入**：
> 帮我写一个爬虫，爬取 https://example.com/news 的新闻列表

**Aider 自动执行**：

1. **侦察阶段**
   ```bash
   browser_intercept '{"resource_types": ["xhr", "fetch"]}'
   browser_navigate '{"url": "https://example.com/news"}'
   browser_wait '{"selector": ".news-list", "timeout": 10000}'
   browser_scroll '{"to_bottom": true}'
   browser_network '{"include_headers": false}'
   browser_get_text '{}'
   ```

2. **分析结果**
   - 发现 API: `https://api.example.com/news?page=1&pageSize=20`
   - 返回 JSON 格式，包含 title/date/link 字段
   - 无反爬机制

3. **选择策略**
   - 策略 A：API 直连

4. **生成代码**
   ```bash
   # 复制模板
   cp templates/scrape_template_api_direct.js scrapers/scrape_example.js
   
   # 修改 CONFIG
   baseUrl = 'https://api.example.com/news'
   outputFile = '../raw_data/example_news.json'
   
   # 注册到 run.py
   ```

5. **测试**
   ```bash
   python3 run.py example --latest 5
   ```

6. **完成！**

---

## ⚠️ 常见陷阱

### 1. 瑞数 WAF / JS 挑战
**特征**：返回 412 状态码，页面显示加载中...
**解决**：
- 使用 `browser_executor.py` 进行高级侦察
- 可能需要 playwright-stealth 插件
- 或者寻找替代数据源

### 2. 动态选择器
**特征**：每次刷新 class 名称都变化
**解决**：
- 使用属性选择器：`[data-id="xxx"]`
- 或者 XPath：`//div[contains(text(), "标题")]`

### 3. 无限滚动
**特征**：没有分页按钮，滚动到底部自动加载
**解决**：
- 多次调用 `browser_scroll '{"to_bottom": true}'`
- 每次滚动后等待新内容加载

### 4. 登录限制
**特征**：需要先登录才能看到数据
**解决**：
- 手动登录后用 `browser_cookies '{"action": "get"}'` 导出 Cookie
- 在爬虫中用 `set_cookie` 注入

---

## 🎓 进阶技巧

### 技巧 1：并行侦察多个页面
```bash
# 同时打开多个标签页
browser_pages '{"action": "new", "url": "https://example.com/page1"}'
browser_pages '{"action": "new", "url": "https://example.com/page2"}'
browser_pages '{"action": "select", "page_index": 0}'
```

### 技巧 2：模拟真实用户行为
```bash
# 随机延迟
browser_eval '{"function": "() => new Promise(r => setTimeout(r, Math.random() * 2000 + 1000))"}'

# 模拟鼠标移动
browser_eval '{"function": "() => { const e = new MouseEvent(\"mousemove\", {bubbles:true}); document.body.dispatchEvent(e); }"}'
```

### 技巧 3：提取隐藏字段
```bash
# 获取 data-* 属性
browser_eval '{"function": "() => Array.from(document.querySelectorAll(\".item\")).map(el => ({id: el.dataset.id, url: el.dataset.url}))"}'
```

---

## 🚀 开始使用

现在你可以这样对 Aider 说：

> "帮我写一个爬虫，爬取 https://target-site.com/list 的数据"

Aider 会自动：
1. 用浏览器工具侦察页面
2. 分析数据结构
3. 选择合适的模板
4. 生成完整代码
5. 测试运行

**祝你爬虫愉快！** 🕸️
