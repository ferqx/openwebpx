"""Filesystem middleware that enforces V4A-style apply_patch edits."""

from __future__ import annotations

import json
import re
import shlex
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal, cast
from urllib.parse import parse_qs, quote, unquote, urlparse

from deepagents.backends.protocol import BackendProtocol, SandboxBackendProtocol
from deepagents.backends.utils import validate_path
from deepagents.middleware.filesystem import FilesystemMiddleware, FilesystemState
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.prebuilt.tool_node import ToolRuntime

_FILE_HEADER_RE = re.compile(r"^\*\*\* (Add|Update|Delete) File:\s*(.+?)\s*$")
_HUNK_HEADER_RE = re.compile(r"^@@(?:\s+.*)?$")

APPLY_PATCH_TOOL_DESCRIPTION = """
Apply a structured V4A patch to files.

You must pass one `patch_content` string using this format:
- `*** Update File: /absolute/path`
- `*** Add File: /absolute/path`
- `*** Delete File: /absolute/path`
- For `Update File`, each change must be in its own `@@ ...` block.

Each update hunk should include:
1. 1-3 lines of unchanged context before the change
2. zero or more `-` lines (old code)
3. one or more `+` lines (new code)
4. 1-3 lines of unchanged context after the change

Hard requirements:
- For the same file, merge all related hunks into a single `*** Update File` section.
- For insert-only hunks (no `-` lines), include `context_before` or `context_after`.
- Do not split one file's edits across multiple tool calls.
- Use absolute file paths.
- Prefer `apply_patch` for existing files; use `write_file` only for net-new files.
""".strip()

READ_FILES_TOOL_DESCRIPTION = """
Batch-read multiple files in one call.

Use this tool when you need to inspect several known files together.
This is the preferred alternative to many repeated `read_file` calls.

Guidelines:
- Pass absolute file paths.
- Keep `file_paths` focused; the tool deduplicates paths automatically.
- Use one batch call first, then only follow-up reads for genuinely missing context.
""".strip()

LIST_COMPONENTS_TOOL_DESCRIPTION = """
List components by scanning component entry files (for example `*/index.ts`).

Use this tool first for questions like:
- "这个组件库有哪些组件"
- "列出组件清单"

It avoids recursive directory traversal and returns a concise inventory quickly.
""".strip()

LIST_RESOURCES_TOOL_DESCRIPTION = """
List resources in a scoped directory using pattern filtering.

Use this as the default repository discovery entrypoint instead of repeated ls/glob loops.
It returns resource URIs (for example `file:///workspace/app/main.py`) that can be passed
to `read_resource`.
""".strip()

READ_RESOURCE_TOOL_DESCRIPTION = """
Read one resource by URI or absolute path.

Supported forms:
- `file:///absolute/path`
- `symbol://<symbol>?path=/absolute/path&start=<line>&end=<line>`
- `callers://<symbol>?path=/absolute/path&line=<line>`
- `/absolute/path`

Use this when you already have a resource URI from `list_resources`.
""".strip()

GET_IMPLEMENTATION_TOOL_DESCRIPTION = """
Resolve symbol implementation candidates and return symbol resource URIs.

Use this for requests like:
- "show implementation of OrderService"
- "find where function createClient is defined"
""".strip()

FIND_CALLERS_TOOL_DESCRIPTION = """
Find call/reference sites of a symbol and return caller resource URIs.

Use this for requests like:
- "who calls OrderService"
- "where is createClient used"
""".strip()

SUBMIT_EDIT_PLAN_TOOL_DESCRIPTION = """
Submit the full edit plan before any write operation.

Call this once before `apply_patch` / `write_file` and include:
- `plan_summary`: short summary of intended changes
- `target_files`: complete file list to be modified in this run
- optional `change_groups`: grouped change bullets

This enforces plan-then-act and prevents fragmented micro-edits.
""".strip()


@dataclass(frozen=True, slots=True)
class V4AHunk:
    """A single V4A update hunk."""

    header: str
    context_before: tuple[str, ...]
    old_lines: tuple[str, ...]
    new_lines: tuple[str, ...]
    context_after: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class V4AFilePatch:
    """A V4A patch section scoped to one file."""

    action: Literal["Add", "Update", "Delete"]
    path: str
    hunks: tuple[V4AHunk, ...] = ()
    add_lines: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PatchCommitAction:
    """A planned commit action produced by patch dry-run."""

    action: Literal["Add", "Update", "Delete"]
    path: str
    before_content: str | None = None
    after_content: str | None = None
    applied_hunks: int = 0


def parse_v4a_patch_content(patch_content: str) -> tuple[V4AFilePatch, ...]:
    """Parse V4A patch content into structured file operations."""
    stripped = _strip_fence(patch_content)
    if not stripped:
        raise ValueError("Patch content is empty.")

    lines = stripped.splitlines()
    patches: list[V4AFilePatch] = []
    seen_paths: set[str] = set()

    current_action: Literal["Add", "Update", "Delete"] | None = None
    current_path: str | None = None
    current_body: list[str] = []

    for raw_line in lines:
        line = raw_line.strip()
        if line in {"*** Begin Patch", "*** End Patch"}:
            continue

        header_match = _FILE_HEADER_RE.match(line)
        if header_match:
            if current_action is not None and current_path is not None:
                patches.append(
                    _build_file_patch(
                        action=current_action,
                        path=current_path,
                        body_lines=current_body,
                        seen_paths=seen_paths,
                    )
                )
            current_action = cast(
                'Literal["Add", "Update", "Delete"]',
                header_match.group(1),
            )
            current_path = header_match.group(2).strip()
            current_body = []
            continue

        if current_action is None:
            if line:
                raise ValueError(
                    "Patch must start with `*** Add/Update/Delete File: <path>`."
                )
            continue

        current_body.append(raw_line)

    if current_action is not None and current_path is not None:
        patches.append(
            _build_file_patch(
                action=current_action,
                path=current_path,
                body_lines=current_body,
                seen_paths=seen_paths,
            )
        )

    if not patches:
        raise ValueError("No valid file patch sections were found.")

    return tuple(patches)


def apply_v4a_update_patch(
    original_content: str,
    *,
    file_path: str,
    hunks: tuple[V4AHunk, ...],
) -> tuple[str, int]:
    """Apply parsed V4A update hunks to file content."""
    updated_content = original_content
    applied_count = 0

    for index, hunk in enumerate(hunks, start=1):
        updated_content = _apply_single_hunk(
            updated_content,
            file_path=file_path,
            hunk=hunk,
            hunk_index=index,
        )
        applied_count += 1

    return updated_content, applied_count


