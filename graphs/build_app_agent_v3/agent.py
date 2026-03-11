"""Create-agent based build-app agent with stricter file-write guards."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from deepagents.middleware.patch_tool_calls import PatchToolCallsMiddleware
from deepagents.middleware.summarization import (
    SummarizationMiddleware,
    _compute_summarization_defaults,
)
from langchain.agents import create_agent
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
    from graphs.build_app_agent_v3.repo_map_middleware import RepoMapMiddleware
except ModuleNotFoundError:
    _module_dir = Path(__file__).resolve().parent
    _module_dir_str = str(_module_dir)
    if _module_dir_str not in sys.path:
        sys.path.insert(0, _module_dir_str)
    from patch_filesystem_middleware import PatchFilesystemMiddleware
    from prompts import build_system_prompt
    from repo_map_middleware import RepoMapMiddleware


def _resolve_model_max_tokens() -> int:
    raw_value = os.getenv("OPENWEBPX_BUILD_APP_AGENT_V3_MAX_TOKENS", "").strip()
    if not raw_value:
        return 4000
    try:
        value = int(raw_value)
    except ValueError:
        return 4000
    return value if value > 0 else 4000


MODEL = init_chat_model(
    model_provider="openai",
    model="deepseek-chat",
    max_tokens=_resolve_model_max_tokens(),
)
SYSTEM_PROMPT = build_system_prompt()
SUMMARIZATION_DEFAULTS = _compute_summarization_defaults(MODEL)

_middleware: list[AgentMiddleware[Any, Any, Any]] = []
_middleware.extend(
    [
        build_web_sandbox_docker_middleware(),
        SummarizationMiddleware(
            model=MODEL,
            backend=DockerBackend,
            trigger=SUMMARIZATION_DEFAULTS["trigger"],
            keep=SUMMARIZATION_DEFAULTS["keep"],
            trim_tokens_to_summarize=None,
            truncate_args_settings=SUMMARIZATION_DEFAULTS["truncate_args_settings"],
        ),
        PatchFilesystemMiddleware(
            backend=DockerBackend,
        ),
        RepoMapMiddleware(),
        PatchToolCallsMiddleware(),
    ]
)

agent = create_agent(
    model=MODEL,
    system_prompt=SYSTEM_PROMPT,
    middleware=_middleware,
).with_config({"recursion_limit": 1000})
