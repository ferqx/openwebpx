from __future__ import annotations

import pytest
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

from graphs.build_app_agent_v3.agent import agent

load_dotenv()


@pytest.mark.asyncio
async def test_agent_real_write_and_read() -> None:
    """A real-world smoke test verifying that Agent can WRITE and then READ files."""
    print("\nStarting real agent write/read integration test...")

    # Task: Create a file and then verify it
    task = "Create a file named test_ok.txt with content 'Hello from Integration Test' and then list the directory."
    inputs = {"messages": [HumanMessage(content=task)]}

    final_result = await agent.ainvoke(inputs)
    final_answer = final_result["messages"][-1].content

    print(f"Final Agent Answer: {final_answer}")

    # Verification: The agent should confirm the creation and mention the filename
    assert "test_ok.txt" in final_answer.lower()
    assert "hello" in final_answer.lower()
