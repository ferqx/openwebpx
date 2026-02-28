"""Create-agent based build-app agent with stricter file-write guards."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from deepagents.middleware.filesystem import FilesystemMiddleware
from deepagents.middleware.patch_tool_calls import PatchToolCallsMiddleware
from deepagents.middleware.summarization import (
    SummarizationMiddleware,
    _compute_summarization_defaults,
)
from langchain.agents import create_agent
from langchain.agents.middleware import TodoListMiddleware
from langchain.agents.middleware.types import AgentMiddleware
from langchain.chat_models import init_chat_model
from langchain_anthropic.middleware import AnthropicPromptCachingMiddleware

from backends.docker import DockerBackend
from middleware.docker import build_web_sandbox_docker_middleware

# LangGraph API may load this file as a standalone module (graphs.<graph_id>).
# Fallback to sibling imports to avoid package-resolution failures.
try:
    from graphs.build_app_agent_v2.guard_middleware import ToolCallGuardMiddleware
    from graphs.build_app_agent_v2.prompts import build_system_prompt
except ModuleNotFoundError:
    _module_dir = Path(__file__).resolve().parent
    _module_dir_str = str(_module_dir)
    if _module_dir_str not in sys.path:
        sys.path.insert(0, _module_dir_str)
    from guard_middleware import ToolCallGuardMiddleware
    from prompts import build_system_prompt


def _infer_prompt_profile(model_provider: str, model_name: str) -> str:
    """Infer prompt overlay profile from provider/model string."""
    normalized = f"{model_provider}/{model_name}".lower()
    if "deepseek" in normalized:
        return "deepseek"
    if "anthropic" in normalized or "claude" in normalized:
        return "claude"
    if "codex" in normalized or "gpt-5" in normalized or "openai" in normalized:
        return "codex"
    return "codex"


def _read_bool_env(name: str, default: bool) -> bool:
    """Parse boolean feature flag from env."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _read_int_env(name: str, default: int) -> int:
    """Parse integer feature flag from env."""
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        parsed = int(raw.strip())
    except ValueError:
        return default
    return parsed if parsed > 0 else default


MODEL_PROVIDER = os.getenv("BUILD_APP_AGENT_V2_MODEL_PROVIDER", "openai")
MODEL_NAME = os.getenv("BUILD_APP_AGENT_V2_MODEL", "deepseek-chat")
PROMPT_PROFILE = os.getenv(
    "BUILD_APP_AGENT_V2_PROFILE",
    _infer_prompt_profile(MODEL_PROVIDER, MODEL_NAME),
)

ENABLE_TODO_MIDDLEWARE = _read_bool_env("BUILD_APP_AGENT_V2_ENABLE_TODOS", False)
ENABLE_ANTHROPIC_CACHE = _read_bool_env(
    "BUILD_APP_AGENT_V2_ENABLE_ANTHROPIC_CACHE",
    PROMPT_PROFILE == "claude",
)

MAX_WRITES_PER_FILE_PER_ROUND = _read_int_env(
    "BUILD_APP_AGENT_V2_MAX_WRITES_PER_FILE_PER_ROUND",
    2 if PROMPT_PROFILE == "deepseek" else 3,
)
MAX_WRITES_PER_FILE_TOTAL = _read_int_env(
    "BUILD_APP_AGENT_V2_MAX_WRITES_PER_FILE_TOTAL",
    0,
)
MAX_EDIT_CALLS_PER_FILE_TOTAL = _read_int_env(
    "BUILD_APP_AGENT_V2_MAX_EDIT_CALLS_PER_FILE_TOTAL",
    6 if PROMPT_PROFILE == "deepseek" else 8,
)
SMALL_EDIT_CHAR_THRESHOLD = _read_int_env(
    "BUILD_APP_AGENT_V2_SMALL_EDIT_CHAR_THRESHOLD",
    160,
)
MAX_SMALL_EDITS_PER_FILE_TOTAL = _read_int_env(
    "BUILD_APP_AGENT_V2_MAX_SMALL_EDITS_PER_FILE_TOTAL",
    4 if PROMPT_PROFILE == "deepseek" else 6,
)

MODEL = init_chat_model(model_provider=MODEL_PROVIDER, model=MODEL_NAME)
SYSTEM_PROMPT = build_system_prompt(PROMPT_PROFILE)
SUMMARIZATION_DEFAULTS = _compute_summarization_defaults(MODEL)

EDIT_FILE_DESCRIPTION = """
Performs exact string replacements in files.

Usage constraints:
- For the same file, first collect all intended changes, then apply one merged edit.
- Avoid tiny sequential edits for a single file (especially CSS/theme changes).
- If a file requires many scattered updates, read the file once and perform one consolidated write.
- Do not narrate intermediate micro-steps between partial edits; execute then summarize.
""".strip()

_middleware: list[AgentMiddleware[Any, Any, Any]] = []

if ENABLE_TODO_MIDDLEWARE:
    _middleware.append(TodoListMiddleware())

_middleware.extend(
    [
        FilesystemMiddleware(
            backend=DockerBackend,
            custom_tool_descriptions={"edit_file": EDIT_FILE_DESCRIPTION},
        ),
        SummarizationMiddleware(
            model=MODEL,
            backend=DockerBackend,
            trigger=SUMMARIZATION_DEFAULTS["trigger"],
            keep=SUMMARIZATION_DEFAULTS["keep"],
            trim_tokens_to_summarize=None,
            truncate_args_settings=SUMMARIZATION_DEFAULTS["truncate_args_settings"],
        ),
    ]
)

if ENABLE_ANTHROPIC_CACHE:
    _middleware.append(
        AnthropicPromptCachingMiddleware(unsupported_model_behavior="ignore")
    )

_middleware.extend(
    [
        PatchToolCallsMiddleware(),
        ToolCallGuardMiddleware(
            max_writes_per_file_per_round=MAX_WRITES_PER_FILE_PER_ROUND,
            max_writes_per_file_total=MAX_WRITES_PER_FILE_TOTAL,
            max_edit_calls_per_file_total=MAX_EDIT_CALLS_PER_FILE_TOTAL,
            small_edit_char_threshold=SMALL_EDIT_CHAR_THRESHOLD,
            max_small_edits_per_file_total=MAX_SMALL_EDITS_PER_FILE_TOTAL,
        ),
        build_web_sandbox_docker_middleware(),
    ]
)

agent = create_agent(
    model=MODEL,
    system_prompt=SYSTEM_PROMPT,
    middleware=_middleware,
).with_config({"recursion_limit": 1000})