class V4AFilesystemMiddleware(FilesystemMiddleware):
    """Filesystem middleware that replaces `edit_file` with `apply_patch`."""

    def __init__(
        self,
        *,
        backend: (
            BackendProtocol | None | Callable[[ToolRuntime], BackendProtocol]
        ) = None,
        system_prompt: str | None = None,
        custom_tool_descriptions: dict[str, str] | None = None,
        tool_token_limit_before_evict: int | None = 20_000,
        max_execute_timeout: int = 3_600,
    ) -> None:
        super().__init__(
            backend=backend,
            system_prompt=system_prompt,
            custom_tool_descriptions=custom_tool_descriptions,
            tool_token_limit_before_evict=tool_token_limit_before_evict,
            max_execute_timeout=max_execute_timeout,
        )
        self.tools = [tool for tool in self.tools if tool.name != "edit_file"]
        self.tools.append(self._create_submit_edit_plan_tool())
        self.tools.append(self._create_apply_patch_tool())
        self.tools.append(self._create_list_resources_tool())
        self.tools.append(self._create_get_implementation_tool())
        self.tools.append(self._create_find_callers_tool())
        self.tools.append(self._create_read_resource_tool())
        self.tools.append(self._create_read_files_tool())
        self.tools.append(self._create_list_components_tool())

    def _create_submit_edit_plan_tool(self) -> BaseTool:
        description = self._custom_tool_descriptions.get("submit_edit_plan")
        if description is None:
            description = SUBMIT_EDIT_PLAN_TOOL_DESCRIPTION

        def sync_submit_edit_plan(
            plan_summary: Annotated[
                str,
                "Short summary of the complete planned modifications.",
            ],
            target_files: Annotated[
                list[str],
                "Absolute file paths that will be modified in this run.",
            ],
            change_groups: Annotated[
                list[str] | None,
                "Optional grouped bullet points of planned changes.",
            ] = None,
        ) -> str:
            return self._submit_edit_plan_result(
                plan_summary=plan_summary,
                target_files=target_files,
                change_groups=change_groups,
            )

        async def async_submit_edit_plan(
            plan_summary: Annotated[
                str,
                "Short summary of the complete planned modifications.",
            ],
            target_files: Annotated[
                list[str],
                "Absolute file paths that will be modified in this run.",
            ],
            change_groups: Annotated[
                list[str] | None,
                "Optional grouped bullet points of planned changes.",
            ] = None,
        ) -> str:
            return self._submit_edit_plan_result(
                plan_summary=plan_summary,
                target_files=target_files,
                change_groups=change_groups,
            )

        return StructuredTool.from_function(
            name="submit_edit_plan",
            description=description,
            func=sync_submit_edit_plan,
            coroutine=async_submit_edit_plan,
        )

    def _create_apply_patch_tool(self) -> BaseTool:
        description = self._custom_tool_descriptions.get("apply_patch")
        if description is None:
            description = APPLY_PATCH_TOOL_DESCRIPTION

        def sync_apply_patch(
            patch_content: Annotated[
                str,
                (
                    "Full V4A patch content. Must contain one or more "
                    "`*** Add/Update/Delete File: /absolute/path` sections."
                ),
            ],
            runtime: ToolRuntime[None, FilesystemState],
            dry_run: Annotated[
                bool,
                "Validate patch match/applicability only; do not write files.",
            ] = False,
        ) -> str:
            backend = self._get_backend(runtime)
            return self._apply_patch_sync(
                backend,
                patch_content,
                dry_run=dry_run,
            )

        async def async_apply_patch(
            patch_content: Annotated[
                str,
                (
                    "Full V4A patch content. Must contain one or more "
                    "`*** Add/Update/Delete File: /absolute/path` sections."
                ),
            ],
            runtime: ToolRuntime[None, FilesystemState],
            dry_run: Annotated[
                bool,
                "Validate patch match/applicability only; do not write files.",
            ] = False,
        ) -> str:
            backend = self._get_backend(runtime)
            return await self._apply_patch_async(
                backend,
                patch_content,
                dry_run=dry_run,
            )

        return StructuredTool.from_function(
            name="apply_patch",
            description=description,
            func=sync_apply_patch,
            coroutine=async_apply_patch,
        )

    def _create_read_files_tool(self) -> BaseTool:
        description = self._custom_tool_descriptions.get("read_files")
        if description is None:
            description = READ_FILES_TOOL_DESCRIPTION

        def sync_read_files(
            file_paths: Annotated[
                list[str],
                "Absolute file paths to read as one batch.",
            ],
            runtime: ToolRuntime[None, FilesystemState],
            offset: Annotated[
                int,
                "Line number to start from (0-indexed), applied to each file.",
            ] = 0,
            limit: Annotated[
                int,
                "Maximum lines per file, applied to each file.",
            ] = 120,
        ) -> str:
            backend = self._get_backend(runtime)
            return self._read_files_sync(
                backend=backend,
                file_paths=file_paths,
                offset=offset,
                limit=limit,
            )

        async def async_read_files(
            file_paths: Annotated[
                list[str],
                "Absolute file paths to read as one batch.",
            ],
            runtime: ToolRuntime[None, FilesystemState],
            offset: Annotated[
                int,
                "Line number to start from (0-indexed), applied to each file.",
            ] = 0,
            limit: Annotated[
                int,
                "Maximum lines per file, applied to each file.",
            ] = 120,
        ) -> str:
            backend = self._get_backend(runtime)
            return await self._read_files_async(
                backend=backend,
                file_paths=file_paths,
                offset=offset,
                limit=limit,
            )

        return StructuredTool.from_function(
            name="read_files",
            description=description,
            func=sync_read_files,
            coroutine=async_read_files,
        )

    def _create_list_resources_tool(self) -> BaseTool:
        description = self._custom_tool_descriptions.get("list_resources")
        if description is None:
            description = LIST_RESOURCES_TOOL_DESCRIPTION

        def sync_list_resources(
            runtime: ToolRuntime[None, FilesystemState],
            scope: Annotated[
                str,
                "Absolute directory scope for resource discovery.",
            ] = "/workspace",
            pattern: Annotated[
                str,
                "Glob pattern under scope (for example '**/*.py').",
            ] = "*",
            resource_kind: Annotated[
                Literal["file", "directory", "all"],
                "Resource kind filter.",
            ] = "all",
            limit: Annotated[
                int,
                "Maximum number of resources to return.",
            ] = 200,
        ) -> str:
            backend = self._get_backend(runtime)
            return self._list_resources_sync(
                backend=backend,
                scope=scope,
                pattern=pattern,
                resource_kind=resource_kind,
                limit=limit,
            )

        async def async_list_resources(
            runtime: ToolRuntime[None, FilesystemState],
            scope: Annotated[
                str,
                "Absolute directory scope for resource discovery.",
            ] = "/workspace",
            pattern: Annotated[
                str,
                "Glob pattern under scope (for example '**/*.py').",
            ] = "*",
            resource_kind: Annotated[
                Literal["file", "directory", "all"],
                "Resource kind filter.",
            ] = "all",
            limit: Annotated[
                int,
                "Maximum number of resources to return.",
            ] = 200,
        ) -> str:
            backend = self._get_backend(runtime)
            return await self._list_resources_async(
                backend=backend,
                scope=scope,
                pattern=pattern,
                resource_kind=resource_kind,
                limit=limit,
            )

        return StructuredTool.from_function(
            name="list_resources",
            description=description,
            func=sync_list_resources,
            coroutine=async_list_resources,
        )

    def _create_read_resource_tool(self) -> BaseTool:
        description = self._custom_tool_descriptions.get("read_resource")
        if description is None:
            description = READ_RESOURCE_TOOL_DESCRIPTION

        def sync_read_resource(
            uri: Annotated[
                str,
                "Resource URI or absolute file path.",
            ],
            runtime: ToolRuntime[None, FilesystemState],
            offset: Annotated[
                int,
                "Line number to start from (0-indexed).",
            ] = 0,
            limit: Annotated[
                int,
                "Maximum number of lines to read.",
            ] = 200,
        ) -> str:
            backend = self._get_backend(runtime)
            return self._read_resource_sync(
                backend=backend,
                uri=uri,
                offset=offset,
                limit=limit,
            )

        async def async_read_resource(
            uri: Annotated[
                str,
                "Resource URI or absolute file path.",
            ],
            runtime: ToolRuntime[None, FilesystemState],
            offset: Annotated[
                int,
                "Line number to start from (0-indexed).",
            ] = 0,
            limit: Annotated[
                int,
                "Maximum number of lines to read.",
            ] = 200,
        ) -> str:
            backend = self._get_backend(runtime)
            return await self._read_resource_async(
                backend=backend,
                uri=uri,
                offset=offset,
                limit=limit,
            )

        return StructuredTool.from_function(
            name="read_resource",
            description=description,
            func=sync_read_resource,
            coroutine=async_read_resource,
        )

    def _create_get_implementation_tool(self) -> BaseTool:
        description = self._custom_tool_descriptions.get("get_implementation")
        if description is None:
            description = GET_IMPLEMENTATION_TOOL_DESCRIPTION

        def sync_get_implementation(
            symbol: Annotated[
                str,
                "Symbol name to locate (class/function/type).",
            ],
            runtime: ToolRuntime[None, FilesystemState],
            scope: Annotated[
                str,
                "Absolute directory scope for lookup.",
            ] = "/workspace",
            limit: Annotated[
                int,
                "Maximum implementation candidates to return.",
            ] = 10,
        ) -> str:
            backend = self._get_backend(runtime)
            return self._get_implementation_sync(
                backend=backend,
                symbol=symbol,
                scope=scope,
                limit=limit,
            )

        async def async_get_implementation(
            symbol: Annotated[
                str,
                "Symbol name to locate (class/function/type).",
            ],
            runtime: ToolRuntime[None, FilesystemState],
            scope: Annotated[
                str,
                "Absolute directory scope for lookup.",
            ] = "/workspace",
            limit: Annotated[
                int,
                "Maximum implementation candidates to return.",
            ] = 10,
        ) -> str:
            backend = self._get_backend(runtime)
            return await self._get_implementation_async(
                backend=backend,
                symbol=symbol,
                scope=scope,
                limit=limit,
            )

        return StructuredTool.from_function(
            name="get_implementation",
            description=description,
            func=sync_get_implementation,
            coroutine=async_get_implementation,
        )

    def _create_find_callers_tool(self) -> BaseTool:
        description = self._custom_tool_descriptions.get("find_callers")
        if description is None:
            description = FIND_CALLERS_TOOL_DESCRIPTION

        def sync_find_callers(
            symbol: Annotated[
                str,
                "Symbol name to search call/reference sites for.",
            ],
            runtime: ToolRuntime[None, FilesystemState],
            scope: Annotated[
                str,
                "Absolute directory scope for lookup.",
            ] = "/workspace",
            limit: Annotated[
                int,
                "Maximum caller sites to return.",
            ] = 40,
            include_definitions: Annotated[
                bool,
                "Whether definition lines can be included as caller candidates.",
            ] = False,
        ) -> str:
            backend = self._get_backend(runtime)
            return self._find_callers_sync(
                backend=backend,
                symbol=symbol,
                scope=scope,
                limit=limit,
                include_definitions=include_definitions,
            )

        async def async_find_callers(
            symbol: Annotated[
                str,
                "Symbol name to search call/reference sites for.",
            ],
            runtime: ToolRuntime[None, FilesystemState],
            scope: Annotated[
                str,
                "Absolute directory scope for lookup.",
            ] = "/workspace",
            limit: Annotated[
                int,
                "Maximum caller sites to return.",
            ] = 40,
            include_definitions: Annotated[
                bool,
                "Whether definition lines can be included as caller candidates.",
            ] = False,
        ) -> str:
            backend = self._get_backend(runtime)
            return await self._find_callers_async(
                backend=backend,
                symbol=symbol,
                scope=scope,
                limit=limit,
                include_definitions=include_definitions,
            )

        return StructuredTool.from_function(
            name="find_callers",
            description=description,
            func=sync_find_callers,
            coroutine=async_find_callers,
        )

    def _create_list_components_tool(self) -> BaseTool:
        description = self._custom_tool_descriptions.get("list_components")
        if description is None:
            description = LIST_COMPONENTS_TOOL_DESCRIPTION

        def sync_list_components(
            runtime: ToolRuntime[None, FilesystemState],
            root_path: Annotated[
                str,
                "Absolute root path for component directories.",
            ] = "/workspace/packages/components/src",
            index_pattern: Annotated[
                str,
                "Glob pattern used under root_path to detect component entries.",
            ] = "*/index.ts",
        ) -> str:
            backend = self._get_backend(runtime)
            return self._list_components_sync(
                backend=backend,
                root_path=root_path,
                index_pattern=index_pattern,
            )

        async def async_list_components(
            runtime: ToolRuntime[None, FilesystemState],
            root_path: Annotated[
                str,
                "Absolute root path for component directories.",
            ] = "/workspace/packages/components/src",
            index_pattern: Annotated[
                str,
                "Glob pattern used under root_path to detect component entries.",
            ] = "*/index.ts",
        ) -> str:
            backend = self._get_backend(runtime)
            return await self._list_components_async(
                backend=backend,
                root_path=root_path,
                index_pattern=index_pattern,
            )

        return StructuredTool.from_function(
            name="list_components",
            description=description,
            func=sync_list_components,
            coroutine=async_list_components,
        )

    def _submit_edit_plan_result(
        self,
        *,
        plan_summary: str,
        target_files: list[str],
        change_groups: list[str] | None,
    ) -> str:
        """Validate and summarize submit_edit_plan payload."""
        summary = plan_summary.strip()
        if not summary:
            return self._error_result(
                error_code="PLAN_INVALID",
                message="`plan_summary` must be a non-empty string.",
                details={"field": "plan_summary"},
                retryable=True,
            )

        deduped_files, files_truncated = self._normalize_batch_paths(
            target_files,
            max_files=50,
        )
        if not deduped_files:
            return self._error_result(
                error_code="PLAN_INVALID",
                message="`target_files` must contain at least one absolute file path.",
                details={"field": "target_files"},
                retryable=True,
            )

        filtered_groups: list[str] = []
        if isinstance(change_groups, list):
            for group in change_groups:
                if not isinstance(group, str):
                    continue
                stripped = group.strip()
                if stripped:
                    filtered_groups.append(stripped)
                if len(filtered_groups) >= 20:
                    break

        result_lines = [
            f"Plan accepted for {len(deduped_files)} file(s).",
            f"Summary: {summary}",
        ]
        if files_truncated:
            result_lines.append(
                "Note: target_files was truncated to first 50 unique paths."
            )
        if filtered_groups:
            result_lines.append(f"Change groups: {len(filtered_groups)}")
        return self._ok_result(
            message=" ".join(result_lines),
            details={
                "target_files_count": len(deduped_files),
                "target_files": deduped_files,
                "change_groups_count": len(filtered_groups),
                "files_truncated": files_truncated,
            },
        )

    def _kernel_result(
        self,
        *,
        ok: bool,
        message: str,
        error_code: str | None = None,
        details: dict[str, Any] | None = None,
        retryable: bool = False,
    ) -> str:
        """Return a structured, machine-readable tool result payload."""
        payload = {
            "ok": ok,
            "error_code": error_code,
            "message": message,
            "details": details or {},
            "retryable": retryable,
        }
        return json.dumps(payload, ensure_ascii=False)

    def _ok_result(
        self,
        *,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> str:
        return self._kernel_result(
            ok=True,
            message=message,
            details=details,
        )

    def _error_result(
        self,
        *,
        error_code: str,
        message: str,
        details: dict[str, Any] | None = None,
        retryable: bool = False,
    ) -> str:
        return self._kernel_result(
            ok=False,
            error_code=error_code,
            message=message,
            details=details,
            retryable=retryable,
        )

    def _map_patch_match_error_code(self, message: str) -> str:
        normalized = message.lower()
        if "ambiguous" in normalized:
            return "PATCH_AMBIGUOUS_MATCH"
        if "did not match existing content" in normalized:
            return "PATCH_NO_MATCH"
        if "insert-only hunk" in normalized:
            return "PATCH_PARSE_ERROR"
        return "PATCH_APPLY_ERROR"

    def _resource_query_first(
        self,
        query: dict[str, list[str]],
        key: str,
    ) -> str | None:
        values = query.get(key) or []
        if not values:
            return None
        value = values[0].strip()
        return value or None

    def _parse_positive_int(
        self,
        raw: str | None,
        *,
        field: str,
        min_value: int = 1,
    ) -> tuple[int | None, str | None]:
        if raw is None:
            return None, None
        try:
            parsed = int(raw)
        except ValueError:
            return None, f"`{field}` must be an integer."
        if parsed < min_value:
            return None, f"`{field}` must be >= {min_value}."
        return parsed, None

    def _normalize_symbol_name(self, raw_symbol: str) -> str:
        normalized = raw_symbol.strip()
        if not normalized:
            return ""
        normalized = normalized.split("::")[-1]
        normalized = normalized.split(".")[-1]
        return normalized.strip()

    def _is_symbol_definition_line(self, line: str, symbol_name: str) -> bool:
        escaped = re.escape(symbol_name)
        patterns = (
            rf"^\s*(?:async\s+def|def|class)\s+{escaped}\b",
            rf"^\s*(?:export\s+)?(?:async\s+)?function\s+{escaped}\b",
            rf"^\s*(?:export\s+)?class\s+{escaped}\b",
            rf"^\s*(?:export\s+)?interface\s+{escaped}\b",
            rf"^\s*(?:export\s+)?type\s+{escaped}\b",
            rf"^\s*(?:export\s+)?(?:const|let|var)\s+{escaped}\b",
            rf"^\s*{escaped}\s*\(",
        )
        return any(re.search(pattern, line) is not None for pattern in patterns)

    def _iter_source_paths_sync(
        self,
        *,
        backend: BackendProtocol,
        scope: str,
        max_files: int = 800,
    ) -> list[str]:
        patterns = ("**/*.py", "**/*.ts", "**/*.tsx", "**/*.js", "**/*.jsx")
        seen: set[str] = set()
        for pattern in patterns:
            infos = backend.glob_info(pattern, path=scope)
            for info in infos:
                path = str(info.get("path", "")).strip()
                if not path or bool(info.get("is_dir", False)):
                    continue
                seen.add(path)
                if len(seen) >= max_files:
                    return sorted(seen)
        return sorted(seen)

    async def _iter_source_paths_async(
        self,
        *,
        backend: BackendProtocol,
        scope: str,
        max_files: int = 800,
    ) -> list[str]:
        patterns = ("**/*.py", "**/*.ts", "**/*.tsx", "**/*.js", "**/*.jsx")
        seen: set[str] = set()
        for pattern in patterns:
            infos = await backend.aglob_info(pattern, path=scope)
            for info in infos:
                path = str(info.get("path", "")).strip()
                if not path or bool(info.get("is_dir", False)):
                    continue
                seen.add(path)
                if len(seen) >= max_files:
                    return sorted(seen)
        return sorted(seen)

    def _build_symbol_resource_uri(
        self,
        *,
        scheme: Literal["symbol", "callers"],
        symbol: str,
        path: str,
        start: int,
        end: int,
        line: int | None = None,
    ) -> str:
        encoded_symbol = quote(symbol, safe="")
        encoded_path = quote(path, safe="/")
        query_parts = [f"path={encoded_path}", f"start={start}", f"end={end}"]
        if line is not None:
            query_parts.append(f"line={line}")
        return f"{scheme}://{encoded_symbol}?{'&'.join(query_parts)}"

    def _resolve_resource_target(
        self,
        *,
        uri: str,
        offset: int,
        limit: int,
    ) -> tuple[dict[str, Any] | None, str | None, str | None]:
        raw = uri.strip()
        if not raw:
            return None, "RESOURCE_URI_INVALID", "`uri` must be a non-empty string."

        if "://" not in raw:
            try:
                path = validate_path(raw)
            except ValueError as exc:
                return None, "RESOURCE_URI_INVALID", str(exc)
            return (
                {
                    "resource_type": "file",
                    "symbol": None,
                    "path": path,
                    "read_offset": offset,
                    "read_limit": limit,
                    "resolved_uri": f"file://{path}",
                },
                None,
                None,
            )

        parsed = urlparse(raw)
        scheme = parsed.scheme
        if scheme == "file":
            if parsed.netloc and parsed.netloc not in {"", "localhost"}:
                return (
                    None,
                    "RESOURCE_URI_INVALID",
                    f"Unsupported file URI host '{parsed.netloc}'.",
                )
            try:
                path = validate_path(parsed.path)
            except ValueError as exc:
                return None, "RESOURCE_URI_INVALID", str(exc)
            return (
                {
                    "resource_type": "file",
                    "symbol": None,
                    "path": path,
                    "read_offset": offset,
                    "read_limit": limit,
                    "resolved_uri": f"file://{path}",
                },
                None,
                None,
            )

        if scheme not in {"symbol", "callers"}:
            return (
                None,
                "RESOURCE_SCHEME_UNSUPPORTED",
                f"Unsupported resource URI scheme '{scheme}'.",
            )

        query = parse_qs(parsed.query)
        path_raw = self._resource_query_first(query, "path")
        if path_raw is None:
            return (
                None,
                "RESOURCE_URI_INVALID",
                "Resource URI must include query parameter `path`.",
            )
        try:
            path = validate_path(unquote(path_raw))
        except ValueError as exc:
            return None, "RESOURCE_URI_INVALID", str(exc)

        symbol_raw = unquote(parsed.netloc or parsed.path.lstrip("/"))
        symbol_name = self._normalize_symbol_name(symbol_raw)
        if not symbol_name:
            return None, "RESOURCE_URI_INVALID", "Resource URI is missing symbol name."

        start_raw = self._resource_query_first(query, "start")
        end_raw = self._resource_query_first(query, "end")
        line_raw = self._resource_query_first(query, "line")
        context_raw = self._resource_query_first(query, "context")

        if (
            scheme == "callers"
            and line_raw is not None
            and start_raw is None
            and end_raw is None
        ):
            line_value, line_error = self._parse_positive_int(line_raw, field="line")
            if line_error is not None or line_value is None:
                return None, "RESOURCE_QUERY_INVALID", line_error
            context_value, context_error = self._parse_positive_int(
                context_raw,
                field="context",
                min_value=1,
            )
            if context_error is not None:
                return None, "RESOURCE_QUERY_INVALID", context_error
            context_size = context_value or 8
            start_value = max(1, line_value - context_size)
            end_value = line_value + context_size
        else:
            start_value, start_error = self._parse_positive_int(
                start_raw, field="start"
            )
            if start_error is not None:
                return None, "RESOURCE_QUERY_INVALID", start_error
            end_value, end_error = self._parse_positive_int(end_raw, field="end")
            if end_error is not None:
                return None, "RESOURCE_QUERY_INVALID", end_error
            start_value = start_value or 1
            if end_value is None:
                end_value = start_value + max(limit, 1) - 1
            if end_value < start_value:
                return None, "RESOURCE_QUERY_INVALID", "`end` must be >= `start`."
            line_value, line_error = self._parse_positive_int(line_raw, field="line")
            if line_error is not None:
                return None, "RESOURCE_QUERY_INVALID", line_error

        read_offset = max(0, start_value - 1 + offset)
        effective_start = start_value + offset
        available = end_value - effective_start + 1
        if available <= 0:
            return (
                None,
                "RESOURCE_QUERY_INVALID",
                "Requested offset exceeds resource span.",
            )
        read_limit = min(limit, available)
        line_number = line_value if "line_value" in locals() else None

        return (
            {
                "resource_type": scheme,
                "symbol": symbol_name,
                "path": path,
                "read_offset": read_offset,
                "read_limit": read_limit,
                "line": line_number,
                "resolved_uri": self._build_symbol_resource_uri(
                    scheme=cast("Literal['symbol', 'callers']", scheme),
                    symbol=symbol_name,
                    path=path,
                    start=effective_start,
                    end=effective_start + read_limit - 1,
                    line=line_number,
                ),
            },
            None,
            None,
        )

    def _get_implementation_sync(
        self,
        *,
        backend: BackendProtocol,
        symbol: str,
        scope: str,
        limit: int,
    ) -> str:
        symbol_name = self._normalize_symbol_name(symbol)
        if not symbol_name:
            return self._error_result(
                error_code="RESOURCE_QUERY_INVALID",
                message="`symbol` must be a non-empty string.",
                details={"field": "symbol"},
                retryable=True,
            )
        if limit <= 0:
            return self._error_result(
                error_code="RESOURCE_QUERY_INVALID",
                message="`limit` must be > 0.",
                details={"field": "limit"},
                retryable=True,
            )
        try:
            validated_scope = validate_path(scope)
        except ValueError as exc:
            return self._error_result(
                error_code="RESOURCE_QUERY_INVALID",
                message=str(exc),
                details={"field": "scope"},
                retryable=True,
            )

        items: list[dict[str, Any]] = []
        source_paths = self._iter_source_paths_sync(
            backend=backend,
            scope=validated_scope,
        )
        truncated = False
        for path in source_paths:
            content, read_error = self._read_file_sync(backend, path)
            if read_error is not None or content is None:
                continue
            lines = content.splitlines()
            for line_number, line in enumerate(lines, start=1):
                if not self._is_symbol_definition_line(line, symbol_name):
                    continue
                start = max(1, line_number - 2)
                end = min(len(lines), line_number + 80)
                items.append(
                    {
                        "uri": self._build_symbol_resource_uri(
                            scheme="symbol",
                            symbol=symbol_name,
                            path=path,
                            start=start,
                            end=end,
                        ),
                        "path": path,
                        "symbol": symbol_name,
                        "line": line_number,
                        "preview": line.strip(),
                    }
                )
                if len(items) >= limit:
                    truncated = True
                    break
            if len(items) >= limit:
                break

        if not items:
            return self._error_result(
                error_code="RESOURCE_SYMBOL_NOT_FOUND",
                message=f"Unable to find implementation for symbol '{symbol_name}'.",
                details={"symbol": symbol_name, "scope": validated_scope},
                retryable=True,
            )

        return self._ok_result(
            message=f"Found {len(items)} implementation candidate(s) for '{symbol_name}'.",
            details={
                "symbol": symbol_name,
                "scope": validated_scope,
                "returned": len(items),
                "truncated": truncated,
                "items": items,
            },
        )

    async def _get_implementation_async(
        self,
        *,
        backend: BackendProtocol,
        symbol: str,
        scope: str,
        limit: int,
    ) -> str:
        symbol_name = self._normalize_symbol_name(symbol)
        if not symbol_name:
            return self._error_result(
                error_code="RESOURCE_QUERY_INVALID",
                message="`symbol` must be a non-empty string.",
                details={"field": "symbol"},
                retryable=True,
            )
        if limit <= 0:
            return self._error_result(
                error_code="RESOURCE_QUERY_INVALID",
                message="`limit` must be > 0.",
                details={"field": "limit"},
                retryable=True,
            )
        try:
            validated_scope = validate_path(scope)
        except ValueError as exc:
            return self._error_result(
                error_code="RESOURCE_QUERY_INVALID",
                message=str(exc),
                details={"field": "scope"},
                retryable=True,
            )

        items: list[dict[str, Any]] = []
        source_paths = await self._iter_source_paths_async(
            backend=backend,
            scope=validated_scope,
        )
        truncated = False
        for path in source_paths:
            content, read_error = await self._read_file_async(backend, path)
            if read_error is not None or content is None:
                continue
            lines = content.splitlines()
            for line_number, line in enumerate(lines, start=1):
                if not self._is_symbol_definition_line(line, symbol_name):
                    continue
                start = max(1, line_number - 2)
                end = min(len(lines), line_number + 80)
                items.append(
                    {
                        "uri": self._build_symbol_resource_uri(
                            scheme="symbol",
                            symbol=symbol_name,
                            path=path,
                            start=start,
                            end=end,
                        ),
                        "path": path,
                        "symbol": symbol_name,
                        "line": line_number,
                        "preview": line.strip(),
                    }
                )
                if len(items) >= limit:
                    truncated = True
                    break
            if len(items) >= limit:
                break

        if not items:
            return self._error_result(
                error_code="RESOURCE_SYMBOL_NOT_FOUND",
                message=f"Unable to find implementation for symbol '{symbol_name}'.",
                details={"symbol": symbol_name, "scope": validated_scope},
                retryable=True,
            )

        return self._ok_result(
            message=f"Found {len(items)} implementation candidate(s) for '{symbol_name}'.",
            details={
                "symbol": symbol_name,
                "scope": validated_scope,
                "returned": len(items),
                "truncated": truncated,
                "items": items,
            },
        )

    def _find_callers_sync(
        self,
        *,
        backend: BackendProtocol,
        symbol: str,
        scope: str,
        limit: int,
        include_definitions: bool,
    ) -> str:
        symbol_name = self._normalize_symbol_name(symbol)
        if not symbol_name:
            return self._error_result(
                error_code="RESOURCE_QUERY_INVALID",
                message="`symbol` must be a non-empty string.",
                details={"field": "symbol"},
                retryable=True,
            )
        if limit <= 0:
            return self._error_result(
                error_code="RESOURCE_QUERY_INVALID",
                message="`limit` must be > 0.",
                details={"field": "limit"},
                retryable=True,
            )
        try:
            validated_scope = validate_path(scope)
        except ValueError as exc:
            return self._error_result(
                error_code="RESOURCE_QUERY_INVALID",
                message=str(exc),
                details={"field": "scope"},
                retryable=True,
            )

        symbol_ref = re.compile(rf"\b{re.escape(symbol_name)}\b")
        items: list[dict[str, Any]] = []
        source_paths = self._iter_source_paths_sync(
            backend=backend,
            scope=validated_scope,
        )
        truncated = False
        for path in source_paths:
            content, read_error = self._read_file_sync(backend, path)
            if read_error is not None or content is None:
                continue
            lines = content.splitlines()
            for line_number, line in enumerate(lines, start=1):
                if symbol_ref.search(line) is None:
                    continue
                if not include_definitions and self._is_symbol_definition_line(
                    line,
                    symbol_name,
                ):
                    continue
                start = max(1, line_number - 8)
                end = min(len(lines), line_number + 8)
                items.append(
                    {
                        "uri": self._build_symbol_resource_uri(
                            scheme="callers",
                            symbol=symbol_name,
                            path=path,
                            start=start,
                            end=end,
                            line=line_number,
                        ),
                        "path": path,
                        "symbol": symbol_name,
                        "line": line_number,
                        "preview": line.strip(),
                    }
                )
                if len(items) >= limit:
                    truncated = True
                    break
            if len(items) >= limit:
                break

        if not items:
            return self._error_result(
                error_code="RESOURCE_CALLERS_NOT_FOUND",
                message=f"Unable to find callers for symbol '{symbol_name}'.",
                details={"symbol": symbol_name, "scope": validated_scope},
                retryable=True,
            )

        return self._ok_result(
            message=f"Found {len(items)} caller reference(s) for '{symbol_name}'.",
            details={
                "symbol": symbol_name,
                "scope": validated_scope,
                "returned": len(items),
                "truncated": truncated,
                "items": items,
            },
        )

    async def _find_callers_async(
        self,
        *,
        backend: BackendProtocol,
        symbol: str,
        scope: str,
        limit: int,
        include_definitions: bool,
    ) -> str:
        symbol_name = self._normalize_symbol_name(symbol)
        if not symbol_name:
            return self._error_result(
                error_code="RESOURCE_QUERY_INVALID",
                message="`symbol` must be a non-empty string.",
                details={"field": "symbol"},
                retryable=True,
            )
        if limit <= 0:
            return self._error_result(
                error_code="RESOURCE_QUERY_INVALID",
                message="`limit` must be > 0.",
                details={"field": "limit"},
                retryable=True,
            )
        try:
            validated_scope = validate_path(scope)
        except ValueError as exc:
            return self._error_result(
                error_code="RESOURCE_QUERY_INVALID",
                message=str(exc),
                details={"field": "scope"},
                retryable=True,
            )

        symbol_ref = re.compile(rf"\b{re.escape(symbol_name)}\b")
        items: list[dict[str, Any]] = []
        source_paths = await self._iter_source_paths_async(
            backend=backend,
            scope=validated_scope,
        )
        truncated = False
        for path in source_paths:
            content, read_error = await self._read_file_async(backend, path)
            if read_error is not None or content is None:
                continue
            lines = content.splitlines()
            for line_number, line in enumerate(lines, start=1):
                if symbol_ref.search(line) is None:
                    continue
                if not include_definitions and self._is_symbol_definition_line(
                    line,
                    symbol_name,
                ):
                    continue
                start = max(1, line_number - 8)
                end = min(len(lines), line_number + 8)
                items.append(
                    {
                        "uri": self._build_symbol_resource_uri(
                            scheme="callers",
                            symbol=symbol_name,
                            path=path,
                            start=start,
                            end=end,
                            line=line_number,
                        ),
                        "path": path,
                        "symbol": symbol_name,
                        "line": line_number,
                        "preview": line.strip(),
                    }
                )
                if len(items) >= limit:
                    truncated = True
                    break
            if len(items) >= limit:
                break

        if not items:
            return self._error_result(
                error_code="RESOURCE_CALLERS_NOT_FOUND",
                message=f"Unable to find callers for symbol '{symbol_name}'.",
                details={"symbol": symbol_name, "scope": validated_scope},
                retryable=True,
            )

        return self._ok_result(
            message=f"Found {len(items)} caller reference(s) for '{symbol_name}'.",
            details={
                "symbol": symbol_name,
                "scope": validated_scope,
                "returned": len(items),
                "truncated": truncated,
                "items": items,
            },
        )

    def _list_resources_sync(
        self,
        *,
        backend: BackendProtocol,
        scope: str,
        pattern: str,
        resource_kind: Literal["file", "directory", "all"],
        limit: int,
    ) -> str:
        if limit <= 0:
            return self._error_result(
                error_code="RESOURCE_QUERY_INVALID",
                message="`limit` must be > 0.",
                details={"field": "limit"},
                retryable=True,
            )

        if resource_kind not in {"file", "directory", "all"}:
            return self._error_result(
                error_code="RESOURCE_QUERY_INVALID",
                message="`resource_kind` must be one of: file, directory, all.",
                details={"field": "resource_kind"},
                retryable=True,
            )

        try:
            validated_scope = validate_path(scope)
        except ValueError as exc:
            return self._error_result(
                error_code="RESOURCE_QUERY_INVALID",
                message=str(exc),
                details={"field": "scope"},
                retryable=True,
            )

        normalized_pattern = pattern.strip() if pattern.strip() else "*"
        infos = backend.glob_info(normalized_pattern, path=validated_scope)

        items: list[dict[str, Any]] = []
        truncated = False
        for info in infos:
            path = str(info.get("path", "")).strip()
            if not path:
                continue
            is_dir = bool(info.get("is_dir", False))
            kind: Literal["file", "directory"] = "directory" if is_dir else "file"
            if resource_kind != "all" and kind != resource_kind:
                continue
            if len(items) >= limit:
                truncated = True
                continue
            items.append(
                {
                    "uri": f"file://{path}",
                    "path": path,
                    "kind": kind,
                }
            )

        return self._ok_result(
            message=f"Listed {len(items)} resource(s).",
            details={
                "scope": validated_scope,
                "pattern": normalized_pattern,
                "resource_kind": resource_kind,
                "returned": len(items),
                "truncated": truncated,
                "items": items,
            },
        )

    async def _list_resources_async(
        self,
        *,
        backend: BackendProtocol,
        scope: str,
        pattern: str,
        resource_kind: Literal["file", "directory", "all"],
        limit: int,
    ) -> str:
        if limit <= 0:
            return self._error_result(
                error_code="RESOURCE_QUERY_INVALID",
                message="`limit` must be > 0.",
                details={"field": "limit"},
                retryable=True,
            )

        if resource_kind not in {"file", "directory", "all"}:
            return self._error_result(
                error_code="RESOURCE_QUERY_INVALID",
                message="`resource_kind` must be one of: file, directory, all.",
                details={"field": "resource_kind"},
                retryable=True,
            )

        try:
            validated_scope = validate_path(scope)
        except ValueError as exc:
            return self._error_result(
                error_code="RESOURCE_QUERY_INVALID",
                message=str(exc),
                details={"field": "scope"},
                retryable=True,
            )

        normalized_pattern = pattern.strip() if pattern.strip() else "*"
        infos = await backend.aglob_info(normalized_pattern, path=validated_scope)

        items: list[dict[str, Any]] = []
        truncated = False
        for info in infos:
            path = str(info.get("path", "")).strip()
            if not path:
                continue
            is_dir = bool(info.get("is_dir", False))
            kind: Literal["file", "directory"] = "directory" if is_dir else "file"
            if resource_kind != "all" and kind != resource_kind:
                continue
            if len(items) >= limit:
                truncated = True
                continue
            items.append(
                {
                    "uri": f"file://{path}",
                    "path": path,
                    "kind": kind,
                }
            )

        return self._ok_result(
            message=f"Listed {len(items)} resource(s).",
            details={
                "scope": validated_scope,
                "pattern": normalized_pattern,
                "resource_kind": resource_kind,
                "returned": len(items),
                "truncated": truncated,
                "items": items,
            },
        )

    def _read_resource_sync(
        self,
        *,
        backend: BackendProtocol,
        uri: str,
        offset: int,
        limit: int,
    ) -> str:
        if offset < 0:
            return self._error_result(
                error_code="RESOURCE_QUERY_INVALID",
                message="`offset` must be >= 0.",
                details={"field": "offset"},
                retryable=True,
            )
        if limit <= 0:
            return self._error_result(
                error_code="RESOURCE_QUERY_INVALID",
                message="`limit` must be > 0.",
                details={"field": "limit"},
                retryable=True,
            )

        target, error_code, error_message = self._resolve_resource_target(
            uri=uri,
            offset=offset,
            limit=limit,
        )
        if target is None:
            return self._error_result(
                error_code=error_code or "RESOURCE_URI_INVALID",
                message=error_message or "Invalid resource URI.",
                details={"uri": uri},
                retryable=True,
            )

        path = str(target.get("path", ""))
        read_offset = int(target.get("read_offset", 0))
        read_limit = int(target.get("read_limit", limit))
        content = backend.read(path, offset=read_offset, limit=read_limit)
        normalized_content = content.strip().lower()
        if normalized_content.startswith("error:"):
            error_code = (
                "RESOURCE_NOT_FOUND"
                if "not found" in normalized_content
                else "RESOURCE_READ_ERROR"
            )
            return self._error_result(
                error_code=error_code,
                message=content.strip(),
                details={"uri": uri, "path": path},
                retryable=error_code != "RESOURCE_NOT_FOUND",
            )

        return self._ok_result(
            message=f"Read resource '{path}'.",
            details={
                "uri": str(target.get("resolved_uri", f"file://{path}")),
                "path": path,
                "resource_type": target.get("resource_type", "file"),
                "symbol": target.get("symbol"),
                "offset": read_offset,
                "limit": read_limit,
                "content": content,
            },
        )

    async def _read_resource_async(
        self,
        *,
        backend: BackendProtocol,
        uri: str,
        offset: int,
        limit: int,
    ) -> str:
        if offset < 0:
            return self._error_result(
                error_code="RESOURCE_QUERY_INVALID",
                message="`offset` must be >= 0.",
                details={"field": "offset"},
                retryable=True,
            )
        if limit <= 0:
            return self._error_result(
                error_code="RESOURCE_QUERY_INVALID",
                message="`limit` must be > 0.",
                details={"field": "limit"},
                retryable=True,
            )

        target, error_code, error_message = self._resolve_resource_target(
            uri=uri,
            offset=offset,
            limit=limit,
        )
        if target is None:
            return self._error_result(
                error_code=error_code or "RESOURCE_URI_INVALID",
                message=error_message or "Invalid resource URI.",
                details={"uri": uri},
                retryable=True,
            )

        path = str(target.get("path", ""))
        read_offset = int(target.get("read_offset", 0))
        read_limit = int(target.get("read_limit", limit))
        content = await backend.aread(path, offset=read_offset, limit=read_limit)
        normalized_content = content.strip().lower()
        if normalized_content.startswith("error:"):
            error_code = (
                "RESOURCE_NOT_FOUND"
                if "not found" in normalized_content
                else "RESOURCE_READ_ERROR"
            )
            return self._error_result(
                error_code=error_code,
                message=content.strip(),
                details={"uri": uri, "path": path},
                retryable=error_code != "RESOURCE_NOT_FOUND",
            )

        return self._ok_result(
            message=f"Read resource '{path}'.",
            details={
                "uri": str(target.get("resolved_uri", f"file://{path}")),
                "path": path,
                "resource_type": target.get("resource_type", "file"),
                "symbol": target.get("symbol"),
                "offset": read_offset,
                "limit": read_limit,
                "content": content,
            },
        )

    def _rollback_actions_sync(
        self,
        backend: BackendProtocol,
        *,
        applied_actions: list[PatchCommitAction],
    ) -> list[dict[str, str]]:
        rollback_errors: list[dict[str, str]] = []
        for action in reversed(applied_actions):
            error: str | None = None
            if action.action == "Add":
                error = self._delete_file_sync(backend, action.path)
            elif action.before_content is None:
                error = (
                    f"Error: Missing rollback snapshot for '{action.path}' "
                    f"({action.action})."
                )
            else:
                error = self._write_file_sync(
                    backend, action.path, action.before_content
                )

            if error is not None:
                rollback_errors.append({"path": action.path, "error": error})
        return rollback_errors

    async def _rollback_actions_async(
        self,
        backend: BackendProtocol,
        *,
        applied_actions: list[PatchCommitAction],
    ) -> list[dict[str, str]]:
        rollback_errors: list[dict[str, str]] = []
        for action in reversed(applied_actions):
            error: str | None = None
            if action.action == "Add":
                error = await self._delete_file_async(backend, action.path)
            elif action.before_content is None:
                error = (
                    f"Error: Missing rollback snapshot for '{action.path}' "
                    f"({action.action})."
                )
            else:
                error = await self._write_file_async(
                    backend,
                    action.path,
                    action.before_content,
                )

            if error is not None:
                rollback_errors.append({"path": action.path, "error": error})
        return rollback_errors

    def _apply_patch_sync(
        self,
        backend: BackendProtocol,
        patch_content: str,
        *,
        dry_run: bool = False,
    ) -> str:
        try:
            file_patches = parse_v4a_patch_content(patch_content)
        except ValueError as exc:
            return self._error_result(
                error_code="PATCH_PARSE_ERROR",
                message=str(exc),
                retryable=True,
            )

        updated_hunks = 0
        changed_files = 0
        commit_actions: list[PatchCommitAction] = []

        for file_patch in file_patches:
            try:
                path = validate_path(file_patch.path)
            except ValueError as exc:
                return self._error_result(
                    error_code="PATCH_PARSE_ERROR",
                    message=str(exc),
                    details={"path": file_patch.path},
                    retryable=True,
                )

            current_content, read_error = self._read_file_sync(backend, path)
            if read_error is not None:
                return self._error_result(
                    error_code="RESOURCE_READ_ERROR",
                    message=read_error,
                    details={"path": path},
                    retryable=True,
                )

            if file_patch.action == "Add":
                if current_content is not None:
                    return self._error_result(
                        error_code="PATCH_PRECONDITION_FAILED",
                        message=f"File '{path}' already exists.",
                        details={"path": path, "action": "Add"},
                        retryable=False,
                    )
                add_content = "\n".join(file_patch.add_lines)
                commit_actions.append(
                    PatchCommitAction(
                        action="Add",
                        path=path,
                        before_content=None,
                        after_content=add_content,
                        applied_hunks=0,
                    )
                )
                changed_files += 1
                continue

            if file_patch.action == "Delete":
                if current_content is None:
                    return self._error_result(
                        error_code="PATCH_PRECONDITION_FAILED",
                        message=f"File '{path}' does not exist.",
                        details={"path": path, "action": "Delete"},
                        retryable=False,
                    )
                commit_actions.append(
                    PatchCommitAction(
                        action="Delete",
                        path=path,
                        before_content=current_content,
                        after_content=None,
                        applied_hunks=0,
                    )
                )
                changed_files += 1
                continue

            if current_content is None:
                return self._error_result(
                    error_code="PATCH_PRECONDITION_FAILED",
                    message=f"File '{path}' does not exist.",
                    details={"path": path, "action": "Update"},
                    retryable=False,
                )

            try:
                updated_content, applied = apply_v4a_update_patch(
                    current_content,
                    file_path=path,
                    hunks=file_patch.hunks,
                )
            except ValueError as exc:
                return self._error_result(
                    error_code=self._map_patch_match_error_code(str(exc)),
                    message=str(exc),
                    details={"path": path, "action": "Update"},
                    retryable=True,
                )

            if updated_content == current_content:
                continue

            commit_actions.append(
                PatchCommitAction(
                    action="Update",
                    path=path,
                    before_content=current_content,
                    after_content=updated_content,
                    applied_hunks=applied,
                )
            )
            updated_hunks += applied
            changed_files += 1

        if dry_run:
            return self._ok_result(
                message="Patch dry-run passed.",
                details={
                    "phase": "dry_run",
                    "matched_files": len(file_patches),
                    "changed_files": changed_files,
                    "hunks_applied": updated_hunks,
                },
            )

        if changed_files == 0:
            return self._ok_result(
                message="Patch parsed, no file changes were needed.",
                details={
                    "phase": "commit",
                    "matched_files": len(file_patches),
                    "changed_files": 0,
                    "hunks_applied": 0,
                },
            )

        applied_actions: list[PatchCommitAction] = []
        for commit_action in commit_actions:
            commit_error: str | None = None
            if commit_action.action in {"Add", "Update"}:
                if commit_action.after_content is None:
                    commit_error = (
                        f"Error: Missing commit content for '{commit_action.path}'."
                    )
                else:
                    commit_error = self._write_file_sync(
                        backend,
                        commit_action.path,
                        commit_action.after_content,
                    )
            elif commit_action.action == "Delete":
                commit_error = self._delete_file_sync(backend, commit_action.path)

            if commit_error is not None:
                rollback_errors = self._rollback_actions_sync(
                    backend,
                    applied_actions=applied_actions,
                )
                return self._error_result(
                    error_code="PATCH_PARTIAL_FORBIDDEN",
                    message=(
                        f"Patch commit failed for '{commit_action.path}'. "
                        "Applied changes were rolled back."
                    ),
                    details={
                        "failed_path": commit_action.path,
                        "failed_action": commit_action.action,
                        "commit_error": commit_error,
                        "rollback_errors": rollback_errors,
                        "rolled_back_actions": len(applied_actions),
                    },
                    retryable=True,
                )

            applied_actions.append(commit_action)

        return self._ok_result(
            message=(
                f"Applied {updated_hunks} update hunk(s) across "
                f"{changed_files} file(s)."
            ),
            details={
                "phase": "commit",
                "matched_files": len(file_patches),
                "changed_files": changed_files,
                "hunks_applied": updated_hunks,
            },
        )

    async def _apply_patch_async(
        self,
        backend: BackendProtocol,
        patch_content: str,
        *,
        dry_run: bool = False,
    ) -> str:
        try:
            file_patches = parse_v4a_patch_content(patch_content)
        except ValueError as exc:
            return self._error_result(
                error_code="PATCH_PARSE_ERROR",
                message=str(exc),
                retryable=True,
            )

        updated_hunks = 0
        changed_files = 0
        commit_actions: list[PatchCommitAction] = []

        for file_patch in file_patches:
            try:
                path = validate_path(file_patch.path)
            except ValueError as exc:
                return self._error_result(
                    error_code="PATCH_PARSE_ERROR",
                    message=str(exc),
                    details={"path": file_patch.path},
                    retryable=True,
                )

            current_content, read_error = await self._read_file_async(backend, path)
            if read_error is not None:
                return self._error_result(
                    error_code="RESOURCE_READ_ERROR",
                    message=read_error,
                    details={"path": path},
                    retryable=True,
                )

            if file_patch.action == "Add":
                if current_content is not None:
                    return self._error_result(
                        error_code="PATCH_PRECONDITION_FAILED",
                        message=f"File '{path}' already exists.",
                        details={"path": path, "action": "Add"},
                        retryable=False,
                    )
                add_content = "\n".join(file_patch.add_lines)
                commit_actions.append(
                    PatchCommitAction(
                        action="Add",
                        path=path,
                        before_content=None,
                        after_content=add_content,
                        applied_hunks=0,
                    )
                )
                changed_files += 1
                continue

            if file_patch.action == "Delete":
                if current_content is None:
                    return self._error_result(
                        error_code="PATCH_PRECONDITION_FAILED",
                        message=f"File '{path}' does not exist.",
                        details={"path": path, "action": "Delete"},
                        retryable=False,
                    )
                commit_actions.append(
                    PatchCommitAction(
                        action="Delete",
                        path=path,
                        before_content=current_content,
                        after_content=None,
                        applied_hunks=0,
                    )
                )
                changed_files += 1
                continue

            if current_content is None:
                return self._error_result(
                    error_code="PATCH_PRECONDITION_FAILED",
                    message=f"File '{path}' does not exist.",
                    details={"path": path, "action": "Update"},
                    retryable=False,
                )

            try:
                updated_content, applied = apply_v4a_update_patch(
                    current_content,
                    file_path=path,
                    hunks=file_patch.hunks,
                )
            except ValueError as exc:
                return self._error_result(
                    error_code=self._map_patch_match_error_code(str(exc)),
                    message=str(exc),
                    details={"path": path, "action": "Update"},
                    retryable=True,
                )

            if updated_content == current_content:
                continue

            commit_actions.append(
                PatchCommitAction(
                    action="Update",
                    path=path,
                    before_content=current_content,
                    after_content=updated_content,
                    applied_hunks=applied,
                )
            )
            updated_hunks += applied
            changed_files += 1

        if dry_run:
            return self._ok_result(
                message="Patch dry-run passed.",
                details={
                    "phase": "dry_run",
                    "matched_files": len(file_patches),
                    "changed_files": changed_files,
                    "hunks_applied": updated_hunks,
                },
            )

        if changed_files == 0:
            return self._ok_result(
                message="Patch parsed, no file changes were needed.",
                details={
                    "phase": "commit",
                    "matched_files": len(file_patches),
                    "changed_files": 0,
                    "hunks_applied": 0,
                },
            )

        applied_actions: list[PatchCommitAction] = []
        for commit_action in commit_actions:
            commit_error: str | None = None
            if commit_action.action in {"Add", "Update"}:
                if commit_action.after_content is None:
                    commit_error = (
                        f"Error: Missing commit content for '{commit_action.path}'."
                    )
                else:
                    commit_error = await self._write_file_async(
                        backend,
                        commit_action.path,
                        commit_action.after_content,
                    )
            elif commit_action.action == "Delete":
                commit_error = await self._delete_file_async(
                    backend, commit_action.path
                )

            if commit_error is not None:
                rollback_errors = await self._rollback_actions_async(
                    backend,
                    applied_actions=applied_actions,
                )
                return self._error_result(
                    error_code="PATCH_PARTIAL_FORBIDDEN",
                    message=(
                        f"Patch commit failed for '{commit_action.path}'. "
                        "Applied changes were rolled back."
                    ),
                    details={
                        "failed_path": commit_action.path,
                        "failed_action": commit_action.action,
                        "commit_error": commit_error,
                        "rollback_errors": rollback_errors,
                        "rolled_back_actions": len(applied_actions),
                    },
                    retryable=True,
                )

            applied_actions.append(commit_action)

        return self._ok_result(
            message=(
                f"Applied {updated_hunks} update hunk(s) across "
                f"{changed_files} file(s)."
            ),
            details={
                "phase": "commit",
                "matched_files": len(file_patches),
                "changed_files": changed_files,
                "hunks_applied": updated_hunks,
            },
        )

    def _normalize_batch_paths(
        self,
        file_paths: list[str],
        *,
        max_files: int = 20,
    ) -> tuple[list[str], bool]:
        """Deduplicate batch paths while preserving order."""
        deduped: list[str] = []
        seen: set[str] = set()
        for raw_path in file_paths:
            if not isinstance(raw_path, str):
                continue
            stripped = raw_path.strip()
            if not stripped or stripped in seen:
                continue
            seen.add(stripped)
            deduped.append(stripped)
            if len(deduped) >= max_files:
                return deduped, True
        return deduped, False

    def _read_files_sync(
        self,
        *,
        backend: BackendProtocol,
        file_paths: list[str],
        offset: int,
        limit: int,
    ) -> str:
        """Read multiple files and return a merged, sectioned response."""
        if not file_paths:
            return "Error: `file_paths` must include at least one absolute path."
        if offset < 0:
            return "Error: `offset` must be >= 0."
        if limit <= 0:
            return "Error: `limit` must be > 0."

        normalized_paths, was_truncated = self._normalize_batch_paths(file_paths)
        if not normalized_paths:
            return "Error: No valid file paths were provided."

        sections: list[str] = []
        for path in normalized_paths:
            try:
                validated_path = validate_path(path)
            except ValueError as exc:
                sections.append(f"=== {path} ===\nError: {exc}")
                continue

            content = backend.read(validated_path, offset=offset, limit=limit)
            sections.append(f"=== {validated_path} ===\n{content.rstrip()}")

        header = (
            f"Batch read {len(normalized_paths)} file(s) "
            f"(offset={offset}, limit={limit})."
        )
        if was_truncated:
            header += " Input was truncated to first 20 unique paths."
        return f"{header}\n\n" + "\n\n".join(sections)

    async def _read_files_async(
        self,
        *,
        backend: BackendProtocol,
        file_paths: list[str],
        offset: int,
        limit: int,
    ) -> str:
        """Async variant of batch file reads."""
        if not file_paths:
            return "Error: `file_paths` must include at least one absolute path."
        if offset < 0:
            return "Error: `offset` must be >= 0."
        if limit <= 0:
            return "Error: `limit` must be > 0."

        normalized_paths, was_truncated = self._normalize_batch_paths(file_paths)
        if not normalized_paths:
            return "Error: No valid file paths were provided."

        sections: list[str] = []
        for path in normalized_paths:
            try:
                validated_path = validate_path(path)
            except ValueError as exc:
                sections.append(f"=== {path} ===\nError: {exc}")
                continue

            content = await backend.aread(validated_path, offset=offset, limit=limit)
            sections.append(f"=== {validated_path} ===\n{content.rstrip()}")

        header = (
            f"Batch read {len(normalized_paths)} file(s) "
            f"(offset={offset}, limit={limit})."
        )
        if was_truncated:
            header += " Input was truncated to first 20 unique paths."
        return f"{header}\n\n" + "\n\n".join(sections)

    def _list_components_sync(
        self,
        *,
        backend: BackendProtocol,
        root_path: str,
        index_pattern: str,
    ) -> str:
        """List components by scanning index entry files under a root path."""
        try:
            validated_root = validate_path(root_path)
        except ValueError as exc:
            return f"Error: {exc}"

        infos = backend.glob_info(index_pattern, path=validated_root)
        entry_paths = sorted(
            {
                str(info.get("path", "")).strip()
                for info in infos
                if str(info.get("path", "")).strip()
            }
        )

        if not entry_paths:
            return (
                "No components found. "
                f"root_path={validated_root}, index_pattern={index_pattern}"
            )

        lines = [
            f"Found {len(entry_paths)} component(s) under {validated_root}:",
        ]
        for entry_path in entry_paths:
            component_name = Path(entry_path).parent.name
            lines.append(f"- {component_name}: {entry_path}")
        return "\n".join(lines)

    async def _list_components_async(
        self,
        *,
        backend: BackendProtocol,
        root_path: str,
        index_pattern: str,
    ) -> str:
        """Async variant of component inventory listing."""
        try:
            validated_root = validate_path(root_path)
        except ValueError as exc:
            return f"Error: {exc}"

        infos = await backend.aglob_info(index_pattern, path=validated_root)
        entry_paths = sorted(
            {
                str(info.get("path", "")).strip()
                for info in infos
                if str(info.get("path", "")).strip()
            }
        )

        if not entry_paths:
            return (
                "No components found. "
                f"root_path={validated_root}, index_pattern={index_pattern}"
            )

        lines = [
            f"Found {len(entry_paths)} component(s) under {validated_root}:",
        ]
        for entry_path in entry_paths:
            component_name = Path(entry_path).parent.name
            lines.append(f"- {component_name}: {entry_path}")
        return "\n".join(lines)

    def _read_file_sync(
        self,
        backend: BackendProtocol,
        file_path: str,
    ) -> tuple[str | None, str | None]:
        responses = backend.download_files([file_path])
        if not responses:
            return None, f"Error: Unable to read '{file_path}'."
        response = responses[0]
        if response.error is not None:
            if response.error == "file_not_found":
                return None, None
            return None, f"Error: Unable to read '{file_path}': {response.error}"
        if response.content is None:
            return None, f"Error: Empty file payload for '{file_path}'."
        return response.content.decode("utf-8", errors="replace"), None

    async def _read_file_async(
        self,
        backend: BackendProtocol,
        file_path: str,
    ) -> tuple[str | None, str | None]:
        responses = await backend.adownload_files([file_path])
        if not responses:
            return None, f"Error: Unable to read '{file_path}'."
        response = responses[0]
        if response.error is not None:
            if response.error == "file_not_found":
                return None, None
            return None, f"Error: Unable to read '{file_path}': {response.error}"
        if response.content is None:
            return None, f"Error: Empty file payload for '{file_path}'."
        return response.content.decode("utf-8", errors="replace"), None

    def _write_file_sync(
        self,
        backend: BackendProtocol,
        file_path: str,
        content: str,
    ) -> str | None:
        responses = backend.upload_files([(file_path, content.encode("utf-8"))])
        if not responses:
            return f"Error: Unable to write '{file_path}'."
        response = responses[0]
        if response.error is not None:
            return f"Error: Unable to write '{file_path}': {response.error}"
        return None

    async def _write_file_async(
        self,
        backend: BackendProtocol,
        file_path: str,
        content: str,
    ) -> str | None:
        responses = await backend.aupload_files([(file_path, content.encode("utf-8"))])
        if not responses:
            return f"Error: Unable to write '{file_path}'."
        response = responses[0]
        if response.error is not None:
            return f"Error: Unable to write '{file_path}': {response.error}"
        return None

    def _delete_file_sync(
        self,
        backend: BackendProtocol,
        file_path: str,
    ) -> str | None:
        if not isinstance(backend, SandboxBackendProtocol):
            return "Error: Delete File is not supported by this backend."
        result = backend.execute(f"rm -f -- {shlex.quote(file_path)}")
        if result.exit_code != 0:
            output = result.output.strip() or "unknown error"
            return f"Error: Unable to delete '{file_path}': {output}"
        return None

    async def _delete_file_async(
        self,
        backend: BackendProtocol,
        file_path: str,
    ) -> str | None:
        if not isinstance(backend, SandboxBackendProtocol):
            return "Error: Delete File is not supported by this backend."
        result = await backend.aexecute(f"rm -f -- {shlex.quote(file_path)}")
        if result.exit_code != 0:
            output = result.output.strip() or "unknown error"
            return f"Error: Unable to delete '{file_path}': {output}"
        return None


def _strip_fence(patch_content: str) -> str:
    text = patch_content.strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        if len(lines) >= 2:
            text = "\n".join(lines[1:-1]).strip()
    return text


def _build_file_patch(
    *,
    action: Literal["Add", "Update", "Delete"],
    path: str,
    body_lines: list[str],
    seen_paths: set[str],
) -> V4AFilePatch:
    if not path:
        raise ValueError("Encountered a file section with empty path.")
    if path in seen_paths:
        raise ValueError(
            f"File '{path}' appears multiple times. Merge all hunks into one section."
        )
    seen_paths.add(path)

    if action == "Delete":
        return V4AFilePatch(action="Delete", path=path)

    if action == "Add":
        add_lines = _parse_add_lines(path=path, body_lines=body_lines)
        return V4AFilePatch(action="Add", path=path, add_lines=add_lines)

    hunks = _parse_update_hunks(path=path, body_lines=body_lines)
    return V4AFilePatch(action="Update", path=path, hunks=hunks)


def _parse_add_lines(*, path: str, body_lines: list[str]) -> tuple[str, ...]:
    add_lines: list[str] = []
    for line in body_lines:
        if _HUNK_HEADER_RE.match(line.strip()):
            continue
        if line.startswith("-"):
            raise ValueError(
                f"Add File '{path}' cannot contain '-' lines. Use Update File instead."
            )
        if line.startswith("+"):
            add_lines.append(line[1:])
            continue
        add_lines.append(line)
    return tuple(add_lines)


def _parse_update_hunks(*, path: str, body_lines: list[str]) -> tuple[V4AHunk, ...]:
    hunks: list[V4AHunk] = []
    current_header: str | None = None
    current_lines: list[str] = []

    for line in body_lines:
        if _HUNK_HEADER_RE.match(line.strip()):
            if current_header is not None:
                hunks.append(
                    _parse_single_hunk(
                        path=path,
                        header=current_header,
                        lines=current_lines,
                    )
                )
            current_header = line.strip()
            current_lines = []
            continue

        if current_header is None:
            if line.strip():
                raise ValueError(
                    f"Update File '{path}' must use '@@ ...' headers before hunk lines."
                )
            continue
        current_lines.append(line)

    if current_header is None:
        raise ValueError(f"Update File '{path}' has no '@@' hunks.")

    hunks.append(
        _parse_single_hunk(path=path, header=current_header, lines=current_lines)
    )
    return tuple(hunks)


def _parse_single_hunk(*, path: str, header: str, lines: list[str]) -> V4AHunk:
    if not lines:
        raise ValueError(f"Update File '{path}' contains an empty hunk: {header}")

    context_before: list[str] = []
    old_lines: list[str] = []
    new_lines: list[str] = []
    context_after: list[str] = []
    seen_change = False

    for line in lines:
        if line == r"\ No newline at end of file":
            continue
        if line.startswith("-"):
            old_lines.append(line[1:])
            seen_change = True
            continue
        if line.startswith("+"):
            new_lines.append(line[1:])
            seen_change = True
            continue
        if seen_change:
            context_after.append(line)
        else:
            context_before.append(line)

    if not old_lines and not new_lines:
        raise ValueError(f"Update File '{path}' hunk has no '-' or '+' lines: {header}")
    if not old_lines and not (context_before or context_after):
        raise ValueError(
            f"Update File '{path}' insert-only hunk must include context lines: "
            f"{header}"
        )

    return V4AHunk(
        header=header,
        context_before=tuple(context_before),
        old_lines=tuple(old_lines),
        new_lines=tuple(new_lines),
        context_after=tuple(context_after),
    )


def _apply_single_hunk(
    content: str,
    *,
    file_path: str,
    hunk: V4AHunk,
    hunk_index: int,
) -> str:
    if not hunk.old_lines:
        return _apply_insert_only_hunk(
            content,
            file_path=file_path,
            hunk=hunk,
            hunk_index=hunk_index,
        )

    old_block = "\n".join(hunk.old_lines)
    new_block = "\n".join(hunk.new_lines)
    anchored_old = "\n".join(
        [*hunk.context_before, *hunk.old_lines, *hunk.context_after]
    )
    anchored_new = "\n".join(
        [*hunk.context_before, *hunk.new_lines, *hunk.context_after]
    )

    if anchored_old and anchored_old in content:
        return content.replace(anchored_old, anchored_new, 1)

    if old_block:
        matches = content.count(old_block)
        if matches == 1:
            return content.replace(old_block, new_block, 1)
        if matches > 1:
            raise ValueError(
                f"Patch hunk {hunk_index} for '{file_path}' is ambiguous. "
                "Add more context lines around '-' blocks."
            )

    raise ValueError(
        f"Patch hunk {hunk_index} for '{file_path}' did not match existing content."
    )


def _apply_insert_only_hunk(
    content: str,
    *,
    file_path: str,
    hunk: V4AHunk,
    hunk_index: int,
) -> str:
    if not hunk.new_lines:
        raise ValueError(
            f"Patch hunk {hunk_index} for '{file_path}' has no '+' lines to insert."
        )

    insertion = "\n".join(hunk.new_lines)
    has_before = bool(hunk.context_before)
    has_after = bool(hunk.context_after)

    if has_before and has_after:
        anchor_old = "\n".join([*hunk.context_before, *hunk.context_after])
        anchor_new = "\n".join(
            [*hunk.context_before, *hunk.new_lines, *hunk.context_after]
        )
    elif has_before:
        anchor_old = "\n".join(hunk.context_before)
        anchor_new = "\n".join([*hunk.context_before, insertion])
    elif has_after:
        anchor_old = "\n".join(hunk.context_after)
        anchor_new = "\n".join([insertion, *hunk.context_after])
    else:
        raise ValueError(
            f"Patch hunk {hunk_index} for '{file_path}' requires context for insert."
        )

    matches = content.count(anchor_old)
    if matches == 0:
        raise ValueError(
            f"Patch hunk {hunk_index} for '{file_path}' did not match existing content."
        )
    if matches > 1:
        raise ValueError(
            f"Patch hunk {hunk_index} for '{file_path}' is ambiguous. "
            "Add more context lines around '+' blocks."
        )
    return content.replace(anchor_old, anchor_new, 1)
