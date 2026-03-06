"""Filesystem middleware that enforces Patch-style apply_patch edits."""

from __future__ import annotations

import json
import re
import shlex
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, Any, Literal, cast

from deepagents.backends.protocol import (
    BACKEND_TYPES,
    BackendProtocol,
    SandboxBackendProtocol,
    execute_accepts_timeout,
)
from deepagents.middleware._utils import append_to_system_message
from deepagents.middleware.filesystem import FilesystemState
from langchain.agents.middleware.types import (
    AgentMiddleware,
    ContextT,
    ModelRequest,
    ModelResponse,
    ResponseT,
)
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.prebuilt.tool_node import ToolRuntime

try:
    from graphs.build_app_agent_v2.prompts import build_system_prompt
    from graphs.build_app_agent_v2.sandbox_policy_guard import (
        SandboxPolicyGuard,
        resolve_sandbox_patch_path,
    )
except ModuleNotFoundError:
    from prompts import build_system_prompt
    from sandbox_policy_guard import SandboxPolicyGuard, resolve_sandbox_patch_path

_FILE_HEADER_RE = re.compile(r"^\*\*\* (Add|Update|Delete) File:\s*(.+?)\s*$")
_HUNK_HEADER_RE = re.compile(r"^@@(?:\s+.*)?$")

APPLY_PATCH_TOOL_DESCRIPTION = """
Apply an `apply_patch` style patch payload to files.

You must pass one `patch_content` string using this format:
- `*** Update File: <path>`
- `*** Add File: <path>`
- `*** Delete File: <path>`
- For `Update File`, each change must be in its own `@@ ...` block.

Path rules aligned with BASE_SYSTEM_PROMPT:
- Use relative paths only (for example `src/app.py`).
- Relative paths are resolved from `/workspace`.

Each update hunk should include:
1. 1-3 lines of unchanged context before the change
2. zero or more `-` lines (old code)
3. one or more `+` lines (new code)
4. 1-3 lines of unchanged context after the change

Hard requirements:
- For the same file, merge all related hunks into a single `*** Update File` section.
- For insert-only hunks (no `-` lines), include `context_before` or `context_after`.
- Do not split one file's edits across multiple tool calls.
- `Add File` payload lines must start with `+`.
- `Update File` hunk lines must start with ` `, `-`, or `+`.
- Use unified patch syntax under `*** Begin Patch` / `*** End Patch`.
""".strip()

UPDATE_PLAN_TOOL_DESCRIPTION = """
Update the task plan shown to the user.

Provide:
- `plan`: ordered step items, each containing:
  - `step`: short action text
  - `status`: one of `pending`, `in_progress`, `completed`
- Optional `explanation`: concise reason when plan changes

Rules:
- Keep steps concise and actionable.
- At most one step can be `in_progress`.
- Mark all steps `completed` when done.
""".strip()


@dataclass(frozen=True, slots=True)
class PatchHunk:
    """A single Patch update hunk."""

    header: str
    context_before: tuple[str, ...]
    old_lines: tuple[str, ...]
    new_lines: tuple[str, ...]
    context_after: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FilePatch:
    """A Patch section scoped to one file."""

    action: Literal["Add", "Update", "Delete"]
    path: str
    move_to: str | None = None
    hunks: tuple[PatchHunk, ...] = ()
    add_lines: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PatchCommitAction:
    """A planned commit action produced by patch dry-run."""

    action: Literal["Add", "Update", "Delete"]
    path: str
    before_content: str | None = None
    after_content: str | None = None
    applied_hunks: int = 0


def parse_patch_content(patch_content: str) -> tuple[FilePatch, ...]:
    """Parse Patch content into structured file operations."""
    stripped = _strip_fence(patch_content)
    if not stripped:
        raise ValueError("Patch content is empty.")

    lines = _repair_missing_update_hunk_headers(stripped.splitlines())
    patches: list[FilePatch] = []
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


