"""Docker sandbox agent scenario runner.

用于快速验证 DockerBackend + DockerMiddleware 在多种场景下的行为：
- 基础命令/文件操作
- Web 项目初始化与启动
- 运行时报错注入与自修复
- 多线程隔离

运行示例：
    python examples/docker_sandbox_example.py --scenario smoke
    python examples/docker_sandbox_example.py --scenario runtime_repair
    python examples/docker_sandbox_example.py --scenario all --model deepseek-chat
"""

from __future__ import annotations

import argparse
from uuid import uuid4

import dotenv
from deepagents import create_deep_agent
from langchain.chat_models import init_chat_model
from langchain_core.messages import BaseMessage
from langchain_core.runnables.config import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver

from backends.docker import DockerBackend
from middleware.docker import DockerMiddleware

dotenv.load_dotenv()

SANDBOX_BIND_HOST = "0.0.0.0"  # nosec B104 - 预览场景必须绑定全接口


def _create_agent(model_name: str, *, fixed_host_ports: bool):
    """创建用于场景测试的 Docker 沙箱 agent。"""
    ports: dict[str, int | None] = (
        {
            "5173/tcp": 5173,
        }
        if fixed_host_ports
        else {
            "5173/tcp": None,
        }
    )

    return create_deep_agent(
        model=init_chat_model(model_provider="openai", model=model_name),
        backend=DockerBackend,
        middleware=[
            DockerMiddleware(
                image="sandbox-agent:latest",
                workdir="/workspace",
                ports=ports,
                environment={
                    "HOST": SANDBOX_BIND_HOST,
                    "PYTHONUNBUFFERED": "1",
                },
                auto_start_service=True,
                default_container_port=5173,
                max_restart_attempts=2,
            ),
        ],
        checkpointer=InMemorySaver(),
    )


def _extract_last_ai_text(result: dict) -> str:
    """提取最后一条 AI 消息文本，便于 CLI 直读。"""
    messages = result.get("messages", [])
    if not messages:
        return "<no messages>"

    last: BaseMessage = messages[-1]
    content = getattr(last, "content", "")
    if isinstance(content, str):
        return content
    return str(content)


def _print_runtime_hint(result: dict) -> None:
    """打印运行态端口提示，避免误以为固定是 localhost:5173。"""
    service_status = result.get("service_status")
    if not isinstance(service_status, dict):
        return

    container_id = result.get("container_id") or service_status.get("container_id")
    preview_urls = service_status.get("preview_urls", [])
    probes = service_status.get("preview_probes", {})
    port_bindings = service_status.get("port_bindings", {})

    print(f"  [runtime] container_id={container_id}")
    if isinstance(port_bindings, dict) and port_bindings:
        print(f"  [runtime] port_bindings={port_bindings}")

    if isinstance(preview_urls, list) and preview_urls:
        print("  [runtime] preview_urls:")
        for url in preview_urls:
            probe = probes.get(url) if isinstance(probes, dict) else None
            print(f"    - {url} (probe={probe})")
    else:
        print("  [runtime] 暂无可用 preview_urls（服务可能尚未启动）")


def _invoke(agent, thread_id: str, prompt: str) -> dict:
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    print(f"\n[thread={thread_id}] USER: {prompt}")
    result = agent.invoke({"messages": [{"role": "user", "content": prompt}]}, config)
    print(f"[thread={thread_id}] AI: {_extract_last_ai_text(result)}")
    _print_runtime_hint(result)
    return result


def scenario_smoke(agent, thread_id: str) -> None:
    """基础连通性：命令执行 + 环境信息。"""
    _invoke(agent, thread_id, "列出 /workspace 目录，并输出 node 与 npm 版本。")


def scenario_files(agent, thread_id: str) -> None:
    """文件能力：写入、读取、验证。"""
    _invoke(agent, thread_id, "创建 /workspace/demo.txt，内容是 'hello sandbox'.")
    _invoke(agent, thread_id, "读取 /workspace/demo.txt 并告诉我内容。")


def scenario_web_bootstrap(agent, thread_id: str) -> None:
    """Web 启动：初始化最小 Vite React 并尝试启动。"""
    _invoke(
        agent,
        thread_id,
        (
            "在 /workspace 初始化一个最小 React Vite 项目（若目录非空请安全处理），"
            "安装依赖并确认开发服务器可运行。"
        ),
    )


def scenario_runtime_repair(agent, thread_id: str) -> None:
    """运行时自修复：先制造错误，再让 agent 根据诊断修复。"""
    _invoke(
        agent,
        thread_id,
        (
            "创建一个最小 Vite React 页面，并故意在 src/main.jsx 写入语法错误，"
            "然后尝试启动服务。"
        ),
    )
    _invoke(
        agent,
        thread_id,
        "请根据系统 Runtime Diagnostics 修复错误，并再次验证服务可访问。",
    )


def scenario_multi_thread(agent, thread_base: str) -> None:
    """线程隔离：验证两个线程状态互不干扰。"""
    thread_a = f"{thread_base}-a"
    thread_b = f"{thread_base}-b"
    _invoke(agent, thread_a, "创建文件 /workspace/thread.txt 内容为 A。")
    _invoke(agent, thread_b, "创建文件 /workspace/thread.txt 内容为 B。")
    _invoke(agent, thread_a, "读取 /workspace/thread.txt。")
    _invoke(agent, thread_b, "读取 /workspace/thread.txt。")


SCENARIOS = {
    "smoke": scenario_smoke,
    "files": scenario_files,
    "web_bootstrap": scenario_web_bootstrap,
    "runtime_repair": scenario_runtime_repair,
    "multi_thread": scenario_multi_thread,
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run docker sandbox agent scenarios.")
    parser.add_argument(
        "--scenario",
        choices=["all", *SCENARIOS.keys()],
        default="smoke",
        help="要运行的测试场景。",
    )
    parser.add_argument(
        "--model",
        default="deepseek-chat",
        help="模型名（model_provider 固定为 openai）。",
    )
    parser.add_argument(
        "--thread-id",
        default=f"sandbox-example-{uuid4().hex[:8]}",
        help="线程 ID（all 模式下会基于此派生）。",
    )
    parser.add_argument(
        "--fixed-host-ports",
        action="store_true",
        help=(
            "固定映射宿主机端口（5173/3000/4173/8080）。"
            "仅建议单容器调试，多容器并发可能端口冲突。"
        ),
    )
    args = parser.parse_args()

    print("Creating Docker sandbox agent...")
    if args.fixed_host_ports:
        print("Using fixed host ports: 5173, 3000, 4173, 8080")
    else:
        print("Using dynamic host ports (Docker auto-assigned).")
    agent = _create_agent(args.model, fixed_host_ports=args.fixed_host_ports)

    if args.scenario == "all":
        for name, handler in SCENARIOS.items():
            print(f"\n==================== Scenario: {name} ====================")
            if name == "multi_thread":
                handler(agent, f"{args.thread_id}-{name}")
            else:
                handler(agent, f"{args.thread_id}-{name}")
        print("\nAll scenarios completed.")
        return

    handler = SCENARIOS[args.scenario]
    if args.scenario == "multi_thread":
        handler(agent, args.thread_id)
    else:
        handler(agent, args.thread_id)
    print("\nScenario completed.")


if __name__ == "__main__":
    main()
