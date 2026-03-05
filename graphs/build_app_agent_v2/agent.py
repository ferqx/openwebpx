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
from langchain_openai import ChatOpenAI

from backends.docker import DockerBackend
from middleware.docker import build_web_sandbox_docker_middleware

# LangGraph API may load this file as a standalone module (graphs.<graph_id>).
# Fallback to sibling imports to avoid package-resolution failures.
try:
    from graphs.build_app_agent_v2.patch_filesystem_middleware import (
        PatchFilesystemMiddleware,
    )
    from graphs.build_app_agent_v2.prompts import build_system_prompt
    from graphs.build_app_agent_v2.workspace_tree_middleware import (
        WorkspaceTreeMiddleware,
    )
except ModuleNotFoundError:
    _module_dir = Path(__file__).resolve().parent
    _module_dir_str = str(_module_dir)
    if _module_dir_str not in sys.path:
        sys.path.insert(0, _module_dir_str)
    from patch_filesystem_middleware import PatchFilesystemMiddleware
    from prompts import build_system_prompt
    from workspace_tree_middleware import WorkspaceTreeMiddleware


def _read_bool_env(name: str, default: bool) -> bool:
    """Parse boolean feature flag from env."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


MODEL_NAME = os.getenv("BUILD_APP_AGENT_V2_MODEL", "deepseek-chat")

ENABLE_TODO_MIDDLEWARE = _read_bool_env("BUILD_APP_AGENT_V2_ENABLE_TODOS", False)
ENABLE_ANTHROPIC_CACHE = _read_bool_env(
    "BUILD_APP_AGENT_V2_ENABLE_ANTHROPIC_CACHE",
    False,
)

MODEL = ChatOpenAI(model=MODEL_NAME)
SYSTEM_PROMPT = build_system_prompt()
SUMMARIZATION_DEFAULTS = _compute_summarization_defaults(MODEL)

APPLY_PATCH_DESCRIPTION = """
Apply a single merged patch with minimal hunks.

Recommended flow:
1. First call `apply_patch` with `dry_run=true` to validate matching and preconditions.
2. If dry-run passes, call the same patch with `dry_run=false` to commit.
3. If dry-run fails, re-read target file and regenerate the patch with exact context.
""".strip()

_middleware: list[AgentMiddleware[Any, Any, Any]] = []
_middleware.extend(
    [
        build_web_sandbox_docker_middleware(),
        PatchFilesystemMiddleware(
            backend=DockerBackend,
            custom_tool_descriptions={
                "apply_patch": APPLY_PATCH_DESCRIPTION,
            },
        ),
        WorkspaceTreeMiddleware(),
        SummarizationMiddleware(
            model=MODEL,
            backend=DockerBackend,
            trigger=SUMMARIZATION_DEFAULTS["trigger"],
            keep=SUMMARIZATION_DEFAULTS["keep"],
            trim_tokens_to_summarize=None,
            truncate_args_settings=SUMMARIZATION_DEFAULTS["truncate_args_settings"],
        ),
        PatchToolCallsMiddleware(),
    ]
)

agent = create_agent(
    model=MODEL,
    system_prompt=SYSTEM_PROMPT,
    middleware=_middleware,
).with_config({"recursion_limit": 1000})
