# tools/browser_executor.py
# 这是一个"哑巴执行器"——它不决定看什么，只负责执行传给它的指令
import asyncio
import sys
import json
from browser_use import Agent

async def execute(prompt: str, url: str, output_file: str):
    print(f"🚀 browser-use 启动，执行指令：\n{prompt}\n")
    
    agent = Agent(
        task=prompt,
        url=url,
        use_vision=True,
        generate_gif=False,
    )
    
    result = await agent.run()
    
    # 把原始输出写入文件，aider 会自己去读
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(result.final_result())
    
    print(f"✅ 执行完成，结果已写入 {output_file}")

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("用法: python browser_executor.py <url> <prompt> <output_file>")
        sys.exit(1)
    
    url = sys.argv[1]
    prompt = sys.argv[2]
    output_file = sys.argv[3]
    
    asyncio.run(execute(prompt, url, output_file))