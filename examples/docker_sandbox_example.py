"""Example: Using DockerBackend and DockerMiddleware with deepagents.

This example demonstrates how to create an agent that can execute commands
and manipulate files inside a Docker container.

Prerequisites:
- Docker installed and running
- docker-py installed (already in dependencies)

Run with:
    python examples/docker_sandbox_example.py
"""

import asyncio

import dotenv
from deepagents import create_deep_agent
from langchain.chat_models import init_chat_model
from langchain_core.runnables.config import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver

from backends.docker import DockerBackend
from middleware.docker import DockerMiddleware

dotenv.load_dotenv()


async def main():
    """Run a simple interaction with the Docker sandbox agent."""
    print("Creating agent with Docker sandbox...")
    agent = create_deep_agent(
        model=init_chat_model(model_provider="openai", model="deepseek-chat"),
        backend=DockerBackend,
        middleware=[
            # DockerMiddleware creates and manages the container
            DockerMiddleware(
                image="python:3.12-alpine",
                workdir="/workspace",
                auto_cleanup=True,
                environment={"PYTHONUNBUFFERED": "1"},
            ),
        ],
        checkpointer=InMemorySaver(),
    )

    # Simulate a conversation thread
    config: RunnableConfig = {"configurable": {"thread_id": "test-thread-1"}}

    print("\n--- Testing ls command ---")
    result = agent.invoke(
        {"messages": [{"role": "user", "content": "List files in /workspace"}]},
        config,
    )
    print(f"Agent response: {result}")

    print("\n--- Testing execute command ---")
    result = agent.invoke(
        {"messages": [{"role": "user", "content": "Run 'echo hello world'"}]},
        config,
    )
    print(f"Agent response: {result}")

    print("\n--- Testing write_file and read_file ---")
    result = agent.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": "Create a file /workspace/test.txt with content 'Hello from Docker'",
                }
            ]
        },
        config,
    )
    print(f"Agent response: {result}")

    result = agent.invoke(
        {"messages": [{"role": "user", "content": "Read /workspace/test.txt"}]},
        config,
    )
    print(f"Agent response: {result}")

    print("\nExample completed.")


if __name__ == "__main__":
    asyncio.run(main())
