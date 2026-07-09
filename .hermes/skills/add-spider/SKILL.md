---
name: add-spider
description: 指导 Agent 手动添加新爬虫（自动发现架构）
version: 2.0.0
author: Weasley
---

# 添加新爬虫指南

## 架构说明

本项目采用**自动发现**的爬虫架构：
- `run.py` - 执行引擎（通过 `--info` 自动获取爬虫元数据，**禁止修改**）
- `scrapers/scrape_*.js` - 爬虫脚本（**可自由添加**）
- `scrapers/utility/` - 共享工具函数（stripHtml、JsonWriter）

新增爬虫只需在 `scrapers/` 目录创建 `scrape_xxx.js`，无需修改任何现有文件。

## 受保护文件（禁止 Agent 修改）

- `/Users/tristcz/project/ai_yuangong/agent_workspace/run.py`

## 添加新爬虫流程

### 1. 创建爬虫脚本

在 `scrapers/` 目录创建 `scrape_xxx.js`。

脚本**必须支持**以下命令行参数：
- `--info` - 输出 JSON 元数据（name/description/modes/outputFile）
- `--latest N` - 爬取最新 N 条
- `--yesterday` - 爬取昨天的数据
- `--date YYYY-MM-DD` - 爬取指定日期数据（可选）

### 2. 验证

```bash
cd /Users/tristcz/project/ai_yuangong/agent_workspace
node scrapers/scrape_xxx.js --info       # 确认 JSON 输出正确
python3 run.py list                       # 确认自动发现正常
python3 run.py xxx --latest 3             # 测试爬取
```

## 爬虫脚本开发规范

### --info 输出格式

```javascript
if (args.includes('--info')) {
  console.log(JSON.stringify({
    name: 'xxx',
    description: '网站名称爬虫',
    modes: ['latest', 'yesterday', 'date'],
    outputFile: 'raw_data/xxx_data.json',
  }));
  return;
}
```

### 标准参数解析

```javascript
const args = process.argv.slice(2);
let mode = 'latest';
let count = 5;
let targetDate = null;

const yesterdayIdx = args.indexOf('--yesterday');
const latestIdx = args.indexOf('--latest');
const dateIdx = args.indexOf('--date');

if (yesterdayIdx >= 0) { mode = 'date'; targetDate = getYesterday(); }
else if (dateIdx >= 0) { mode = 'date'; targetDate = args[dateIdx + 1]; }
else if (latestIdx >= 0) { mode = 'latest'; count = parseInt(args[latestIdx + 1]) || 5; }
```

### 输出格式
- JSON 格式输出到 `raw_data/` 目录
- 文件名格式：`{name}_data.json`
- 使用 `JsonWriter` 增量写入（每条立即写磁盘）

### 必须使用的工具函数
- `require('./utility/stripHtml')` - HTML 转纯文本
- `require('./utility/JsonWriter')` - 增量 JSON 写入器

### 错误处理
- 网络请求使用 `requestWithBackoff` 包装（限频退避）
- 详情爬取失败时跳过并记录
- 最终 `process.exit(1)` 报告失败

### 禁止行为
- 不要修改 `run.py`
- 不要在其他目录创建爬虫脚本
- 不要使用非标准命令行参数格式
---
name: add-spider
description: 指导 Agent 添加新爬虫（配置驱动架构）
version: 1.0.0
author: Weasley
---

# 添加新爬虫指南

## 架构说明

本项目采用**配置驱动**的爬虫架构：
- `run.py` - 执行引擎（**只读保护，禁止修改**）
- `spiders.json` - 爬虫配置（**只读保护，禁止修改**）
- `scrapers/*.js` - 爬虫脚本（**可自由添加**）

## 受保护文件（禁止 Agent 修改）

以下文件受只读保护，Agent 不得修改：
- `/Users/tristcz/project/ai_yuangong/agent_workspace/run.py`
- `/Users/tristcz/project/ai_yuangong/agent_workspace/scrapers/spiders.json`

如需修改配置，必须：
1. 先请求用户授权
2. 用户手动执行 `chmod 644` 解锁
3. 修改完成后用户执行 `chmod 444` 重新锁定

## 添加新爬虫流程

### 1. 创建爬虫脚本

在 `scrapers/` 目录创建新的 JavaScript 文件：
```
scrapers/scrape_xxx.js
```

脚本必须支持以下命令行参数：
- `--latest N` - 爬取最新 N 条
- `--yesterday` - 爬取昨天的数据

示例脚本模板参考 `scrapers/example_spider.js`。

### 2. 请求配置添加

脚本创建完成后，向用户说明：
- 爬虫名称
- 描述信息
- 使用的命令行参数格式

等待用户授权后，由用户手动添加配置到 `spiders.json`。

### 3. 测试验证

配置添加后，执行测试：
```bash
cd /Users/tristcz/project/ai_yuangong/agent_workspace
python3 run.py list          # 确认爬虫已注册
python3 run.py xxx --latest 3  # 测试爬取
```

## 爬虫脚本开发规范

### 必需功能

1. **命令行参数解析**
```javascript
const args = process.argv.slice(2);
let mode = 'latest';
let count = 5;

for (let i = 0; i < args.length; i++) {
  if (args[i] === '--latest') {
    mode = 'latest';
    count = parseInt(args[i + 1]) || 5;
  } else if (args[i] === '--yesterday') {
    mode = 'yesterday';
  }
}
```

2. **输出格式**
- JSON 格式输出到 `data/` 目录
- 文件名格式：`{spider_name}_data.json`
- 每条记录包含：title, url, date, content（可选）

3. **错误处理**
- 网络请求失败时重试
- 数据解析失败时跳过并记录
- 最终输出错误日志到 stderr

### 禁止行为

- 不要修改 `run.py` 或 `spiders.json`
- 不要在其他目录创建爬虫脚本
- 不要使用非标准命令行参数格式
- 不要修改其他爬虫的配置

## 示例：添加 chinapost 爬虫

### 创建脚本
```bash
cat > scrapers/scrape_chinapost.js << 'EOF'
// 中国邮政采购网爬虫
// 支持 --latest N 和 --yesterday 参数
EOF
```

### 向用户说明
"我已创建 `scrape_chinapost.js` 爬虫脚本，支持 `--latest N` 和 `--yesterday` 参数。请在 `spiders.json` 中添加配置：

```json
"chinapost": {
  "description": "中国邮政采购网",
  "script": "scrape_chinapost.js",
  "args": {
    "latest": ["--latest"],
    "yesterday": ["--yesterday"]
  }
}
```

需要您授权后执行 `chmod 644 spiders.json` 进行修改。"
