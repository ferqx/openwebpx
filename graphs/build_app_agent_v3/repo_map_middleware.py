"""Attach repository directory map into system prompt before model calls."""

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


class RepoMapMiddleware(AgentMiddleware[Any, ContextT, ResponseT]):
    """Bind latest repository tree snapshot to system prompt."""

    def __init__(
        self,
        *,
        repo_root: str = "/workspace",
        max_depth: int = 4,
        max_entries: int = 800,
        excludes: tuple[str, ...] = DEFAULT_EXCLUDES,
    ) -> None:
        self.repo_root = repo_root
        self.max_depth = max_depth if max_depth > 0 else 4
        self.max_entries = max_entries if max_entries > 0 else 800
        self.excludes = excludes

    def _build_find_command(self) -> str:
        quoted_root = self.repo_root.replace('"', '\\"')
        exclude_clause = " -o ".join(f"-name '{item}'" for item in self.excludes)
        git_listing = "git ls-files --cached --others --exclude-standard | sort -u"
        fallback_find = (
            f"find . -maxdepth {self.max_depth} "
            f"\\( {exclude_clause} \\) -prune -o -type f -print "
            "2>/dev/null | sed 's|^\\./||' | sort"
        )
        with_line_counts = (
            "while IFS= read -r path; do "
            '[ -z "$path" ] && continue; '
            'if [ -f "$path" ]; then '
            "lines=$(wc -l < \"$path\" 2>/dev/null || printf '?'); "
            'printf \'%s\\t%s\\n\' "$path" "$lines"; '
            "fi; "
            "done"
        )
        return (
            f'cd "{quoted_root}" && '
            f"(git rev-parse --is-inside-work-tree >/dev/null 2>&1 && {git_listing} "
            f"|| {fallback_find}) | head -n {self.max_entries} | {with_line_counts}"
        )

    def _build_prompt_block(self, tree_output: str) -> str:
        content = self._format_repo_map_with_line_counts(tree_output)
        return (
            "## Latest Repo Map\n"
            "Use this snapshot as the authoritative repository structure context.\n"
            "Each entry is `path<TAB>line_count`.\n"
            "```text\n"
            f"{content}\n"
            "```"
        )

    def _format_repo_map_with_line_counts(self, tree_output: str) -> str:
        raw = tree_output.strip()
        if not raw:
            return "(empty repository)"

        formatted_lines: list[str] = []
        for line in raw.splitlines():
            if not line.strip():
                continue
            if "\t" not in line:
                formatted_lines.append(line.strip())
                continue
            path, line_count = line.split("\t", 1)
            path = path.strip()
            line_count = line_count.strip() or "?"
            formatted_lines.append(f"{path} (lines: {line_count})")

        return "\n".join(formatted_lines) if formatted_lines else "(empty repository)"

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
            print("wrap_model_call new_system_message", new_system_message)
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
            print("awrap_model_call new_system_message", new_system_message)
            request = request.override(system_message=new_system_message)
        except Exception:
            return await handler(request)
        return await handler(request)
