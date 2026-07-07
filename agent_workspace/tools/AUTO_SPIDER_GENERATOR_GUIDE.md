# 🤖 智能爬虫生成器使用指南

## 📌 功能特性

✅ **全自动工作流**：从侦察到生成到测试，一气呵成  
✅ **自动修正**：测试失败时自动修复代码（最多 3 轮）  
✅ **智能决策**：自动判断使用浏览器自动化还是直接 API 调用  
✅ **人工介入**：实在搞不定才找你  

---

## 🚀 快速开始

### Step 1: 启动浏览器 MCP 服务器

```bash
cd /Users/tristcz/project/ai_yuangong
source venv-browser/bin/activate
python3 agent_workspace/tools/browser_mcp_server.py --sse --port 8765 &
echo "✅ 浏览器服务已启动"
```

### Step 2: 运行自动生成器

```bash
cd /Users/tristcz/project/ai_yuangong
source venv-aider/bin/activate

# 基本用法
python3 agent_workspace/tools/auto_spider_generator.py https://example.com/news

# 指定输出文件
python3 agent_workspace/tools/auto_spider_generator.py https://example.com/news scrapers/scrape_example.js
```

---

## 📊 工作流程

```
┌─────────────────────────────────────────┐
│  阶段 1: 侦察页面结构                     │
│  - 启动请求拦截                          │
│  - 导航到目标页面                        │
│  - 分析 API 端点                         │
│  - 识别反爬机制                          │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│  阶段 2: 生成爬虫代码                     │
│  - 选择技术方案 (Browser/API)            │
│  - 生成完整代码                          │
│  - 添加错误处理                          │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│  阶段 3: 测试爬虫                        │
│  - 安装依赖                              │
│  - 运行测试 (--latest 2)                 │
│  - 验证输出数据                          │
└──────────────┬──────────────────────────┘
               │
        ┌──────┴──────┐
        │  成功？      │
        └──┬─────┬────┘
       Yes │     │ No
           │     ▼
           │  ┌─────────────────────────┐
           │  │ 阶段 4: 自动修正         │
           │  │ - 分析错误              │
           │  │ - 修复代码              │
           │  │ - 重新测试              │
           │  └──────┬──────────────────┘
           │         │
           │    ┌────┴────┐
           │    │ 第几轮？ │
           │    └──┬──┬───┘
           │   <3 │  │ =3
           │      │  │
           │      ▼  ▼
           │   继续  求助用户
           │   修正   
           │
           ▼
    ┌──────────────────┐
    │ 🎉 成功！         │
    │ 输出爬虫文件       │
    └──────────────────┘
```

---

## 🎯 使用示例

### 示例 1: 简单新闻列表页

```bash
python3 agent_workspace/tools/auto_spider_generator.py \
  https://www.example.com/news
```

**预期输出**：
```
🕷️  智能爬虫生成器
============================================================
目标 URL: https://www.example.com/news
输出文件: scrapers/scrape_www_example_com.js
最大修正轮数: 3

🔍 检查浏览器 MCP 服务器...
✅ 浏览器 MCP 服务器正在运行

============================================================
📊 阶段 1: 侦察页面结构
============================================================
🤖 Aider 正在侦察页面...
✅ 侦察完成

📋 侦察结果:
  - 有反爬机制: False
  - 推荐方式: browser
  - API 端点: 0 个

============================================================
💻 阶段 2: 生成爬虫代码
============================================================
🤖 Aider 正在生成爬虫代码（browser 模式）...
✅ 爬虫代码已生成: scrapers/scrape_www_example_com.js

============================================================
🧪 阶段 3: 测试爬虫
============================================================
📦 安装依赖...
🚀 运行测试（抓取 2 条数据）...
✅ 测试成功！抓取到 2 条数据
   第一条数据: {"title": "Example News 1", "link": "https://...", "date": "2024-01-01"}

============================================================
🎉 爬虫生成成功！
============================================================
文件位置: scrapers/scrape_www_example_com.js
数据样例: {...}

完整测试命令:
  node scrapers/scrape_www_example_com.js --latest 10
```

---

### 示例 2: 有 API 的网站

```bash
python3 agent_workspace/tools/auto_spider_generator.py \
  https://api.example.com/items \
  scrapers/scrape_api_items.js
```

---

### 示例 3: 有反爬的网站

```bash
python3 agent_workspace/tools/auto_spider_generator.py \
  https://cg.psbc.com/cms/default/webfile/1ywgg2/index.html
```

自动生成器会：
1. 检测到瑞数 WAF
2. 使用浏览器自动化方案
3. 注入 stealth 脚本
4. 模拟真实用户行为

---

## ⚙️ 配置选项

编辑 `auto_spider_generator.py` 顶部的配置：