def _repair_missing_update_hunk_headers(lines: list[str]) -> list[str]:
    """Auto-repair simple Update File sections that omitted the first @@ header."""

    repaired: list[str] = []
    current_header: str | None = None
    current_action: Literal["Add", "Update", "Delete"] | None = None
    current_body: list[str] = []

    def flush_section() -> None:
        nonlocal current_header, current_action, current_body
        if current_header is None or current_action is None:
            return
        repaired.append(current_header)
        if current_action == "Update":
            repaired.extend(_repair_update_section_body(current_body))
        else:
            repaired.extend(current_body)
        current_header = None
        current_action = None
        current_body = []

    for raw_line in lines:
        line = raw_line.strip()
        if line in {"*** Begin Patch", "*** End Patch"}:
            flush_section()
            repaired.append(raw_line)
            continue

        header_match = _FILE_HEADER_RE.match(line)
        if header_match:
            flush_section()
            current_header = raw_line
            current_action = cast(
                'Literal["Add", "Update", "Delete"]',
                header_match.group(1),
            )
            current_body = []
            continue

        if current_header is None:
            repaired.append(raw_line)
            continue

        current_body.append(raw_line)

    flush_section()
    return repaired


def _repair_update_section_body(body_lines: list[str]) -> list[str]:
    """Insert a default @@ header when a simple Update block omitted one."""

    if any(_HUNK_HEADER_RE.match(line.strip()) for line in body_lines):
        return body_lines

    body_start = 0
    while body_start < len(body_lines):
        stripped = body_lines[body_start].strip()
        if not stripped:
            body_start += 1
            continue
        if stripped.startswith("*** Move to:"):
            body_start += 1
            continue
        break

    if body_start >= len(body_lines):
        return body_lines

    first_body_line = body_lines[body_start]
    if not first_body_line.startswith((" ", "-", "+")):
        return body_lines

    return [*body_lines[:body_start], "@@", *body_lines[body_start:]]


def _resolve_patch_path(raw_path: str) -> str:
    """Resolve patch path into an absolute sandbox path."""
    return resolve_sandbox_patch_path(raw_path)


def apply_update_patch(
    original_content: str,
    *,
    file_path: str,
    hunks: tuple[PatchHunk, ...],
) -> tuple[str, int]:
    """Apply parsed Patch update hunks to file content."""
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


