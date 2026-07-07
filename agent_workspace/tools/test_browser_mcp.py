"""
Browser MCP Server 测试客户端
用于验证 MCP server 的工具是否正常工作。

用法:
    python test_browser_mcp.py               # stdio 模式测试
    python test_browser_mcp.py --sse         # SSE 模式测试
"""

import asyncio
import json
import argparse


async def test_stdio():
    """通过 stdio 测试 MCP server。"""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    server_params = StdioServerParameters(
        command="python3",
        args=["agent_workspace/tools/browser_mcp_server.py"],
        cwd="/Users/tristcz/project/ai_yuangong",
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # 列出所有工具
            tools = await session.list_tools()
            print(f"\n=== 可用工具 ({len(tools.tools)} 个) ===")
            for t in tools.tools:
                print(f"  {t.name:25s} - {t.description[:60]}")

            # 测试 navigate
            print("\n=== 测试 navigate_page ===")
            result = await session.call_tool("navigate_page", {"url": "https://example.com"})
            print(f"  结果: {result.content[0].text[:100]}")

            # 测试 take_snapshot
            print("\n=== 测试 take_snapshot ===")
            result = await session.call_tool("take_snapshot")
            print(f"  结果: {result.content[0].text[:200]}")

            # 测试 evaluate_script
            print("\n=== 测试 evaluate_script ===")
            result = await session.call_tool("evaluate_script", {
                "function": "() => { return { title: document.title, url: document.URL } }"
            })
            print(f"  结果: {result.content[0].text[:200]}")

            # 测试 take_screenshot
            print("\n=== 测试 take_screenshot ===")
            result = await session.call_tool("take_screenshot", {"full_page": True})
            text = result.content[0].text
            if text.startswith("data:image"):
                print(f"  结果: 截图 base64 长度={len(text)}")
            else:
                print(f"  结果: {text[:100]}")

            # 测试 list_pages
            print("\n=== 测试 list_pages ===")
            result = await session.call_tool("list_pages")
            print(f"  结果: {result.content[0].text}")

            print("\n 所有测试通过!")


async def test_sse():
    """通过 SSE 测试 MCP server。"""
    from mcp import ClientSession
    from mcp.client.sse import sse_client

    async with sse_client("http://localhost:8765/sse") as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            print(f"\n=== 可用工具 ({len(tools.tools)} 个) ===")
            for t in tools.tools:
                print(f"  {t.name:25s} - {t.description[:60]}")

            print("\n=== 测试 navigate_page ===")
            result = await session.call_tool("navigate_page", {"url": "https://example.com"})
            print(f"  结果: {result.content[0].text[:100]}")

            print("\n 测试通过!")


def main():
    parser = argparse.ArgumentParser(description="Browser MCP Server 测试客户端")
    parser.add_argument("--sse", action="store_true", help="通过 SSE 连接")
    args = parser.parse_args()

    if args.sse:
        asyncio.run(test_sse())
    else:
        asyncio.run(test_stdio())


if __name__ == "__main__":
    main()
