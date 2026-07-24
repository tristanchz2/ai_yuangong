# Hermes 全局配置架构

## 关键事实

Hermes 是**全局安装**的工具，配置在 `~/.hermes/config.yaml`，不是项目级别的。
项目的 `.env` 文件**不影响** hermes 的模型配置。

## 查看当前配置

```bash
hermes config show        # 查看完整配置
hermes config path        # 配置文件路径 (~/.hermes/config.yaml)
hermes config env-path    # .env 文件路径
```

## 模型配置

当前 hermes 默认模型配置在 `~/.hermes/config.yaml` 的 `model:` 段。
调用时可通过命令行参数覆盖：

```bash
hermes chat -m <model> --provider <provider>
```

## 不同任务用不同模型

项目有两类 LLM 任务：
1. **爬虫生成**（hermes chat 调用）→ 可用 `-m` / `--provider` 指定
2. **字段提取**（extract_fields.py 直接调 OpenAI API）→ 读 `.env` 的 OPENAI_* 变量

要实现两套模型配置：
- 字段提取：直接改 `.env` 中的 `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL`
- 爬虫生成：在 `scraper_generator.py` 中通过 `hermes chat -m <model>` 传参，或在 `~/.hermes/config.yaml` 中配置多个 provider

## 常见误区

- ❌ 在 `.env` 里加 `SCRAPER_GEN_*` 变量 → hermes 不会读这些
- ❌ 修改项目目录下的配置文件 → hermes 读的是全局 `~/.hermes/config.yaml`
- ✅ 用 `hermes chat -m <model>` 命令行参数覆盖
- ✅ 在 `~/.hermes/config.yaml` 中配置多个 provider，用 `--provider` 切换
