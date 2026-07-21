#!/bin/bash
# 同步 Hermes 知识到服务器
# 用法: ./sync_hermes_to_server.sh [server]
# server 格式: user@host 或 ~/.ssh/config 中的别名

set -e

SERVER=${1:-"your-server"}  # 改成你的服务器地址
LOCAL_HERMES="$HOME/.hermes"

echo "🚀 开始同步 Hermes 知识到 $SERVER ..."

# 1. 同步 skills（通过 git）
echo "📚 同步 skills (git push)..."
cd "$LOCAL_HERMES/skills"
git add .
git diff --cached --quiet || git commit -m "Sync skills $(date +%Y-%m-%d_%H:%M)"
git push origin main

# 2. 同步 state.db（包含 sessions 和 memory）
echo "💾 同步 state.db (sessions + memory)..."
rsync -avz --progress "$LOCAL_HERMES/state.db" "$SERVER:$LOCAL_HERMES/state.db"

# 3. 同步配置（可选）
echo "⚙️  同步配置..."
rsync -avz --progress "$LOCAL_HERMES/config.yaml" "$SERVER:$LOCAL_HERMES/config.yaml"
rsync -avz --progress "$LOCAL_HERMES/.env" "$SERVER:$LOCAL_HERMES/.env"

echo "✅ 同步完成！"
echo ""
echo "服务器上的 Hermes 现在可以使用相同的："
echo "  - Skills（~/.hermes/skills/）"
echo "  - Sessions 历史（state.db）"
echo "  - Memory（state.db）"
echo "  - 配置和 API keys（config.yaml + .env）"