```python
MAX_RETRY_ROUNDS = 3  # 最大自动修正轮数（默认 3）
BROWSER_MCP_URL = "http://localhost:8765/sse"
AIDER_VENV = "venv-aider/bin/activate"
PROJECT_ROOT = "/Users/tristcz/project/ai_yuangong"
```

---

## 🔧 故障排查

### 问题 1: 浏览器 MCP 服务器未运行

**症状**：
```
❌ 浏览器 MCP 服务器未运行
   请先启动: python3 agent_workspace/tools/browser_mcp_server.py --sse --port 8765 &
```

**解决**：
```bash
source venv-browser/bin/activate
python3 agent_workspace/tools/browser_mcp_server.py --sse --port 8765 &
```

---

### 问题 2: Aider 无法连接 MCP

**症状**：Aider 报错找不到 browser-use 工具

**解决**：
1. 确认浏览器 MCP 服务器在运行
2. 检查端口 8765 是否被占用：`lsof -ti:8765`
3. 查看日志：`tail -f /tmp/browser_mcp.log`

---

### 问题 3: 自动修正 3 轮后仍然失败

**症状**：
```
❌ 经过 3 轮自动修正仍然失败

📞 需要人工介入
```

**解决**：
1. 手动检查生成的爬虫代码
2. 手动测试：`node scrapers/scrape_xxx.js --latest 5`
3. 使用 Aider 交互式调试：
   ```bash
   source venv-aider/bin/activate
   aider scrapers/scrape_xxx.js
   ```
4. 查看浏览器日志：`tail -f /tmp/browser_mcp.log`

---

## 📝 生成的爬虫文件结构

```javascript
/**
 * 爬虫名称: Example News Scraper
 * 目标网站: https://example.com/news
 * 生成时间: 2024-01-01
 * 技术方案: Browser Automation (Playwright)
 */

const playwright = require('playwright');
const fs = require('fs');
const path = require('path');

// 配置
const CONFIG = {
    targetUrl: 'https://example.com/news',
    outputDir: 'raw_data',
    outputFile: 'example_news.json',
    // ...
};

// 主函数
async function main() {
    // ...
}

main().catch(console.error);
```

---

## 🎓 高级用法

### 自定义侦察 Prompt

修改 `reconnaissance()` 函数中的 `recon_prompt`，添加特定的侦察要求。

### 自定义代码生成 Prompt

修改 `generate_spider_code()` 函数中的 `spider_prompt`，指定特定的代码风格或功能。

### 调整测试参数

修改 `test_spider()` 函数中的测试数据量（默认 `--latest 2`）。

---

## 💡 最佳实践

1. **先侦察再生成**：让自动生成器先了解页面结构
2. **小步测试**：先用 `--latest 2` 测试，成功后再全量爬取
3. **查看日志**：遇到问题时查看 `/tmp/browser_mcp.log`
4. **人工审核**：自动生成的代码建议人工 review 后再投入使用
5. **增量开发**：复杂网站可以分多次生成，逐步完善

---

## 🚀 下一步

生成成功后：

1. **完整测试**：
   ```bash
   node scrapers/scrape_xxx.js --latest 50
   ```

2. **集成到 run.py**：
   ```python
   # 在 run.py 中添加新的爬虫入口
   elif spider_name == 'xxx':
       os.system(f'node scrapers/scrape_xxx.js {args}')
   ```

3. **定时任务**：
   ```bash
   crontab -e
   # 每天凌晨 2 点运行
   0 2 * * * cd /path/to/project && node scrapers/scrape_xxx.js --yesterday
   ```

---

## ❓ 常见问题

**Q: 为什么需要浏览器 MCP 服务器？**  
A: 因为 Aider 0.86.x 不支持 MCP，我们需要一个中间层来提供浏览器自动化工具。

**Q: 自动修正最多几轮？**  
A: 默认 3 轮，可以在配置中修改 `MAX_RETRY_ROUNDS`。

**Q: 如果自动生成的代码不满意怎么办？**  
A: 可以手动修改，或者用 Aider 交互式调试：`aider scrapers/scrape_xxx.js`

**Q: 支持哪些类型的网站？**  
A: 理论上支持所有网站，包括：
- 静态 HTML 页面
- 动态渲染页面（SPA）
- 有 API 的网站
- 有反爬机制的网站（需要额外配置）

---

## 🎉 开始使用吧！

```bash
# 1. 启动浏览器服务
source venv-browser/bin/activate
python3 agent_workspace/tools/browser_mcp_server.py --sse --port 8765 &

# 2. 运行自动生成器
source venv-aider/bin/activate
python3 agent_workspace/tools/auto_spider_generator.py https://your-target-url.com

# 3. 等待完成，享受成果！
```

祝你爬虫愉快！🕷️✨
