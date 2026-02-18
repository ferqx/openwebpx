from deepagents import create_deep_agent
from langchain.chat_models import init_chat_model

from backends.docker import DockerBackend
from middleware.docker import DockerMiddleware

# 沙盒预览通过端口映射访问，容器内服务必须绑定到全接口。
SANDBOX_BIND_HOST = "0.0.0.0"  # nosec B104

WEB_BUILDER_PROMPT = """你是一个 Web 应用构建 Agent，运行在 Docker 沙盒内（Node.js 环境）。

你的核心目标：
1. 根据用户需求生成/修改 Web 应用代码。
2. 在代码变更后主动运行或重启应用。
3. 主动根据系统注入的 Runtime Diagnostics 进行故障修复，直到服务可访问。

执行约束：
- 优先使用项目脚本（`npm|pnpm|yarn run dev/start/preview`）。
- 服务必须监听 `0.0.0.0`，确保容器外可访问。
- 每轮修改后都要验证运行状态（启动日志、端口、HTTP 可达性）。
- 如果看到 Runtime Diagnostics 报错，先修根因再继续实现需求。
"""

agent = create_deep_agent(
    system_prompt=WEB_BUILDER_PROMPT,
    backend=DockerBackend,
    middleware=[
        DockerMiddleware(
            image="node:20-bookworm",
            ports={
                "5173/tcp": None,
                "3000/tcp": None,
                "4173/tcp": None,
                "8080/tcp": None,
            },
            environment={"HOST": SANDBOX_BIND_HOST},
            auto_start_service=True,
            default_container_port=5173,
            healthcheck_path="/",
        )
    ],
    model=init_chat_model(model_provider="openai", model="deepseek-chat"),
)
