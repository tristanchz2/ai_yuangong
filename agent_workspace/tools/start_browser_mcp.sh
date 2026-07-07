#!/usr/bin/env bash
# 启动 Browser MCP Server
# 用法:
#   ./start_browser_mcp.sh              # stdio 模式（默认，无头）
#   ./start_browser_mcp.sh --visible    # 有头模式（可以看到浏览器窗口）
#   ./start_browser_mcp.sh --sse        # SSE 模式（端口 8765）

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 激活虚拟环境
if [ -f "../../venv-browser/bin/activate" ]; then
    source ../../venv-browser/bin/activate
elif [ -f "../../venv-browser/bin/activate" ]; then
    source ../../venv-browser/bin/activate
fi

ARGS=()
if [[ "$1" == "--visible" ]]; then
    ARGS+=("--headless")  # 注意：脚本里 --headless 标志是关闭无头模式
    shift
fi

exec python3 browser_mcp_server.py "$@" "${ARGS[@]}"
