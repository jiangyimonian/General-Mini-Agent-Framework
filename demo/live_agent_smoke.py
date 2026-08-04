"""Live Agent smoke test using real API.

This script requires a real API key to be set in environment variables.
It is NOT part of the default CI and must be run manually.

Required environment variables:
    GMAF_API_KEY: API key for the LLM service

Optional environment variables:
    GMAF_BASE_URL: Base URL for the API (defaults to OpenAI)
    GMAF_MODEL: Model name to use

Usage:
    # Windows PowerShell
    $env:GMAF_API_KEY = "your-api-key"
    python demo/live_agent_smoke.py

    # Unix
    GMAF_API_KEY=your-api-key python demo/live_agent_smoke.py
"""

from __future__ import annotations

import os

from general_mini_agent import LLM, Agent, LLMConfig, tool


@tool(description="Evaluate a simple integer addition")
def calculator(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


def main() -> int:
    """Run a live agent smoke test with a real API."""
    api_key = os.environ.get("GMAF_API_KEY")
    if not api_key:
        print("ERROR: GMAF_API_KEY environment variable is required")
        print("Set it before running this script:")
        print("  Windows: $env:GMAF_API_KEY = 'your-key'")
        print("  Unix: GMAF_API_KEY=your-key python demo/live_agent_smoke.py")
        return 2

    base_url = os.environ.get("GMAF_BASE_URL")
    model = os.environ.get("GMAF_MODEL", "gpt-4o-mini")

    config = LLMConfig(
        api_key=api_key,
        base_url=base_url,
        model=model,
        timeout=30.0,
        max_retries=2,
    )

    llm = LLM(config)
    try:
        agent = Agent(llm=llm, tools=[calculator], max_iterations=4)
        result = agent.run(
            "Use the calculator tool to compute 19 + 23, then explain the result."
        )

        print(f"Result: {result.content}")
        print(f"Stop reason: {result.stop_reason}")
        print(f"Iterations: {result.iterations}")
        print(f"Usage: {result.usage}")

        return 0 if result.stop_reason == "completed" else 1
    finally:
        llm.close()


if __name__ == "__main__":
    raise SystemExit(main())