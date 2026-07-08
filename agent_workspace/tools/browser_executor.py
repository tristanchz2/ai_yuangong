# tools/browser_executor.py
# 这是一个"哑巴执行器"——它不决定看什么，只负责执行传给它的指令
import asyncio
import argparse
import os


def _load_env():
    """Load .env from project root (simple parser, no extra deps)."""
    env_path = os.path.join(os.path.dirname(__file__), '..', '..', '.env')
    env_path = os.path.abspath(env_path)
    if not os.path.exists(env_path):
        print(f"[WARN] .env not found at {env_path}")
        print(f"  Copy .env.example → .env and fill in your API key.")
        return
    with open(env_path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' in line:
                key, _, value = line.partition('=')
                os.environ.setdefault(key.strip(), value.strip())


async def execute(prompt: str, output_file: str):
    from browser_use import Agent
    from browser_use.browser.browser import Browser, BrowserConfig
    from browser_use.browser.context import BrowserContextConfig
    from langchain_openai import ChatOpenAI

    model_name = os.environ.get('OPENAI_MODEL', 'qwen3.7-plus')
    api_key = os.environ.get('OPENAI_API_KEY', '')
    base_url = os.environ.get('OPENAI_BASE_URL', 'https://coding.dashscope.aliyuncs.com/v1')

    llm = ChatOpenAI(
        model=model_name,
        api_key=api_key,
        base_url=base_url,
        temperature=0.0,
        max_tokens=8096,
    )

    # 标准 Chrome UA，避免被识别为自动化工具
    chrome_ua = (
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/138.0.0.0 Safari/537.36'
    )

    browser = Browser(
        config=BrowserConfig(
            headless=False,
            disable_security=True,
            new_context_config=BrowserContextConfig(
                user_agent=chrome_ua,
                minimum_wait_page_load_time=2,
                wait_for_network_idle_page_load_time=2,
            ),
        )
    )

    print(f"[>] browser-use 启动 (model={model_name})，执行指令：\n{prompt}\n")

    agent = Agent(
        task=prompt,
        llm=llm,
        browser=browser,
        use_vision=True,
    )

    result = await agent.run()

    output = result.final_result() or ''
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(output)

    print(f"[OK] 执行完成，结果已写入 {output_file}")


if __name__ == "__main__":
    _load_env()

    parser = argparse.ArgumentParser(description="browser-use 哑巴执行器")
    parser.add_argument("--prompt-file", required=True, help="包含 prompt 的文件路径")
    parser.add_argument("--output-file", required=True, help="侦察结果保存路径")
    args = parser.parse_args()

    with open(args.prompt_file, "r", encoding="utf-8") as f:
        prompt = f.read().strip()

    asyncio.run(execute(prompt, args.output_file))
