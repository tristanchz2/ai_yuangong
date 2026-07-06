from openai import OpenAI

client = OpenAI(
    api_key="你的API Key",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
)

# 定义你需要的字段结构
tools = [
    {
        "type": "function",
        "function": {
            "name": "extract_project_info",
            "description": "从文本中提取项目相关信息",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_name": {
                        "type": "string",
                        "description": "项目名称"
                    },
                    "service_location": {
                        "type": "string",
                        "description": "服务地点，格式要求：省-市-区，例如：广东省-深圳市"
                    },
                    "budget": {
                        "type": "number",
                        "description": "预算金额，格式要求：纯数字，单位为元"
                    }
                },
                "required": ["project_name", "service_location", "budget"]
            }
        }
    }
]

response = client.chat.completions.create(
    model="qwen-plus",  # 或 qwen-max
    messages=[
        {"role": "system", "content": "你是一个信息提取助手，请严格按照要求从文本中提取信息。"},
        {"role": "user", "content": f"请从以下文本中提取项目信息：\n\n{你的长文本}"}
    ],
    tools=tools,
    tool_choice={"type": "function", "function": {"name": "extract_project_info"}}
)

# 解析结果
import json
result = json.loads(response.choices[0].message.tool_calls[0].function.arguments)
print(result)
# 输出示例：{"project_name": "智慧城市项目", "service_location": "广东省-深圳市-南山区", "budget": "150.5"}
