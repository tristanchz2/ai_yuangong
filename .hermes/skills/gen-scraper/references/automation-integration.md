# 自动化集成指南

## server.py 调用规范

当通过 `hermes chat -q` 作为子进程调用时：

### 必须使用的参数

**--yolo 标志（关键！）**
- 必须使用 `--yolo`，否则命令审批系统会拒绝 shell 命令
- Agent 以为用户拒绝 → 停下来问问题 → 无人回答 → 卡死
- 这是最常见的挂起原因

**示例：**
```bash
hermes chat -q --yolo "帮我爬 https://example.com，不要问我任何问题，所有决策你自己做"
```

### 超时控制

- **20 分钟硬限制**：server.py 有总超时兜底，超过 20 分钟直接 kill
- Agent 侧：不要在任何步骤上死等，单个操作超过 2-3 分钟无响应就跳过或报错

### Prompt 要求

Prompt 必须包含：
> "不要问我任何问题，所有决策你自己做，遇到错误自己修复"

否则 agent 可能停下来问问题。

## 诊断 Hang

检查 `~/.hermes/logs/errors.log`：

| 错误信息 | 原因 | 解决方案 |
|---------|------|---------|
| "Stream stale" | LLM 响应卡死（网络或 API 问题） | 重试或检查网络连接 |
| "User denied" | 命令被审批拒绝 | 检查是否使用了 `--yolo` 参数 |
| 无错误但任务不完成 | Agent 在等用户输入 | Prompt 缺少"不要问问题"指令 |

## 日志结构

每个任务创建独立日志：
```
logs/
├── task_<id>_gen-scraper.log           # gen-scraper 任务的 agent 输出
└── task_<id>_gen-scraper-browser.log   # gen-scraper-browser 任务的 agent 输出
```

任务完成后，日志内容保存在 `tasks[task_id]['hermes_output']` 中。

## 任务状态管理

server.py 保留最近 5 个爬虫生成任务（`MAX_GENERATE_TASKS = 5`），超出后自动清理最旧的任务。

任务状态存储在内存中（`services/scraper_generator.py` 的 `tasks` dict），生产环境应考虑迁移到 Redis/DB。
