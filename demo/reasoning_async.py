"""异步 Agent 示例。

展示 AsyncLLM、AsyncAgent 和工具 timeout 配置。
运行前需要从 .env.example 创建 .env 并配置有效密钥。
"""

import asyncio
import os

from dotenv import load_dotenv

from general_mini_agent import (
    AsyncAgent,
    AsyncLLM,
    InMemoryConversation,
    LLMConfig,
    TokenBudgetContext,
    tool,
)


@tool(description="获取当前天气（模拟）")
async def get_weather(city: str) -> dict:
    """获取指定城市的天气信息（模拟）。

    Args:
        city: 城市名称
    """
    # 模拟异步操作
    await asyncio.sleep(0.1)
    return {
        "city": city,
        "temperature": 25,
        "condition": "晴朗",
        "humidity": 60,
    }


@tool(description="计算两个数的和")
async def add_numbers(a: int, b: int) -> int:
    """异步计算两个整数的和。

    Args:
        a: 第一个整数
        b: 第二个整数
    """
    await asyncio.sleep(0.01)
    return a + b


async def main() -> None:
    """异步主入口。"""
    load_dotenv()

    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    base_url = os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
    model = os.getenv("LLM_MODEL", "deepseek-chat")

    if not api_key:
        print("请配置 DEEPSEEK_API_KEY 环境变量")
        return

    config = LLMConfig(
        api_key=api_key,
        base_url=base_url,
        model=model,
    )

    # 使用 async with 管理 AsyncLLM 生命周期
    async with AsyncLLM(config) as llm:
        # 创建异步 Agent，配置工具 timeout
        agent = AsyncAgent(
            llm=llm,
            tools=[get_weather, add_numbers],
            memory=InMemoryConversation(),
            context_policy=TokenBudgetContext(
                context_window=65536,
                reserved_output_tokens=4096,
            ),
            default_tool_timeout=5.0,  # 工具执行超时 5 秒
        )

        # 运行异步 Agent
        result = await agent.run_async("北京今天天气怎么样？如果温度高于20度，计算 17 + 25")

        print(f"回答: {result.content}")
        print(f"迭代次数: {result.iterations}")
        print(f"停止原因: {result.stop_reason}")
        print(f"工具调用: {len([e for e in result.trace if e['type'] == 'tool_call'])}")


if __name__ == "__main__":
    asyncio.run(main())