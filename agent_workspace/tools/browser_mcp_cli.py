#!/usr/bin/env python3
"""
Browser MCP CLI Bridge
======================
让 Aider（或其他 CLI 工具）通过命令行调用 browser MCP server 的工具。

架构:
    browser_mcp_server.py --sse   →  后台持久化浏览器 (端口 8765)
    browser_mcp_cli.py <tool>     →  连接 SSE server 调用工具

用法:
    # 1. 先启动浏览器服务（后台运行）
    python browser_mcp_server.py --sse &

    # 2. 然后调用工具
    python browser_mcp_cli.py navigate_page '{"url": "https://example.com"}'
    python browser_mcp_cli.py take_snapshot '{}'
    python browser_mcp_cli.py evaluate_script '{"function": "() => document.title"}'
    python browser_mcp_cli.py --list
"""

import asyncio
import json
import sys
import os
import argparse

# 项目根目录
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
DEFAULT_SSE_URL = os.environ.get("BROWSER_MCP_URL", "http://localhost:8765/sse")


async def call_mcp_tool(tool_name: str, args_json: str, sse_url: str = DEFAULT_SSE_URL) -> str:
    """通过 SSE 连接持久化 MCP server 调用工具。"""
    from mcp import ClientSession
    from mcp.client.sse import sse_client

    # 解析参数
    if args_json:
        try:
            arguments = json.loads(args_json)
        except json.JSONDecodeError as e:
            return json.dumps({"error": f"参数 JSON 解析失败: {e}"}, ensure_ascii=False)
    else:
        arguments = {}

    async with sse_client(sse_url) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)

            texts = []
            for content in result.content:
                if hasattr(content, 'text'):
                    texts.append(content.text)
                else:
                    texts.append(str(content))

            return "\n".join(texts)


async def list_tools(sse_url: str = DEFAULT_SSE_URL) -> str:
    """列出 MCP server 所有可用工具。"""
    from mcp import ClientSession
    from mcp.client.sse import sse_client

    async with sse_client(sse_url) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()

            lines = [f"可用工具 ({len(tools.tools)} 个):\n"]
            for t in tools.tools:
                desc = t.description.split('\n')[0] if t.description else ''
                lines.append(f"  {t.name:25s} - {desc}")

                if t.inputSchema and t.inputSchema.get('properties'):
                    for pname, pinfo in t.inputSchema['properties'].items():
                        ptype = pinfo.get('type', 'any')
                        pdesc = pinfo.get('description', '')
                        required = pname in t.inputSchema.get('required', [])
                        req_mark = " *" if required else ""
                        lines.append(f"    {pname}{req_mark} ({ptype}): {pdesc}")
                lines.append("")

            return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Browser MCP CLI Bridge — 通过命令行调用浏览器自动化工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用前请先启动浏览器服务:
  python agent_workspace/tools/browser_mcp_server.py --sse &

示例:
  python browser_mcp_cli.py --list
  python browser_mcp_cli.py navigate_page '{"url": "https://example.com"}'
  python browser_mcp_cli.py take_snapshot '{}'
  python browser_mcp_cli.py evaluate_script '{"function": "() => document.title"}'
  python browser_mcp_cli.py take_screenshot '{"file_path": "/tmp/s.png", "full_page": true}'
        """,
    )
    parser.add_argument("tool", nargs="?", help="工具名称")
    parser.add_argument("args", nargs="?", default="{}", help="JSON 格式的参数")
    parser.add_argument("--list", action="store_true", help="列出所有可用工具")
    parser.add_argument("--url", default=DEFAULT_SSE_URL, help="MCP SSE 服务器地址")

    args = parser.parse_args()

    if args.list:
        result = asyncio.run(list_tools(args.url))
        print(result)
        return

    if not args.tool:
        parser.print_help()
        sys.exit(1)

    result = asyncio.run(call_mcp_tool(args.tool, args.args, args.url))
    print(result)


if __name__ == "__main__":
    main()
