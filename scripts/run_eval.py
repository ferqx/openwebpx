from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import docker
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

from backends.docker import DockerBackend

load_dotenv()


class MockRuntime:
    def __init__(self, container_id: str):
        self.state = {"container_id": container_id}
        self.config = {"configurable": {"thread_id": "eval_thread"}}


async def run_eval_task(task: dict[str, Any], client: docker.DockerClient) -> bool:
    print(f"\n[RUNNING TASK] {task['name']} (Level: {task['level']})")

    # 1. Create a temporary container for this task
    print("  -> Creating temporary sandbox container...")
    container = client.containers.run(
        "sandbox-agent:latest", detach=True, tty=True, command="tail -f /dev/null"
    )

    try:
        runtime = MockRuntime(container.id)
        backend = DockerBackend(runtime=runtime)

        # 2. Setup environment
        print("  -> Setting up environment...")
        for cmd in task.get("setup_commands", []):
            backend.execute(cmd)

        # 3. Run Agent
        print(f"  -> Agent is working on: {task['input']}")
        with patch(
            "graphs.build_app_agent_v3.agent.DockerBackend", return_value=backend
        ):
            from graphs.build_app_agent_v3.agent import create_build_app_agent

            agent_executor = create_build_app_agent()

            inputs = {"messages": [HumanMessage(content=task["input"])]}
            await agent_executor.ainvoke(inputs)

        # 4. Verification
        print(f"  -> Verifying with command: {task['verify_command']}")
        result = backend.execute(task["verify_command"])

        if result.exit_code == 0:
            print(f"  [SUCCESS] Task '{task['name']}' passed!")
            return True
        else:
            print(f"  [FAILED] Task '{task['name']}' failed.")
            print(f"    - Exit Code: {result.exit_code}")
            print(f"    - Output: {result.output[:500]}")

            # Debug snapshot on failure
            print("\n  [DEBUG] Snapshot of /workspace after failure:")
            for file_path in [
                "/workspace/models.py",
                "/workspace/auth.py",
                "/workspace/test_auth.py",
                "/workspace/app.py",
                "/workspace/calculator.py",
            ]:
                cat_res = backend.execute(f"cat {file_path}")
                if cat_res.exit_code == 0:
                    print(f"\n--- {file_path} ---\n{cat_res.output}")
            return False
    finally:
        print("  -> Cleaning up container...")
        container.stop()
        container.remove()


async def main():
    client = docker.from_env()
    tasks_path = Path("tests/benchmark/tasks.json")

    if not tasks_path.exists():
        print(f"Error: {tasks_path} not found.")
        return

    with tasks_path.open("r") as f:
        tasks = json.load(f)

    results = []
    # Run all tasks to see the final baseline
    for task in tasks:
        try:
            success = await run_eval_task(task, client)
            results.append((task["name"], success))
        except Exception as e:
            print(f"  [CRITICAL ERROR] Task {task['name']} crashed: {e}")
            results.append((task["name"], False))

    # Summary Table
    print("\n" + "=" * 40)
    print("      AGENT EVALUATION SUMMARY")
    print("=" * 40)
    passed_count = sum(1 for r in results if r[1])
    for name, success in results:
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"- {name:<25}: {status}")

    success_rate = (passed_count / len(tasks)) * 100 if tasks else 0
    print("-" * 40)
    print(f"OVERALL SUCCESS RATE: {success_rate:.1f}% ({passed_count}/{len(tasks)})")
    print("=" * 40 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
