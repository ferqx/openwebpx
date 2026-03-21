"""Create-agent based build-app agent with stricter file-write guards."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from deepagents.middleware.patch_tool_calls import PatchToolCallsMiddleware
from deepagents.middleware.skills import SkillsMiddleware
from deepagents.middleware.summarization import (
    SummarizationMiddleware,
    _compute_summarization_defaults,
)
from langchain.agents import create_agent
from langchain.agents.middleware import (
    ClearToolUsesEdit,
    ContextEditingMiddleware,
    ModelRetryMiddleware,
)
from langchain.agents.middleware.types import AgentMiddleware
from langchain.chat_models import init_chat_model

from backends.docker import DockerBackend
from middleware.docker import build_web_sandbox_docker_middleware

# LangGraph API may load this file as a standalone module (graphs.<graph_id>).
# Fallback to sibling imports to avoid package-resolution failures.
try:
    from graphs.build_app_agent_v3.patch_filesystem_middleware import (
        PatchFilesystemMiddleware,
    )
    from graphs.build_app_agent_v3.prompts import build_system_prompt
    from graphs.build_app_agent_v3.think_tool_middleware import ThinkToolMiddleware
except ModuleNotFoundError:
    _module_dir = Path(__file__).resolve().parent
    _module_dir_str = str(_module_dir)
    if _module_dir_str not in sys.path:
        sys.path.insert(0, _module_dir_str)
    from patch_filesystem_middleware import PatchFilesystemMiddleware
    from prompts import build_system_prompt
    from think_tool_middleware import ThinkToolMiddleware


def _resolve_model_max_tokens() -> int:
    raw_value = os.getenv("OPENWEBPX_BUILD_APP_AGENT_V3_MAX_TOKENS", "").strip()
    if not raw_value:
        return 4000
    try:
        value = int(raw_value)
    except ValueError:
        return 4000
    return value if value > 0 else 4000


def _think_tool_enabled() -> bool:
    raw_value = os.getenv("OPENWEBPX_BUILD_APP_AGENT_V3_THINK_TOOL", "").strip()
    if not raw_value:
        return False
    return raw_value.lower() in {"1", "true", "yes", "on"}


MODEL = init_chat_model(
    model_provider="openai",
    model="deepseek-chat",
    max_tokens=_resolve_model_max_tokens(),
)
THINK_TOOL_ENABLED = _think_tool_enabled()
SYSTEM_PROMPT = build_system_prompt(think_tool_enabled=THINK_TOOL_ENABLED)
SUMMARIZATION_DEFAULTS = _compute_summarization_defaults(MODEL)


def create_build_app_agent(model: Any = None) -> Any:
    """Create the build-app agent with the specified model and middleware."""
    actual_model = model or MODEL
    actual_system_prompt = build_system_prompt(think_tool_enabled=THINK_TOOL_ENABLED)
    actual_summarization_defaults = _compute_summarization_defaults(actual_model)

    middleware: list[AgentMiddleware[Any, Any, Any]] = [
        ModelRetryMiddleware(
            max_retries=3,
            backoff_factor=2.0,
            initial_delay=1.0,
        ),
        build_web_sandbox_docker_middleware(),
        SummarizationMiddleware(
            model=actual_model,
            backend=DockerBackend,
            trigger=actual_summarization_defaults["trigger"],
            keep=actual_summarization_defaults["keep"],
            trim_tokens_to_summarize=None,
            truncate_args_settings=actual_summarization_defaults[
                "truncate_args_settings"
            ],
        ),
        *([ThinkToolMiddleware()] if THINK_TOOL_ENABLED else []),
        PatchFilesystemMiddleware(
            backend=DockerBackend,
        ),
        PatchToolCallsMiddleware(),
        ContextEditingMiddleware(
            edits=[
                ClearToolUsesEdit(
                    trigger=100000,
                    keep=3,
                    placeholder="自动压缩",
                ),
            ],
        ),
        SkillsMiddleware(
            backend=DockerBackend,
            sources=[
                "/workspace/.agents/skills/",
                "/workspace/.roo/skills/",
                "/workspace/.skills/",
            ],
        ),
    ]

    return create_agent(
        model=actual_model,
        system_prompt=actual_system_prompt,
        middleware=middleware,
    ).with_config({"recursion_limit": 1000})


agent = create_build_app_agent()
