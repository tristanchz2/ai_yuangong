# 两层爬虫生成系统架构

## 系统分层

```
┌─────────────────────────────────────┐
│  Layer 1: gen-scraper (HTTP-only)   │
│  - Node.js http/https 模块          │
│  - 可处理：API、HTML解析、加密解密  │
│  - 失败条件：瑞数WAF等需要JS执行    │
└─────────────────────────────────────┘
              ↓ (HTTP方案失败时)
┌─────────────────────────────────────┐
│  Layer 2: gen-scraper-browser       │
│  (Chrome CDP with real browser)     │
│  - Playwright + connectOverCDP      │
│  - 绕过：WAF、JS挑战、登录态        │
│  - 资源限制：同一时刻只能1个浏览器  │
└─────────────────────────────────────┘
```

## Skill 隔离原则

**核心规则：每个 skill 只包含自己的方案模板**

- `gen-scraper` 只包含 HTTP/HTTPS 模板，禁止出现 Playwright
- `gen-scraper-browser` 只包含 Chrome CDP 模板
- 如果 skill 里混入了多个方案的模板，agent 会过早切换到"看起来更简单"的方案

**历史教训：**
- gen-scraper 里曾经包含 Playwright 模板 → agent 遇到反爬就直接用 Playwright → 没有深入尝试 HTTP 方案
- 解决：从 gen-scraper 中删除所有 Playwright 相关内容

## 浏览器资源管理

### 问题场景

批量运行爬虫时（`batch_task.py`），多个 Playwright 爬虫并发执行：

```python
# batch_task.py
MAX_CONCURRENT = 5  # 最多5个爬虫并发

async def run_scraper(scraper_name):
    # 如果 scraper 使用 Playwright，会启动浏览器实例
    pass
```

**症状：**
- 浏览器窗口在不同网站间快速切换
- 点击操作失效（点击了错误的页面元素）
- 浏览器崩溃或卡死

**根因：**
- 多个 Playwright 实例竞争同一个浏览器进程
- 或者多个浏览器实例竞争系统资源（内存、CPU）

### 解决方案

**互斥锁（Semaphore）：**

```python
# batch_task.py
PLAYWRIGHT_SEM = asyncio.Semaphore(1)

async def run_scraper(scraper_name):
    if is_playwright_scraper(scraper_name):
        async with PLAYWRIGHT_SEM:  # 同时只能1个 Playwright 爬虫
            await execute_scraper(scraper_name)
    else:
        # HTTP 爬虫不受限制，可以并发
        await execute_scraper(scraper_name)
```

**检测 Playwright 爬虫：**

```python
def is_playwright_scraper(scraper_name):
    """读取爬虫文件，检查是否使用了 Playwright"""
    path = f"scrapers/scrape_{scraper_name}.js"
    with open(path) as f:
        content = f.read()
    return 'playwright' in content.lower() or 'chromium' in content.lower()
```

### 性能影响

- **HTTP 爬虫**：完全并发，无限制
- **Playwright 爬虫**：串行执行，每次只能1个
- **混合场景**：HTTP 爬虫不受影响，Playwright 爬虫排队等待

**优化方向（未来）：**
- 浏览器池：启动多个浏览器实例，每个实例处理一个爬虫
- 资源感知调度：根据系统资源动态调整并发数

## 实际案例

### 浦发银行 (spdb)

**Layer 1 成功：**
- API 返回加密数据（AES-ECB + 自定义 Base64）
- HTTP 方案可以解密：分析 JS 源码 → 复现解密逻辑
- 结果：`scrape_spdb.js` 使用纯 HTTP 方案

**关键代码：**
```javascript
const crypto = require('crypto');

function decryptResponse(encryptedData, key) {
  const decipher = crypto.createDecipheriv('aes-128-ecb', key, null);
  decipher.setAutoPadding(true);
  let decrypted = decipher.update(encryptedData, 'base64', 'utf8');
  decrypted += decipher.final('utf8');
  return JSON.parse(decrypted);
}
```

### 徽商银行 (hfbank)

**Layer 1 失败 → Layer 2 成功：**
- 瑞数 WAF：HTTP 412 + JavaScript 挑战
- 尝试了所有 HTTP 手段（User-Agent、Referer、Cookie、TLS指纹）
- 判断：需要执行 JavaScript 才能生成正确的 Cookie
- 结果：使用 `gen-scraper-browser` 生成 Chrome CDP 方案

### 批量运行场景

假设要爬取 10 个网站：
- 7 个使用 HTTP 方案 → 并发执行，5分钟内完成
- 3 个使用 Playwright 方案 → 串行执行，每个约2-3分钟
- 总耗时：7 个 HTTP（并发）+ 3 个 Playwright（串行）≈ 10-15分钟

**日志输出示例：**
```
[10:23:45] 开始爬取 site_a (HTTP模式)...
[10:23:45] 开始爬取 site_b (HTTP模式)...
[10:23:45] 开始爬取 site_c (Playwright模式，等待浏览器锁)...
[10:23:46] site_a 完成 ✓
[10:23:47] site_b 完成 ✓
[10:23:47] site_c 获取锁，开始爬取...
```

## 运维建议

1. **监控浏览器进程**：定期检查是否有残留的 Chrome 进程
   ```bash
   ps aux | grep -i chrome | grep -v grep
   ```

2. **清理临时目录**：Playwright 爬虫会创建临时用户数据目录
   ```bash
   ls -la /tmp | grep chrome
   ```

3. **调整并发数**：如果系统资源紧张，降低 MAX_CONCURRENT
   ```python
   # batch_task.py
   MAX_CONCURRENT = 3  # 从5降到3
   ```

4. **日志分析**：检查是否有浏览器竞争导致的超时
   ```bash
   grep -i "timeout\|browser" logs/*.log | tail -20
   ```