class PatchFilesystemMiddleware(AgentMiddleware[FilesystemState, ContextT, ResponseT]):
    """Filesystem middleware that replaces `edit_file` with `apply_patch`."""

    state_schema = FilesystemState

    def __init__(
        self,
        *,
        backend: BACKEND_TYPES | None = None,
        system_prompt: str | None = None,
        custom_tool_descriptions: dict[str, str] | None = None,
        tool_token_limit_before_evict: int | None = 20_000,
        max_execute_timeout: int = 3_600,
        include_legacy_read_write_tools: bool = False,
    ) -> None:
        _ = tool_token_limit_before_evict
        _ = include_legacy_read_write_tools
        if max_execute_timeout <= 0:
            raise ValueError("max_execute_timeout must be positive")
        self.backend = backend if backend is not None else cast("BACKEND_TYPES", None)
        self._custom_tool_descriptions = custom_tool_descriptions or {}
        self._custom_system_prompt = (
            build_system_prompt() if system_prompt is None else system_prompt
        )
        self._max_execute_timeout = max_execute_timeout
        self._sandbox_policy_guard = SandboxPolicyGuard()
        self.tools = [self._create_execute_tool()]
        self.tools.append(self._create_update_plan_tool())
        self.tools.append(self._create_apply_patch_tool())

    def _get_backend(self, runtime: ToolRuntime[Any, Any]) -> BackendProtocol:
        if self.backend is None:
            raise RuntimeError("Filesystem backend is not configured.")
        if callable(self.backend):
            return self.backend(runtime)
        return self.backend

    def wrap_model_call(
        self,
        request: ModelRequest[ContextT],
        handler: Callable[[ModelRequest[ContextT]], ModelResponse[ResponseT]],
    ) -> ModelResponse[ResponseT]:
        prompt = self._custom_system_prompt
        if prompt:
            new_system_message = append_to_system_message(
                request.system_message, prompt
            )
            request = request.override(system_message=new_system_message)
        return handler(request)

    async def awrap_model_call(
        self,
        request: ModelRequest[ContextT],
        handler: Callable[
            [ModelRequest[ContextT]], Awaitable[ModelResponse[ResponseT]]
        ],
    ) -> ModelResponse[ResponseT]:
        prompt = self._custom_system_prompt
        if prompt:
            new_system_message = append_to_system_message(
                request.system_message, prompt
            )
            request = request.override(system_message=new_system_message)
        return await handler(request)

    def _create_execute_tool(self) -> BaseTool:
        description = self._custom_tool_descriptions.get("execute")
        if description is None:
            description = (
                "Execute shell commands in sandbox. "
                "Prefer `rg` / `rg --files` for search. "
                "Avoid Python one-liners for large file reads. "
                "For multi-command execution, chain with ';' or '&&' in one line."
            )

        def sync_execute(
            command: Annotated[str, "Shell command to execute in sandbox."],
            runtime: ToolRuntime[None, FilesystemState],
            timeout: Annotated[int | None, "Optional timeout seconds."] = None,
        ) -> str:
            violation = self._validate_execute_command(command)
            if violation is not None:
                return f"Error: {violation}"
            backend = self._get_backend(runtime)
            if not isinstance(backend, SandboxBackendProtocol):
                return "Error: execute is not supported by this backend."
            if timeout is not None:
                if timeout <= 0:
                    return "Error: timeout must be a positive integer."
                if timeout > self._max_execute_timeout:
                    return (
                        "Error: timeout exceeds max_execute_timeout "
                        f"({self._max_execute_timeout}s)."
                    )
                if execute_accepts_timeout(type(backend)):
                    result = backend.execute(command, timeout=timeout)
                else:
                    result = backend.execute(command)
            else:
                result = backend.execute(command)
            return (
                f"Exit code: {result.exit_code}\n"
                f"Truncated: {result.truncated}\n"
                f"Output:\n{result.output}"
            )

        async def async_execute(
            command: Annotated[str, "Shell command to execute in sandbox."],
            runtime: ToolRuntime[None, FilesystemState],
            timeout: Annotated[int | None, "Optional timeout seconds."] = None,
        ) -> str:
            violation = self._validate_execute_command(command)
            if violation is not None:
                return f"Error: {violation}"
            backend = self._get_backend(runtime)
            if not isinstance(backend, SandboxBackendProtocol):
                return "Error: execute is not supported by this backend."
            if timeout is not None:
                if timeout <= 0:
                    return "Error: timeout must be a positive integer."
                if timeout > self._max_execute_timeout:
                    return (
                        "Error: timeout exceeds max_execute_timeout "
                        f"({self._max_execute_timeout}s)."
                    )
                if execute_accepts_timeout(type(backend)):
                    result = await backend.aexecute(command, timeout=timeout)
                else:
                    result = await backend.aexecute(command)
            else:
                result = await backend.aexecute(command)
            return (
                f"Exit code: {result.exit_code}\n"
                f"Truncated: {result.truncated}\n"
                f"Output:\n{result.output}"
            )

        return StructuredTool.from_function(
            name="execute",
            description=description,
            func=sync_execute,
            coroutine=async_execute,
        )

    def _validate_execute_command(self, command: str) -> str | None:
        return self._sandbox_policy_guard.validate_execute_command(command)

    def _create_apply_patch_tool(self) -> BaseTool:
        description = self._custom_tool_descriptions.get("apply_patch")
        if description is None:
            description = APPLY_PATCH_TOOL_DESCRIPTION

        def sync_apply_patch(
            patch_content: Annotated[
                str,
                (
                    "Full Patch content. Must contain one or more "
                    "`*** Add/Update/Delete File: <path>` sections. "
                    "Paths must be relative and are resolved from `/workspace`."
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
                    "Full Patch content. Must contain one or more "
                    "`*** Add/Update/Delete File: <path>` sections. "
                    "Paths must be relative and are resolved from `/workspace`."
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

    def _normalize_plan_items(
        self,
        plan: list[dict[str, Any]],
    ) -> tuple[list[dict[str, str]], str | None]:
        allowed_status = {"pending", "in_progress", "completed"}
        normalized: list[dict[str, str]] = []
        in_progress_count = 0

        for index, item in enumerate(plan, start=1):
            if not isinstance(item, dict):
                return [], f"plan[{index}] must be an object."
            step = item.get("step")
            status = item.get("status")
            if not isinstance(step, str) or not step.strip():
                return [], f"plan[{index}].step must be a non-empty string."
            if not isinstance(status, str) or status not in allowed_status:
                return (
                    [],
                    f"plan[{index}].status must be one of pending/in_progress/completed.",
                )
            if status == "in_progress":
                in_progress_count += 1
            normalized.append({"step": step.strip(), "status": status})

        if in_progress_count > 1:
            return [], "At most one plan step can be in_progress."

        return normalized, None

    def _create_update_plan_tool(self) -> BaseTool:
        description = self._custom_tool_descriptions.get("update_plan")
        if description is None:
            description = UPDATE_PLAN_TOOL_DESCRIPTION

        def sync_update_plan(
            plan: Annotated[
                list[dict[str, Any]],
                "Ordered plan items with `step` and `status`.",
            ],
            runtime: ToolRuntime[None, FilesystemState],
            explanation: Annotated[
                str | None,
                "Optional explanation for plan update.",
            ] = None,
        ) -> str:
            if not plan:
                return self._error_result(
                    error_code="PLAN_VALIDATION_ERROR",
                    message="plan must contain at least one step.",
                    retryable=True,
                )

            normalized_plan, error = self._normalize_plan_items(plan)
            if error is not None:
                return self._error_result(
                    error_code="PLAN_VALIDATION_ERROR",
                    message=error,
                    retryable=True,
                )

            raw_state = runtime.state if isinstance(runtime.state, dict) else None
            if raw_state is not None:
                state = cast("dict[str, Any]", raw_state)
                state["update_plan"] = normalized_plan
                state["update_plan_explanation"] = (
                    explanation.strip() if isinstance(explanation, str) else None
                )

            completed = sum(
                1 for item in normalized_plan if item["status"] == "completed"
            )
            active_step = next(
                (
                    item["step"]
                    for item in normalized_plan
                    if item["status"] == "in_progress"
                ),
                None,
            )
            return self._ok_result(
                message="Plan updated.",
                details={
                    "steps_total": len(normalized_plan),
                    "steps_completed": completed,
                    "active_step": active_step,
                    "plan": normalized_plan,
                },
            )

        async def async_update_plan(
            plan: Annotated[
                list[dict[str, Any]],
                "Ordered plan items with `step` and `status`.",
            ],
            runtime: ToolRuntime[None, FilesystemState],
            explanation: Annotated[
                str | None,
                "Optional explanation for plan update.",
            ] = None,
        ) -> str:
            return sync_update_plan(
                plan=plan,
                runtime=runtime,
                explanation=explanation,
            )

        return StructuredTool.from_function(
            name="update_plan",
            description=description,
            func=sync_update_plan,
            coroutine=async_update_plan,
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
            file_patches = parse_patch_content(patch_content)
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
                path = _resolve_patch_path(file_patch.path)
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
                updated_content, applied = apply_update_patch(
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

            if updated_content == current_content and file_patch.move_to is None:
                continue

            if file_patch.move_to is not None:
                try:
                    move_target = _resolve_patch_path(file_patch.move_to)
                except ValueError as exc:
                    return self._error_result(
                        error_code="PATCH_PARSE_ERROR",
                        message=str(exc),
                        details={
                            "path": path,
                            "move_to": file_patch.move_to,
                            "action": "Update",
                        },
                        retryable=True,
                    )

                target_current, target_read_error = self._read_file_sync(
                    backend, move_target
                )
                if target_read_error is not None:
                    return self._error_result(
                        error_code="RESOURCE_READ_ERROR",
                        message=target_read_error,
                        details={"path": move_target},
                        retryable=True,
                    )
                if target_current is not None:
                    return self._error_result(
                        error_code="PATCH_PRECONDITION_FAILED",
                        message=f"Move target '{move_target}' already exists.",
                        details={
                            "path": path,
                            "move_to": move_target,
                            "action": "Update",
                        },
                        retryable=False,
                    )
                commit_actions.append(
                    PatchCommitAction(
                        action="Add",
                        path=move_target,
                        before_content=None,
                        after_content=updated_content,
                        applied_hunks=applied,
                    )
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
                changed_files += 2
            else:
                commit_actions.append(
                    PatchCommitAction(
                        action="Update",
                        path=path,
                        before_content=current_content,
                        after_content=updated_content,
                        applied_hunks=applied,
                    )
                )
                changed_files += 1
            updated_hunks += applied

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
            file_patches = parse_patch_content(patch_content)
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
                path = _resolve_patch_path(file_patch.path)
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
                updated_content, applied = apply_update_patch(
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

            if updated_content == current_content and file_patch.move_to is None:
                continue

            if file_patch.move_to is not None:
                try:
                    move_target = _resolve_patch_path(file_patch.move_to)
                except ValueError as exc:
                    return self._error_result(
                        error_code="PATCH_PARSE_ERROR",
                        message=str(exc),
                        details={
                            "path": path,
                            "move_to": file_patch.move_to,
                            "action": "Update",
                        },
                        retryable=True,
                    )

                target_current, target_read_error = await self._read_file_async(
                    backend, move_target
                )
                if target_read_error is not None:
                    return self._error_result(
                        error_code="RESOURCE_READ_ERROR",
                        message=target_read_error,
                        details={"path": move_target},
                        retryable=True,
                    )
                if target_current is not None:
                    return self._error_result(
                        error_code="PATCH_PRECONDITION_FAILED",
                        message=f"Move target '{move_target}' already exists.",
                        details={
                            "path": path,
                            "move_to": move_target,
                            "action": "Update",
                        },
                        retryable=False,
                    )
                commit_actions.append(
                    PatchCommitAction(
                        action="Add",
                        path=move_target,
                        before_content=None,
                        after_content=updated_content,
                        applied_hunks=applied,
                    )
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
                changed_files += 2
            else:
                commit_actions.append(
                    PatchCommitAction(
                        action="Update",
                        path=path,
                        before_content=current_content,
                        after_content=updated_content,
                        applied_hunks=applied,
                    )
                )
                changed_files += 1
            updated_hunks += applied

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
        execute_fn = None
        if isinstance(backend, SandboxBackendProtocol):
            execute_fn = backend.execute
        else:
            candidate = getattr(backend, "execute", None)
            if callable(candidate):
                execute_fn = candidate
        if execute_fn is None:
            return "Error: Delete File is not supported by this backend."

        result = execute_fn(f"rm -f -- {shlex.quote(file_path)}")
        exit_code = getattr(result, "exit_code", None)
        output = getattr(result, "output", "")
        if not isinstance(exit_code, int):
            return (
                "Error: Delete File execution returned an invalid response "
                "(missing integer exit_code)."
            )
        if not isinstance(output, str):
            output = str(output)
        if exit_code != 0:
            output = output.strip() or "unknown error"
            return f"Error: Unable to delete '{file_path}': {output}"
        return None

    async def _delete_file_async(
        self,
        backend: BackendProtocol,
        file_path: str,
    ) -> str | None:
        async_execute_fn: Callable[[str], Awaitable[Any]] | None = None
        if isinstance(backend, SandboxBackendProtocol):
            async_execute_fn = cast("Callable[[str], Awaitable[Any]]", backend.aexecute)
        else:
            candidate = getattr(backend, "aexecute", None)
            if callable(candidate):
                async_execute_fn = cast("Callable[[str], Awaitable[Any]]", candidate)
        if async_execute_fn is None:
            return "Error: Delete File is not supported by this backend."

        result = await async_execute_fn(f"rm -f -- {shlex.quote(file_path)}")
        exit_code = getattr(result, "exit_code", None)
        output = getattr(result, "output", "")
        if not isinstance(exit_code, int):
            return (
                "Error: Delete File execution returned an invalid response "
                "(missing integer exit_code)."
            )
        if not isinstance(output, str):
            output = str(output)
        if exit_code != 0:
            output = output.strip() or "unknown error"
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
) -> FilePatch:
    if not path:
        raise ValueError("Encountered a file section with empty path.")
    if path in seen_paths:
        raise ValueError(
            f"File '{path}' appears multiple times. Merge all hunks into one section."
        )
    seen_paths.add(path)

    if action == "Delete":
        for line in body_lines:
            if line.strip():
                raise ValueError(f"Delete File '{path}' must not contain body lines.")
        return FilePatch(action="Delete", path=path)

    if action == "Add":
        add_lines = _parse_add_lines(path=path, body_lines=body_lines)
        return FilePatch(action="Add", path=path, add_lines=add_lines)

    move_to, update_body_lines = _extract_move_to(path=path, body_lines=body_lines)
    hunks = _parse_update_hunks(path=path, body_lines=update_body_lines)
    return FilePatch(action="Update", path=path, move_to=move_to, hunks=hunks)


def _extract_move_to(
    *,
    path: str,
    body_lines: list[str],
) -> tuple[str | None, list[str]]:
    move_to: str | None = None
    remaining: list[str] = []
    first_content_seen = False

    for line in body_lines:
        stripped = line.strip()
        if not first_content_seen and not stripped:
            continue

        if stripped.startswith("*** Move to:"):
            if move_to is not None:
                raise ValueError(
                    f"Update File '{path}' contains multiple '*** Move to:' lines."
                )
            if first_content_seen:
                raise ValueError(
                    f"Update File '{path}' must place '*** Move to:' before hunks."
                )
            move_to = stripped[len("*** Move to:") :].strip()
            if not move_to:
                raise ValueError(
                    f"Update File '{path}' has empty move target in '*** Move to:'."
                )
            continue

        first_content_seen = True
        remaining.append(line)

    return move_to, remaining


def _parse_add_lines(*, path: str, body_lines: list[str]) -> tuple[str, ...]:
    add_lines: list[str] = []
    for line in body_lines:
        if not line.strip():
            raise ValueError(
                f"Add File '{path}' lines must start with '+'; found empty line."
            )
        if line.startswith("-"):
            raise ValueError(
                f"Add File '{path}' cannot contain '-' lines. Use Update File instead."
            )
        if line.startswith("+"):
            add_lines.append(line[1:])
            continue
        raise ValueError(f"Add File '{path}' lines must start with '+': {line!r}")
    return tuple(add_lines)


def _parse_update_hunks(*, path: str, body_lines: list[str]) -> tuple[PatchHunk, ...]:
    hunks: list[PatchHunk] = []
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


def _parse_single_hunk(*, path: str, header: str, lines: list[str]) -> PatchHunk:
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
        if line.startswith(" "):
            context_line = line[1:]
            if seen_change:
                context_after.append(context_line)
            else:
                context_before.append(context_line)
            continue
        raise ValueError(
            f"Update File '{path}' has invalid hunk line prefix: {line!r}. "
            "Hunk lines must start with ' ', '-', or '+'."
        )

    if not old_lines and not new_lines:
        raise ValueError(f"Update File '{path}' hunk has no '-' or '+' lines: {header}")
    if not old_lines and not (context_before or context_after):
        raise ValueError(
            f"Update File '{path}' insert-only hunk must include context lines: "
            f"{header}"
        )

    return PatchHunk(
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
    hunk: PatchHunk,
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
    hunk: PatchHunk,
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
