"""
Browser Use MCP Server
======================
一个基于 Playwright 的浏览器自动化 MCP 服务器。
提供 navigate、click、fill、screenshot、snapshot、evaluate_script 等工具。

启动方式:
    python browser_mcp_server.py              # stdio 模式（默认）
    python browser_mcp_server.py --sse        # SSE 模式（端口 8765）
    python browser_mcp_server.py --streamable # Streamable HTTP 模式（端口 8765）

其他 agent 通过 MCP 协议调用这些工具来控制浏览器。
"""

import asyncio
import sys
import json
import argparse
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Optional

from mcp.server.fastmcp import FastMCP
from playwright.async_api import async_playwright, Browser, BrowserContext, Page


# ─── 全局浏览器状态 ───────────────────────────────────────────────

@dataclass
class BrowserState:
    playwright: Optional[object] = None
    browser: Optional[Browser] = None
    context: Optional[BrowserContext] = None
    pages: list = field(default_factory=list)
    active_page_index: int = 0

    @property
    def active_page(self) -> Optional[Page]:
        if self.pages and 0 <= self.active_page_index < len(self.pages):
            return self.pages[self.active_page_index]
        return None


state = BrowserState()

# 默认 Chrome UA
DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/138.0.0.0 Safari/537.36"
)


# ─── 浏览器初始化（惰性、全局持久化） ─────────────────────────────

_browser_initialized = False
_browser_lock = asyncio.Lock()


