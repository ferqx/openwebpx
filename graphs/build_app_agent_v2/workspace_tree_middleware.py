"""Attach latest workspace tree snapshot into system prompt before model calls."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, cast

from deepagents.middleware._utils import append_to_system_message
from langchain.agents.middleware.types import (
    AgentMiddleware,
    ContextT,
    ModelRequest,
    ModelResponse,
    ResponseT,
)

DEFAULT_EXCLUDES = (
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
)


class WorkspaceTreeMiddleware(AgentMiddleware[Any, ContextT, ResponseT]):
    """Bind latest workspace directory structure to system prompt."""

    def __init__(
        self,
        *,
        workspace_root: str = "/workspace",
        max_depth: int = 4,
        max_entries: int = 300,
        excludes: tuple[str, ...] = DEFAULT_EXCLUDES,
    ) -> None:
        self.workspace_root = workspace_root
        self.max_depth = max_depth if max_depth > 0 else 4
        self.max_entries = max_entries if max_entries > 0 else 300
        self.excludes = excludes

    def _build_find_command(self) -> str:
        quoted_root = self.workspace_root.replace('"', '\\"')
        exclude_clause = " -o ".join(f"-name '{item}'" for item in self.excludes)
        return (
            f'cd "{quoted_root}" && '
            f"find . -maxdepth {self.max_depth} "
            f"\\( {exclude_clause} \\) -prune -o -print "
            "2>/dev/null | sed 's|^\\./||' | sort | "
            f"head -n {self.max_entries}"
        )

    def _build_prompt_block(self, tree_output: str) -> str:
        content = tree_output.strip() or "(empty workspace)"
        return (
            "## Latest Workspace Structure\n"
            "Refresh this snapshot before planning edits.\n"
            "```\n"
            f"{content}\n"
            "```"
        )

    def _build_backend(self, runtime: Any) -> Any:
        """Cast runtime to Any to satisfy DockerBackend constructor typing."""
        from backends.docker import DockerBackend

        typed_runtime = cast("Any", runtime)
        return DockerBackend(typed_runtime)

    def wrap_model_call(
        self,
        request: ModelRequest[ContextT],
        handler: Callable[[ModelRequest[ContextT]], ModelResponse[ResponseT]],
    ) -> ModelResponse[ResponseT]:
        try:
            backend = self._build_backend(request.runtime)
            command = self._build_find_command()
            result = backend.execute(command)
            block = self._build_prompt_block(result.output)
            new_system_message = append_to_system_message(request.system_message, block)
            request = request.override(system_message=new_system_message)
        except Exception:
            return handler(request)
        return handler(request)

    async def awrap_model_call(
        self,
        request: ModelRequest[ContextT],
        handler: Callable[
            [ModelRequest[ContextT]], Awaitable[ModelResponse[ResponseT]]
        ],
    ) -> ModelResponse[ResponseT]:
        try:
            backend = self._build_backend(request.runtime)
            command = self._build_find_command()
            result = await backend.aexecute(command)
            block = self._build_prompt_block(result.output)
            new_system_message = append_to_system_message(request.system_message, block)
            request = request.override(system_message=new_system_message)
        except Exception:
            return await handler(request)
        return await handler(request)
