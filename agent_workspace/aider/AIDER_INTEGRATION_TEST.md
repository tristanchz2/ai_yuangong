# 🧪 Aider 爬虫生成器 — 端到端测试指南

## 📌 前置条件

确保以下服务已启动：

```bash
# 1. 浏览器 MCP 服务器（后台运行）
cd /Users/tristcz/project/ai_yuangong
source venv-browser/bin/activate
python3 agent_workspace/tools/browser_mcp_server.py --sse --port 8765 &

# 2. 验证服务正常
curl http://localhost:8765/sse
```

---

## 🎯 测试场景 1：简单列表页（无 API）

**目标网站**：https://example.com/news（假设）

**测试步骤**：

### Step 1: 启动 Aider

```bash
cd /Users/tristcz/project/ai_yuangong
source venv-aider/bin/activate
aider \
  --model qwen3.7-plus \
  --openai-api-key sk-sp-19999d7535d94b6cae08afb54c4f1875 \
  --openai-api-base https://coding.dashscope.aliyuncs.com/v1 \
  --tools agent_workspace/aider/*.yml \
  --no-auto-commits
```

### Step 2: 给 Aider 指令

```
帮我写一个爬虫，爬取 https://example.com/news 的新闻列表。
每条新闻包含：标题、链接、发布日期。
按照 SPIDER_GENERATOR_WORKFLOW.md 的流程执行。
```

### Step 3: 观察 Aider 自动执行

Aider 应该自动：

1. **侦察阶段**
   ```
   → browser_intercept '{"resource_types": ["xhr", "fetch"]}'
   → browser_navigate '{"url": "https://example.com/news"}'
   → browser_wait '{"selector": ".news-list", "timeout": 10000}'
   → browser_get_text '{}'
   → browser_network '{}'
   ```

2. **分析结果**
   - 判断是否有 API
   - 识别选择器
   - 确定分页方式

3. **生成代码**
   - 复制模板
   - 修改 CONFIG
   - 注册到 run.py

4. **测试运行**
   ```bash
   python3 run.py example --latest 5
   ```

### Step 4: 验证输出

```bash
cat raw_data/example_news.json | jq '.[0]'
```

预期输出：
```json
{
  "title": "示例新闻标题",
  "link": "https://example.com/news/123",
  "date": "2024-01-01"
}
```

---

## 🎯 测试场景 2：API 直连模式

**目标网站**：有公开 API 的网站（如 GitHub API）

**测试指令**：

```
帮我写一个爬虫，从 https://api.github.com/repos/facebook/react/issues 
获取最新的 10 个 issue。
使用 API 直连模式。
```

**预期行为**：
- Aider 识别这是 API URL
- 直接使用 `browser_http_request` 测试
- 使用 `scrape_template_api_direct.js` 模板
- 生成简洁的 HTTP 爬虫代码

---

## 🎯 测试场景 3：复杂反爬网站

**目标网站**：https://cg.psbc.com/cms/default/webfile/1ywgg2/index.html

**测试指令**：

```
帮我侦察这个网站：https://cg.psbc.com/cms/default/webfile/1ywgg2/index.html
分析它的反爬机制，并告诉我是否能爬取。
如果不能直接爬，有没有替代方案？
```

**预期行为**：
- Aider 用 `browser_navigate` 访问
- 发现瑞数 WAF（412 状态码）
- 用 `browser_executor.py` 进行高级侦察
- 报告反爬特征
- 建议替代方案（如寻找其他数据源）

---

## 🔍 调试技巧

### 问题 1：Aider 没有调用浏览器工具

**检查**：
```bash
# 确认 YAML 文件被加载
aider --help | grep -i tool

# 手动测试工具
python3 agent_workspace/tools/browser_mcp_cli.py navigate_page '{"url": "https://example.com"}'
```

**解决**：
- 确保 `--tools agent_workspace/aider/*.yml` 参数正确
- 检查 YAML 语法是否正确

---

### 问题 2：浏览器工具返回错误

**常见错误**：
```
Error: Target page, context or browser has been closed
```

**原因**：浏览器进程未保持状态

**解决**：
```bash
# 确保使用 SSE 模式启动
pkill -f browser_mcp_server.py
python3 agent_workspace/tools/browser_mcp_server.py --sse --port 8765 &

# 验证服务运行
ps aux | grep browser_mcp_server
```

---

### 问题 3：生成的爬虫运行失败

**调试步骤**：

1. **检查选择器**
   ```bash
   # 用浏览器工具验证选择器
   python3 agent_workspace/tools/browser_mcp_cli.py evaluate_script \
     '{"function": "() => document.querySelectorAll(\".news-item\").length"}'
   ```

2. **检查网络请求**
   ```bash
   # 查看拦截的请求
   python3 agent_workspace/tools/browser_mcp_cli.py list_network_requests \
     '{"include_headers": true}'
   ```

3. **手动运行爬虫**
   ```bash
   node scrapers/scrape_example.js --latest 1
   ```

---

## ✅ 成功标准

测试通过的条件：

1. ✅ Aider 能自动调用浏览器工具侦察页面
2. ✅ Aider 能正确分析页面结构
3. ✅ Aider 能选择合适的模板
4. ✅ 生成的爬虫能成功运行
5. ✅ 输出的 JSON 格式正确
6. ✅ 支持 `--latest N` 和 `--yesterday` 两种模式

---

## 📊 性能基准

| 指标 | 目标值 |
|------|--------|
| 侦察时间 | < 30 秒 |
| 代码生成时间 | < 60 秒 |
| 首次测试成功率 | > 80% |
| 简单网站全自动成功率 | > 90% |
| 复杂网站（需人工干预） | < 20% |

---

## 🚀 快速开始（一键测试）

创建一个测试脚本：

```bash
#!/bin/bash
# test_aider_spider_generator.sh

echo "🚀 启动浏览器 MCP 服务器..."
pkill -f browser_mcp_server.py 2>/dev/null
python3 agent_workspace/tools/browser_mcp_server.py --sse --port 8765 &
sleep 3

echo "✅ 服务器已启动，PID: $!"

echo ""
echo "📝 现在可以启动 Aider 进行测试："
echo ""
echo "cd /Users/tristcz/project/ai_yuangong"
echo "source venv-aider/bin/activate"
echo "aider \\"
echo "  --model qwen3.7-plus \\"
echo "  --openai-api-key YOUR_KEY \\"
echo "  --openai-api-base https://coding.dashscope.aliyuncs.com/v1 \\"
echo "  --tools agent_workspace/aider/*.yml \\"
echo "  --no-auto-commits"
echo ""
echo "然后对 Aider 说："
echo '"帮我写一个爬虫，爬取 https://example.com/news 的新闻列表"'
```

运行：
```bash
chmod +x test_aider_spider_generator.sh
./test_aider_spider_generator.sh
```

---

## 📚 相关文档

- [SPIDER_GENERATOR_WORKFLOW.md](SPIDER_GENERATOR_WORKFLOW.md) — 完整工作流程
- [browser_mcp_server.py](../tools/browser_mcp_server.py) — MCP 服务器源码
- [templates/](../templates/) — 爬虫模板库

---

**祝测试顺利！** 🎉