async def _ensure_browser():
    """惰性初始化浏览器，全局只创建一次，进程退出时清理。"""
    global _browser_initialized

    async with _browser_lock:
        if _browser_initialized:
            return

        pw = await async_playwright().start()
        browser = await pw.chromium.launch(
            headless=os.environ.get("HEADLESS", "true").lower() == "true",
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
        context = await browser.new_context(
            user_agent=os.environ.get("BROWSER_UA", DEFAULT_UA),
            viewport={"width": 1920, "height": 1080},
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
        )
        # 注入 stealth 脚本：隐藏 webdriver 等自动化特征
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
            window.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'permissions', {
                get: () => ({ query: async () => ({ state: 'granted' }) })
            });
        """)

        state.playwright = pw
        state.browser = browser
        state.context = context

        # 创建初始页面
        page = await context.new_page()
        state.pages.append(page)
        state.active_page_index = 0

        _browser_initialized = True

        # 注册进程退出时清理
        import atexit
        def _cleanup():
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(browser.close())
                    loop.create_task(pw.stop())
                else:
                    loop.run_until_complete(browser.close())
                    loop.run_until_complete(pw.stop())
            except Exception:
                pass
        atexit.register(_cleanup)


def _get_page() -> Page:
    """获取当前页面，如果浏览器未初始化则先初始化。"""
    page = state.active_page
    if page is None:
        raise RuntimeError("没有可用的浏览器页面。请先调用 navigate_page。")
    return page


# ─── MCP Server ───────────────────────────────────────────────────

mcp = FastMCP(
    "browser-use",
    instructions="浏览器自动化工具集。通过 Playwright 控制真实浏览器，支持导航、点击、输入、截图、执行 JS 等。",
)


def _get_page() -> Page:
    page = state.active_page
    if page is None:
        raise RuntimeError("没有可用的浏览器页面。请先调用 list_pages 或 navigate_page。")
    return page


# ─── 工具：页面管理 ───────────────────────────────────────────────

@mcp.tool()
async def list_pages() -> str:
    """获取浏览器中所有打开的页面列表。返回每个页面的 URL 和索引。"""
    await _ensure_browser()
    pages = state.pages
    if not pages:
        return "没有打开的页面。"
    lines = []
    for i, p in enumerate(pages):
        marker = " [selected]" if i == state.active_page_index else ""
        lines.append(f"{i}: {p.url}{marker}")
    return "## Pages\n" + "\n".join(lines)


@mcp.tool()
async def select_page(index: int) -> str:
    """切换到指定索引的页面。

    Args:
        index: 页面索引（从 list_pages 获取）
    """
    await _ensure_browser()
    if index < 0 or index >= len(state.pages):
        return f"错误：页面索引 {index} 超出范围（共 {len(state.pages)} 个页面）。"
    state.active_page_index = index
    page = state.pages[index]
    await page.bring_to_front()
    return f"已切换到页面 {index}: {page.url}"


@mcp.tool()
async def new_page(url: Optional[str] = None) -> str:
    """打开一个新页面。

    Args:
        url: 可选，打开后导航到的 URL
    """
    await _ensure_browser()
    page = await state.context.new_page()
    state.pages.append(page)
    state.active_page_index = len(state.pages) - 1
    if url:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    return f"新页面已创建 (index={state.active_page_index}), URL: {page.url}"


@mcp.tool()
async def close_page(index: Optional[int] = None) -> str:
    """关闭指定页面。不指定则关闭当前页面。

    Args:
        index: 可选，要关闭的页面索引
    """
    await _ensure_browser()
    if index is None:
        index = state.active_page_index
    if len(state.pages) <= 1:
        return "错误：至少需要保留一个页面。"
    page = state.pages.pop(index)
    await page.close()
    if state.active_page_index >= len(state.pages):
        state.active_page_index = len(state.pages) - 1
    return f"页面 {index} 已关闭。当前页面: {state.active_page_index} - {state.active_page.url}"


# ─── 工具：导航 ───────────────────────────────────────────────────

@mcp.tool()
async def navigate_page(
    url: Optional[str] = None,
    type: str = "url",
    timeout: Optional[int] = None,
) -> str:
    """导航页面。支持 URL 导航、前进、后退、刷新。

    Args:
        url: 目标 URL（type=url 时需要）
        type: 导航类型 - url, back, forward, reload
        timeout: 超时时间（毫秒），默认 30000
    """
    await _ensure_browser()
    page = _get_page()
    ts = timeout or 30000

    if type == "url":
        if not url:
            return "错误：type=url 时必须提供 url 参数。"
        await page.goto(url, wait_until="domcontentloaded", timeout=ts)
    elif type == "back":
        await page.go_back(timeout=ts)
    elif type == "forward":
        await page.go_forward(timeout=ts)
    elif type == "reload":
        await page.reload(timeout=ts)
    else:
        return f"错误：未知的 type '{type}'，可选值：url, back, forward, reload"

    await page.wait_for_timeout(1000)  # 等待页面稳定
    return f"导航完成: {page.url}"


# ─── 工具：交互操作 ───────────────────────────────────────────────

@mcp.tool()
async def click(selector: str, button: str = "left") -> str:
    """点击页面上的元素。

    Args:
        selector: CSS 选择器或文本选择器
        button: 鼠标按钮 - left, right, middle
    """
    await _ensure_browser()
    page = _get_page()
    await page.click(selector, button=button, timeout=10000)
    await page.wait_for_timeout(500)
    return f"已点击: {selector}"


@mcp.tool()
async def hover(selector: str) -> str:
    """鼠标悬停在元素上。

    Args:
        selector: CSS 选择器
    """
    await _ensure_browser()
    page = _get_page()
    await page.hover(selector, timeout=10000)
    return f"已悬停: {selector}"


@mcp.tool()
async def fill(selector: str, value: str) -> str:
    """填充输入框内容。

    Args:
        selector: CSS 选择器
        value: 要填入的值
    """
    await _ensure_browser()
    page = _get_page()
    await page.fill(selector, value, timeout=10000)
    return f"已填充 {selector} = {value}"


@mcp.tool()
async def press_key(key: str) -> str:
    """按下键盘按键。支持组合键如 Control+a, Enter, Escape 等。

    Args:
        key: 按键名称
    """
    await _ensure_browser()
    page = _get_page()
    await page.keyboard.press(key)
    await page.wait_for_timeout(300)
    return f"已按键: {key}"


@mcp.tool()
async def type_text(text: str, delay: int = 50) -> str:
    """逐个字符输入文本（模拟真实打字）。

    Args:
        text: 要输入的文本
        delay: 每个字符之间的延迟（毫秒），默认 50
    """
    await _ensure_browser()
    page = _get_page()
    await page.keyboard.type(text, delay=delay)
    return f"已输入文本: {text[:50]}{'...' if len(text) > 50 else ''}"


@mcp.tool()
async def drag(
    start_selector: str,
    end_selector: str,
) -> str:
    """拖拽操作：从 start_selector 拖到 end_selector。

    Args:
        start_selector: 起始元素选择器
        end_selector: 目标元素选择器
    """
    await _ensure_browser()
    page = _get_page()
    await page.drag_and_drop(start_selector, end_selector, timeout=10000)
    return f"已拖拽: {start_selector} → {end_selector}"


@mcp.tool()
async def upload_file(selector: str, file_path: str) -> str:
    """上传文件到文件输入框。

    Args:
        selector: 文件输入框的 CSS 选择器
        file_path: 要上传的文件路径
    """
    await _ensure_browser()
    page = _get_page()
    await page.set_input_files(selector, file_path, timeout=10000)
    return f"已上传文件: {file_path} → {selector}"


@mcp.tool()
async def handle_dialog(action: str, prompt_text: Optional[str] = None) -> str:
    """处理浏览器对话框（alert/confirm/prompt）。需要在对话框出现前调用。

    Args:
        action: 操作 - accept（接受）或 dismiss（取消）
        prompt_text: 当 action=accept 且是 prompt 对话框时，填入的文本
    """
    await _ensure_browser()
    page = _get_page()

    def _handler(dialog):
        if action == "accept":
            dialog.accept(prompt_text or "")
        else:
            dialog.dismiss()

    page.once("dialog", _handler)
    return f"已设置对话框处理: {action}"


@mcp.tool()
async def wait_for(
    selector: Optional[str] = None,
    timeout: int = 30000,
    state: str = "visible",
) -> str:
    """等待元素出现或页面状态变化。

    Args:
        selector: 可选，等待出现的 CSS 选择器
        timeout: 超时时间（毫秒），默认 30000
        state: 元素状态 - visible, hidden, attached, detached
    """
    await _ensure_browser()
    page = _get_page()
    if selector:
        await page.wait_for_selector(selector, state=state, timeout=timeout)
        return f"等待完成: {selector} (state={state})"
    else:
        await page.wait_for_timeout(timeout)
        return f"等待了 {timeout}ms"


@mcp.tool()
async def scroll_page(
    direction: str = "down",
    amount: Optional[int] = None,
    to_bottom: bool = False,
) -> str:
    """滚动页面。用于触发懒加载、无限滚动等。

    Args:
        direction: 滚动方向 - down, up, left, right
        amount: 可选，滚动像素数。不指定则滚动一屏
        to_bottom: 是否滚动到底部（忽略 amount）
    """
    await _ensure_browser()
    page = _get_page()
    
    if to_bottom:
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(1000)  # 等待懒加载
        return "已滚动到页面底部"
    elif amount:
        if direction == "down":
            await page.evaluate(f"window.scrollBy(0, {amount})")
        elif direction == "up":
            await page.evaluate(f"window.scrollBy(0, -{amount})")
        elif direction == "left":
            await page.evaluate(f"window.scrollBy(-{amount}, 0)")
        elif direction == "right":
            await page.evaluate(f"window.scrollBy({amount}, 0)")
        else:
            return f"错误：未知的 direction '{direction}'"
        await page.wait_for_timeout(500)
        return f"已向{direction}滚动 {amount}px"
    else:
        # 默认滚动一屏
        viewport = await page.evaluate("() => ({ width: window.innerWidth, height: window.innerHeight })")
        if direction == "down":
            await page.evaluate(f"window.scrollBy(0, {viewport['height']})")
        elif direction == "up":
            await page.evaluate(f"window.scrollBy(0, -{viewport['height']})")
        else:
            return f"错误：需要指定 amount 或使用 to_bottom"
        await page.wait_for_timeout(500)
        return f"已向{direction}滚动一屏"


# ─── 工具：内容提取 ───────────────────────────────────────────────

@mcp.tool()
async def take_snapshot(verbose: bool = False) -> str:
    """获取页面的无障碍树（a11y tree）快照。返回页面元素及其 uid。
    比截图更适合让 AI 理解页面结构。

    Args:
        verbose: 是否返回详细信息
    """
    await _ensure_browser()
    page = _get_page()

    # 通过 JS 获取 DOM 结构作为快照
    snapshot = await page.evaluate("""() => {
        function buildTree(el, depth) {
            if (depth > 8) return null;
            const tag = el.tagName ? el.tagName.toLowerCase() : '';
            if (!tag) return null;
            const skip = ['script', 'style', 'link', 'meta'];
            if (skip.includes(tag)) return null;

            const id = el.id ? '#' + el.id : '';
            const cls = el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\\s+/).join('.') : '';
            const text = (el.innerText || '').trim().substring(0, 80);
            const role = el.getAttribute('role') || '';
            const ariaLabel = el.getAttribute('aria-label') || '';
            const href = el.getAttribute('href') || '';
            const name = ariaLabel || text || el.getAttribute('placeholder') || el.getAttribute('alt') || '';

            const node = { role: role || tag, name: name.substring(0, 100) };
            if (href) node.href = href;
            if (id) node.id = el.id;

            const children = [];
            for (const child of el.children) {
                const t = buildTree(child, depth + 1);
                if (t) children.push(t);
            }
            if (children.length) node.children = children;
            return node;
        }
        return buildTree(document.body, 0);
    }""")

    def _format_tree(node, indent=0):
        lines = []
        prefix = "  " * indent
        role = node.get("role", "")
        name = node.get("name", "")
        uid = f"{role}:{name}" if name else role
        extra = ""
        if node.get("href"):
            extra = f" href={node['href'][:60]}"
        if node.get("id"):
            extra += f" id={node['id']}"
        lines.append(f"{prefix}{uid}{extra}")
        for child in node.get("children", []):
            lines.extend(_format_tree(child, indent + 1))
        return lines

    if snapshot:
        lines = _format_tree(snapshot)
        return "## Page Snapshot\n" + "\n".join(lines[:200])
    else:
        return "## Page Snapshot\n(空页面，无 DOM 内容)"


@mcp.tool()
async def take_screenshot(
    full_page: bool = False,
    selector: Optional[str] = None,
    file_path: Optional[str] = None,
) -> str:
    """截取页面或元素的截图。

    Args:
        full_page: 是否截取完整页面（包括滚动区域）
        selector: 可选，只截取指定元素
        file_path: 可选，截图保存路径
    """
    await _ensure_browser()
    page = _get_page()

    if selector:
        element = await page.query_selector(selector)
        if element:
            buf = await element.screenshot()
        else:
            return f"错误：未找到元素 '{selector}'"
    else:
        buf = await page.screenshot(full_page=full_page)

    if file_path:
        os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
        with open(file_path, "wb") as f:
            f.write(buf)
        return f"截图已保存: {file_path}"
    else:
        # 返回 base64 供 MCP 客户端显示
        import base64
        b64 = base64.b64encode(buf).decode()
        return f"data:image/png;base64,{b64}"


@mcp.tool()
async def get_page_content() -> str:
    """获取页面的完整 HTML 源码。"""
    await _ensure_browser()
    page = _get_page()
    html = await page.content()
    return html[:10000] + ("...\n(内容过长，已截断)" if len(html) > 10000 else "")


@mcp.tool()
async def get_page_text() -> str:
    """获取页面的可见文本内容。"""
    await _ensure_browser()
    page = _get_page()
    text = await page.inner_text("body")
    return text[:5000] + ("...\n(内容过长，已截断)" if len(text) > 5000 else "")


# ─── 工具：JavaScript 执行 ────────────────────────────────────────

@mcp.tool()
async def evaluate_script(
    function: str,
) -> str:
    """在页面中执行 JavaScript 函数并返回结果。

    Args:
        function: JavaScript 函数体，例如 "() => { return document.title }"
                  或 "async () => { return await fetch('/api/data').then(r => r.json()) }"
    """
    await _ensure_browser()
    page = _get_page()
    try:
        result = await page.evaluate(function)
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"JS 执行错误: {str(e)}"


# ─── 工具：网络监控 ───────────────────────────────────────────────

@mcp.tool()
async def list_network_requests(
    resource_types: Optional[list[str]] = None,
    page_idx: int = 0,
    page_size: int = 50,
    include_headers: bool = False,
) -> str:
    """列出页面的网络请求记录（增强版）。
    
    注意：此工具只能获取已完成的请求。如需捕获所有请求，请先调用 start_request_interception。

    Args:
        resource_types: 可选，过滤资源类型，如 ["xhr", "fetch", "document"]
        page_idx: 页码（从 0 开始）
        page_size: 每页数量
        include_headers: 是否包含请求/响应头
    """
    await _ensure_browser()
    page = _get_page()

    # 获取已存储的拦截请求
    intercepted = getattr(page, "_mcp_intercepted_requests", [])
    
    if intercepted:
        # 使用拦截的请求（更详细）
        requests_data = intercepted
    else:
        # Fallback: 使用 performance API
        perf_entries = await page.evaluate("""() => {
            const entries = performance.getEntriesByType('resource');
            return entries.map(e => ({
                url: e.name,
                type: e.initiatorType,
                duration: Math.round(e.duration),
                size: e.transferSize || 0,
                method: 'GET',
                status: 200
            }));
        }""")
        requests_data = [{"request": e} for e in perf_entries]

    if resource_types:
        requests_data = [
            r for r in requests_data 
            if (r.get("type") or r.get("request", {}).get("type")) in resource_types
        ]

    total = len(requests_data)
    start = page_idx * page_size
    end = start + page_size
    page_entries = requests_data[start:end]

    lines = [f"## Network Requests (showing {len(page_entries)} of {total})"]
    for i, entry in enumerate(page_entries, start=start + 1):
        if "request" in entry:
            # Performance API 格式
            req = entry["request"]
            line = f"  {i}. [{req.get('type', 'other')}] {req.get('url', '')[:100]} ({req.get('duration', 0)}ms)"
        else:
            # Intercepted format
            req = entry.get("request", {})
            resp = entry.get("response", {})
            method = req.get("method", "GET")
            url = req.get("url", "")[:100]
            status = resp.get("status", 0)
            line = f"  {i}. [{method}] {url} → {status}"
            
            if include_headers:
                req_headers = req.get("headers", {})
                resp_headers = resp.get("headers", {})
                if req_headers:
                    line += f"\n      Request Headers: {json.dumps(req_headers, ensure_ascii=False)[:200]}"
                if resp_headers:
                    line += f"\n      Response Headers: {json.dumps(resp_headers, ensure_ascii=False)[:200]}"
        
        lines.append(line)

    return "\n".join(lines) if lines else "## Network Requests\n(无请求记录)"


@mcp.tool()
async def list_console_messages(
    level: Optional[str] = None,
    page_idx: int = 0,
    page_size: int = 50,
) -> str:
    """获取页面的控制台消息。注意：需要在导航前设置监听才能捕获。

    Args:
        level: 可选，过滤级别 - log, warn, error, info
        page_idx: 页码
        page_size: 每页数量
    """
    await _ensure_browser()
    page = _get_page()

    # 获取已存储的控制台消息
    messages = getattr(page, "_mcp_console_messages", [])

    if level:
        messages = [m for m in messages if m["type"] == level]

    total = len(messages)
    start = page_idx * page_size
    end = start + page_size
    page_messages = messages[start:end]

    lines = [f"## Console Messages (showing {len(page_messages)} of {total})"]
    for i, m in enumerate(page_messages, start=start + 1):
        lines.append(f"  msgid={i} [{m['type']}] {m['text'][:200]}")

    return "\n".join(lines) if lines else "## Console Messages\n(无控制台消息)"


# ─── 工具：Cookie & Storage ───────────────────────────────────────

@mcp.tool()
async def get_cookies() -> str:
    """获取当前页面的所有 Cookie。"""
    await _ensure_browser()
    page = _get_page()
    cookies = await page.context.cookies()
    if not cookies:
        return "## Cookies\n(无 Cookie)"
    lines = ["## Cookies"]
    for c in cookies:
        lines.append(f"  {c['name']}={c['value'][:50]}{'...' if len(c['value']) > 50 else ''} (domain={c.get('domain', '')})")
    return "\n".join(lines)


@mcp.tool()
async def set_cookie(name: str, value: str, domain: Optional[str] = None) -> str:
    """设置 Cookie。

    Args:
        name: Cookie 名称
        value: Cookie 值
        domain: 可选，Cookie 域名（默认使用当前页面域名）
    """
    await _ensure_browser()
    page = _get_page()
    from urllib.parse import urlparse
    d = domain or urlparse(page.url).netloc
    await page.context.add_cookies([{"name": name, "value": value, "domain": d, "path": "/"}])
    return f"已设置 Cookie: {name}={value[:30]}... (domain={d})"


# ── 启动时自动监听控制台消息 ─────────────────────────────────────

@mcp.tool()
async def start_console_capture() -> str:
    """开始捕获当前页面的控制台消息。导航到新页面后需要重新调用。"""
    await _ensure_browser()
    page = _get_page()
    page._mcp_console_messages = []

    def _on_console(msg):
        page._mcp_console_messages.append({
            "type": msg.type,
            "text": msg.text,
        })

    page.on("console", _on_console)
    return "已开始捕获控制台消息。"


# ─── 工具：请求拦截（爬虫关键） ──────────────────────────────────────

@mcp.tool()
async def start_request_interception(
    resource_types: Optional[list[str]] = None,
) -> str:
    """开始拦截网络请求，捕获请求头、响应头、响应体等详细信息。
    
    **爬虫必备**：在导航到目标页面前调用此工具，可以捕获所有 API 请求。
    拦截的数据可以通过 list_network_requests(include_headers=True) 查看。

    Args:
        resource_types: 可选，只拦截指定类型，如 ["xhr", "fetch"]。不指定则拦截所有。
    """
    await _ensure_browser()
    page = _get_page()
    
    # 初始化存储
    page._mcp_intercepted_requests = []
    
    # 设置拦截
    await page.route("**/*", lambda route, request: _intercept_handler(route, request, resource_types))
    
    types_str = ", ".join(resource_types) if resource_types else "all"
    return f"已开始拦截网络请求 (types={types_str})。拦截数据存储在 page._mcp_intercepted_requests。"


async def _intercept_handler(route, request, allowed_types: Optional[list[str]]):
    """请求拦截处理器。"""
    import time
    
    req_type = request.resource_type
    
    # 如果指定了类型过滤，跳过不匹配的
    if allowed_types and req_type not in allowed_types:
        await route.continue_()
        return
    
    # 记录请求信息
    req_info = {
        "request": {
            "url": request.url,
            "method": request.method,
            "headers": dict(request.headers),
            "post_data": request.post_data,
            "type": req_type,
            "timestamp": time.time()
        },
        "response": None
    }
    
    try:
        # 继续请求并获取响应
        response = await route.fetch()
        
        # 记录响应信息
        resp_info = {
            "status": response.status,
            "headers": dict(response.headers),
            "body": None
        }
        
        # 尝试获取响应体（文本或 JSON）
        try:
            body = await response.text()
            if len(body) < 50000:  # 限制大小
                resp_info["body"] = body
            else:
                resp_info["body"] = body[:50000] + "\n... (truncated)"
        except Exception:
            resp_info["body"] = "<binary or too large>"
        
        req_info["response"] = resp_info
        
        # 存储
        page = request.frame.page
        if not hasattr(page, "_mcp_intercepted_requests"):
            page._mcp_intercepted_requests = []
        page._mcp_intercepted_requests.append(req_info)
        
        # 返回原始响应
        await route.fulfill(response=response)
        
    except Exception as e:
        # 请求失败，继续原始路由
        await route.continue_()


@mcp.tool()
async def clear_intercepted_requests() -> str:
    """清除已拦截的请求记录。用于重新开始捕获。"""
    await _ensure_browser()
    page = _get_page()
    page._mcp_intercepted_requests = []
    return "已清除拦截记录。"


# ─── 工具：HTTP 客户端（类似 curl） ─────────────────────────────────

@mcp.tool()
async def http_request(
    url: str,
    method: str = "GET",
    headers: Optional[dict] = None,
    body: Optional[str] = None,
    timeout: int = 30000,
) -> str:
    """发送 HTTP 请求并返回响应（类似 curl）。
    
    **适用场景**：直接调用 API 获取数据，无需加载完整页面。
    比浏览器自动化更快，适合已知 API 端点的爬虫。

    Args:
        url: 请求 URL
        method: HTTP 方法 - GET, POST, PUT, DELETE 等
        headers: 可选，请求头字典
        body: 可选，请求体（POST/PUT 时使用）
        timeout: 超时时间（毫秒），默认 30000
    """
    await _ensure_browser()
    page = _get_page()
    
    # 使用 Playwright 的 request 上下文
    context = page.context
    
    try:
        if method.upper() == "GET":
            response = await context.request.get(url, headers=headers, timeout=timeout)
        elif method.upper() == "POST":
            response = await context.request.post(url, headers=headers, data=body, timeout=timeout)
        elif method.upper() == "PUT":
            response = await context.request.put(url, headers=headers, data=body, timeout=timeout)
        elif method.upper() == "DELETE":
            response = await context.request.delete(url, headers=headers, timeout=timeout)
        else:
            return f"错误：不支持的 HTTP 方法 '{method}'"
        
        # 构建结果
        result = {
            "status": response.status,
            "statusText": response.status_text,
            "headers": dict(response.headers),
            "url": response.url,
            "ok": response.ok
        }
        
        # 尝试解析响应体
        try:
            text = await response.text()
            if len(text) < 100000:
                result["body"] = text
            else:
                result["body"] = text[:100000] + "\n... (truncated)"
            
            # 尝试解析为 JSON
            try:
                result["json"] = json.loads(text)
            except json.JSONDecodeError:
                pass
        except Exception as e:
            result["body"] = f"<无法读取响应体: {str(e)}>"
        
        return json.dumps(result, ensure_ascii=False, indent=2)
        
    except Exception as e:
        return json.dumps({
            "error": str(e),
            "url": url,
            "method": method
        }, ensure_ascii=False, indent=2)


# ─── 入口 ─────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Browser Use MCP Server")
    parser.add_argument("--sse", action="store_true", help="使用 SSE 传输模式")
    parser.add_argument("--streamable", action="store_true", help="使用 Streamable HTTP 模式")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址")
    parser.add_argument("--port", type=int, default=8765, help="监听端口")
    parser.add_argument("--headless", action="store_true", help="无头模式（默认开启）")
    args = parser.parse_args()

    if not args.headless:
        os.environ["HEADLESS"] = "false"

    if args.sse:
        from mcp.server.sse import SseServerTransport
        from starlette.applications import Starlette
        from starlette.routing import Mount, Route

        sse = SseServerTransport("/messages/")

        async def handle_sse(request):
            async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
                await mcp._mcp_server.run(streams[0], streams[1], mcp._mcp_server.create_initialization_options())

        app = Starlette(
            routes=[
                Route("/sse", endpoint=handle_sse),
                Mount("/messages/", app=sse.handle_post_message),
            ]
        )

        import uvicorn
        print(f"🌐 Browser MCP Server (SSE) running at http://{args.host}:{args.port}/sse", file=sys.stderr)
        uvicorn.run(app, host=args.host, port=args.port)
    elif args.streamable:
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
        from starlette.applications import Starlette
        from starlette.routing import Route

        session_manager = StreamableHTTPSessionManager(
            app=mcp._mcp_server,
            event_store=None,
            json_response=True,
        )

        async def handle_streamable(request):
            from starlette.responses import Response
            scope = request.scope
            receive = request.receive
            send = request._send

            async def _send(msg):
                await send(msg)

            await session_manager.handle_request(scope, receive, _send)

        app = Starlette(routes=[Route("/mcp", endpoint=handle_streamable, methods=["GET", "POST"])])

        import uvicorn
        print(f"🌐 Browser MCP Server (Streamable HTTP) running at http://{args.host}:{args.port}/mcp", file=sys.stderr)
        uvicorn.run(app, host=args.host, port=args.port)
    else:
        # stdio 模式 — 不输出任何内容到 stdout
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
