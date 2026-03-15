"""Filesystem middleware that enforces Patch-style apply_patch edits."""

from __future__ import annotations

import json
import re
import shlex
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from hashlib import sha256
from typing import Annotated, Any, Literal, NotRequired, cast

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
    from graphs.build_app_agent_v3.sandbox_policy_guard import (
        SandboxPolicyGuard,
        resolve_sandbox_patch_path,
    )
except ModuleNotFoundError:
    from sandbox_policy_guard import SandboxPolicyGuard, resolve_sandbox_patch_path


# ===== Constants and tool descriptions =====
_FILE_HEADER_RE = re.compile(r"^\*\*\* (Add|Update|Delete) File:\s*(.+?)\s*$")

APPLY_PATCH_TOOL_DESCRIPTION = """
Apply a patch payload to files using Search/Replace blocks.

You must pass one `patch_content` string using this format:
- `*** Update File: <path>`
- `*** Add File: <path>`
- `*** Delete File: <path>`

For `Add File`:
- Provide the exact full file content directly below the header. NO prefixes needed!

For `Update File`:
- Use XML search/replace blocks:
<search>
[exact old code to find]
</search>
<replace>
[new code to replace it with]
</replace>

Hard requirements:
- `SEARCH` block MUST exactly match the existing file content, including indentation and empty lines.
- Include enough surrounding unique context lines in the `SEARCH` block so it matches EXACTLY ONE location in the file.
- `Update File` is an exact replacement operation, not a best-effort edit. If the current file does not exactly match `SEARCH`, you must stop, re-read the file, and generate a smaller, more precise patch.
- Never use one huge file-wide `SEARCH` / `REPLACE` block for a large file. Split large edits into multiple local replacements so each patch stays complete and unambiguous.
- If a previous patch failed with parse errors such as missing `</search>` or `</replace>`, regenerate a smaller complete patch from scratch. Never try to append the missing tail onto the old failed payload.
- If the same file already hit `PATCH_PARSE_ERROR`, your next retry for that file MUST reduce scope to a smaller local block. Do not resend another large whole-file or near-whole-file replacement.
- For SCSS/CSS/Vue style files, treat broad top-to-bottom style rewrites as invalid. Patch one selector block or one local region at a time.
- Do not output any line number prefixes or `+`/`-` signs. Just write the raw code.
- `</search>` and `</replace>` MUST each be on their own line.
- Never put code and XML close tags on the same line (for example: `}</replace>` is invalid).
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


# ===== Patch data models =====
@dataclass(frozen=True, slots=True)
class PatchHunk:
    """A single Search/Replace block."""

    search_text: str
    replace_text: str


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


@dataclass(frozen=True, slots=True)
class TextFormat:
    """Original text formatting preserved across normalized patch application."""

    newline: str
    has_trailing_newline: bool


_UNIFIED_DIFF_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_UNIFIED_DIFF_MARKER_RE = re.compile(r"(?m)^(?:@@\s+-\d|---\s|\+\+\+\s)")
_MAX_FILE_DIFFS = 20
_MAX_HUNKS_PER_FILE = 20
_APPLY_PATCH_STATS_STATE_KEY = "apply_patch_stats_v1"
_MAX_TRACKED_FILE_CHARS = 200_000


class PatchFilesystemState(FilesystemState):
    """Filesystem state plus apply_patch session diff tracking."""

    apply_patch_stats_v1: NotRequired[dict[str, Any]]


# ===== Parse/apply primitives =====
# Patch parser and applier core:
# parse_patch_content -> FilePatch -> apply_update_patch/_apply_single_hunk
def parse_patch_content(patch_content: str) -> tuple[FilePatch, ...]:
    """Parse Patch content into structured file operations."""
    stripped = _strip_fence(patch_content)
    if not stripped:
        raise ValueError("Patch content is empty.")
    if _looks_like_unified_diff(stripped):
        raise ValueError(
            "PATCH_WRONG_FORMAT: Detected unified diff markers (`@@`/`---`/`+++`). "
            "This tool only accepts XML Search/Replace blocks. "
            "Use `*** Update File: <path>` with `<search>...</search>` and `<replace>...</replace>`."
        )

    lines = stripped.splitlines()
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
                'Literal["Add", "Update", "Delete"]', header_match.group(1)
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


def _resolve_patch_path(raw_path: str) -> str:
    """Resolve patch path into an absolute sandbox path (best-effort tolerant)."""
    candidate = raw_path.strip()
    if candidate.startswith("/workspace/"):
        candidate = candidate.removeprefix("/workspace/")
    elif candidate == "/workspace":
        candidate = "."
    return resolve_sandbox_patch_path(candidate or raw_path)


def apply_update_patch(
    original_content: str,
    *,
    file_path: str,
    hunks: tuple[PatchHunk, ...],
) -> tuple[str, int]:
    """Apply parsed Patch update hunks to file content."""
    normalized_content, text_format = _normalize_text_for_patch(original_content)
    updated_content = normalized_content
    applied_count = 0

    for index, hunk in enumerate(hunks, start=1):
        updated_content = _apply_single_hunk(
            updated_content,
            file_path=file_path,
            hunk=hunk,
            hunk_index=index,
        )
        applied_count += 1

    return _restore_text_format(updated_content, text_format=text_format), applied_count


def _compute_diff_hunks(before: str, after: str) -> list[dict[str, int]]:
    """Compute unified-diff hunk ranges with absolute line numbers."""
    import difflib

    old_lines = before.splitlines()
    new_lines = after.splitlines()
    hunks: list[dict[str, int]] = []

    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile="before",
        tofile="after",
        n=0,
        lineterm="",
    )
    for line in diff:
        if not line.startswith("@@ "):
            continue
        match = _UNIFIED_DIFF_HUNK_RE.match(line)
        if not match:
            continue
        hunks.append(
            {
                "old_start": int(match.group(1)),
                "old_count": int(match.group(2) or "1"),
                "new_start": int(match.group(3)),
                "new_count": int(match.group(4) or "1"),
            }
        )

    return hunks


def _compute_line_change_counts(before: str, after: str) -> tuple[int, int]:
    """Count minimal added/removed lines so summary stats match rendered diffs."""
    old_lines = before.splitlines()
    new_lines = after.splitlines()

    if not old_lines and not new_lines:
        return 0, 0
    if not old_lines:
        return len(new_lines), 0
    if not new_lines:
        return 0, len(old_lines)

    # Myers computes the shortest edit script exactly without the O(n*m) DP blowup.
    frontier: dict[int, int] = {1: 0}
    old_len = len(old_lines)
    new_len = len(new_lines)

    for distance in range(old_len + new_len + 1):
        for diagonal in range(-distance, distance + 1, 2):
            if diagonal == -distance or (
                diagonal != distance
                and frontier.get(diagonal - 1, -1) < frontier.get(diagonal + 1, -1)
            ):
                old_index = frontier.get(diagonal + 1, 0)
            else:
                old_index = frontier.get(diagonal - 1, 0) + 1

            new_index = old_index - diagonal
            while (
                old_index < old_len
                and new_index < new_len
                and old_lines[old_index] == new_lines[new_index]
            ):
                old_index += 1
                new_index += 1

            frontier[diagonal] = old_index
            if old_index >= old_len and new_index >= new_len:
                delta = new_len - old_len
                added = (distance + delta) // 2
                removed = distance - added
                return added, removed

    raise RuntimeError("Unable to compute shortest edit script for apply_patch stats.")


def _normalize_text_for_patch(content: str) -> tuple[str, TextFormat]:
    """Normalize file text to LF for matching while retaining original formatting."""
    newline = _detect_dominant_newline(content)
    has_trailing_newline = content.endswith(("\n", "\r"))
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    return normalized, TextFormat(
        newline=newline,
        has_trailing_newline=has_trailing_newline,
    )


def _restore_text_format(content: str, *, text_format: TextFormat) -> str:
    """Restore original newline style and final newline preference."""
    restored = content
    if text_format.has_trailing_newline:
        if restored and not restored.endswith("\n"):
            restored += "\n"
    elif restored.endswith("\n"):
        restored = restored[:-1]

    if text_format.newline != "\n":
        restored = restored.replace("\n", text_format.newline)
    return restored


def _detect_dominant_newline(content: str) -> str:
    """Detect a consistent newline style or fail fast on mixed text files."""
    has_crlf = "\r\n" in content
    normalized_without_crlf = content.replace("\r\n", "")
    has_bare_cr = "\r" in normalized_without_crlf
    has_bare_lf = "\n" in normalized_without_crlf

    newline_kinds = int(has_crlf) + int(has_bare_cr) + int(has_bare_lf)
    if newline_kinds > 1:
        raise ValueError(
            "PATCH_FORMAT_ERROR: File uses mixed line endings. "
            "Normalize the file first, then retry apply_patch."
        )
    if has_crlf:
        return "\r\n"
    if has_bare_cr:
        return "\r"
    return "\n"


# ===== Middleware and tool wiring =====
class PatchFilesystemMiddleware(
    AgentMiddleware[PatchFilesystemState, ContextT, ResponseT]
):
    """Filesystem middleware that replaces `edit_file` with `apply_patch`."""

    state_schema = PatchFilesystemState

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
        self._custom_system_prompt = system_prompt
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
                "For independent read-only discovery, batch related checks into one call. "
                "For multi-command execution, chain with ';' or '&&' in one line."
            )

        def sync_execute(
            command: Annotated[str, "Shell command to execute in sandbox."],
            runtime: ToolRuntime[None, PatchFilesystemState],
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
            runtime: ToolRuntime[None, PatchFilesystemState],
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
            runtime: ToolRuntime[None, PatchFilesystemState],
            dry_run: Annotated[
                bool,
                "Validate patch match/applicability only; do not write files.",
            ] = False,
        ) -> tuple[str, dict[str, Any]]:
            backend = self._get_backend(runtime)
            try:
                content = self._apply_patch_sync(
                    backend,
                    patch_content,
                    dry_run=dry_run,
                    runtime_state=(
                        runtime.state if isinstance(runtime.state, dict) else None
                    ),
                )
                return self._split_tool_payload_for_frontend(content)
            except Exception as exc:
                content = self._error_result(
                    error_code="PATCH_INTERNAL_ERROR",
                    message="Patch execution failed due to internal error.",
                    details={
                        "phase": "recover",
                        "changed_files": 0,
                        "hunks_applied": 0,
                        "fallbacks": [f"sync_apply_patch_exception: {exc!r}"],
                        "actions": {"add": 0, "update": 0, "delete": 0},
                        "file_diffs": [],
                    },
                    retryable=True,
                )
                return self._split_tool_payload_for_frontend(content)

        async def async_apply_patch(
            patch_content: Annotated[
                str,
                (
                    "Full Patch content. Must contain one or more "
                    "`*** Add/Update/Delete File: <path>` sections. "
                    "Paths must be relative and are resolved from `/workspace`."
                ),
            ],
            runtime: ToolRuntime[None, PatchFilesystemState],
            dry_run: Annotated[
                bool,
                "Validate patch match/applicability only; do not write files.",
            ] = False,
        ) -> tuple[str, dict[str, Any]]:
            backend = self._get_backend(runtime)
            try:
                content = await self._apply_patch_async(
                    backend,
                    patch_content,
                    dry_run=dry_run,
                    runtime_state=(
                        runtime.state if isinstance(runtime.state, dict) else None
                    ),
                )
                return self._split_tool_payload_for_frontend(content)
            except Exception as exc:
                content = self._error_result(
                    error_code="PATCH_INTERNAL_ERROR",
                    message="Patch execution failed due to internal error.",
                    details={
                        "phase": "recover",
                        "changed_files": 0,
                        "hunks_applied": 0,
                        "fallbacks": [f"async_apply_patch_exception: {exc!r}"],
                        "actions": {"add": 0, "update": 0, "delete": 0},
                        "file_diffs": [],
                    },
                    retryable=True,
                )
                return self._split_tool_payload_for_frontend(content)

        return StructuredTool.from_function(
            name="apply_patch",
            description=description,
            func=sync_apply_patch,
            coroutine=async_apply_patch,
            response_format="content_and_artifact",
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
            runtime: ToolRuntime[None, PatchFilesystemState],
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
            runtime: ToolRuntime[None, PatchFilesystemState],
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

    def _split_tool_payload_for_frontend(
        self, content: str
    ) -> tuple[str, dict[str, Any]]:
        """Mirror diff data into artifact while preserving payload compatibility."""
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            return content, {}
        if not isinstance(payload, dict):
            return content, {}

        details = payload.get("details")
        if not isinstance(details, dict):
            return content, {}

        raw_file_diffs = details.get("file_diffs")
        if not isinstance(raw_file_diffs, list):
            payload["details"] = details
            return json.dumps(payload, ensure_ascii=False), {}

        details["file_diff_count"] = len(raw_file_diffs)
        details["file_diffs_omitted"] = False
        payload["details"] = details
        artifact: dict[str, Any] = {"tool_file_diffs": raw_file_diffs}
        if "file_diffs_truncated" in details:
            artifact["file_diffs_truncated"] = details["file_diffs_truncated"]
        return json.dumps(payload, ensure_ascii=False), artifact

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

    def _strict_patch_error(
        self,
        *,
        error_code: str,
        message: str,
        phase: str,
        matched_files: int = 0,
        changed_files: int = 0,
        hunks_applied: int = 0,
        actions: dict[str, int] | None = None,
        fallbacks: list[str] | None = None,
        retryable: bool = True,
    ) -> str:
        return self._error_result(
            error_code=error_code,
            message=message,
            details={
                "phase": phase,
                "matched_files": matched_files,
                "changed_files": changed_files,
                "hunks_applied": hunks_applied,
                "fallbacks": fallbacks or [],
                "actions": actions or {"add": 0, "update": 0, "delete": 0},
                "file_diffs": [],
            },
            retryable=retryable,
        )

    def _build_file_diff_result(
        self,
        *,
        action: PatchCommitAction,
    ) -> dict[str, Any] | None:
        """Build structured diff metadata returned by apply_patch itself."""
        before_text = action.before_content or ""
        after_text = action.after_content or ""
        if before_text == after_text:
            return None

        hunks = _compute_diff_hunks(before_text, after_text)
        truncated_hunks = hunks[:_MAX_HUNKS_PER_FILE]
        delta_added, delta_removed = _compute_line_change_counts(
            before_text, after_text
        )
        return {
            "action": action.action,
            "file_path": action.path.removeprefix("/workspace/"),
            "before_line_count": len(before_text.splitlines()),
            "after_line_count": len(after_text.splitlines()),
            "before_content_sha256": sha256(before_text.encode("utf-8")).hexdigest(),
            "after_content_sha256": sha256(after_text.encode("utf-8")).hexdigest(),
            "delta_added": delta_added,
            "delta_removed": delta_removed,
            "hunks": truncated_hunks,
            "hunks_truncated": len(hunks) > len(truncated_hunks),
        }

    def _enrich_file_diff_with_session_stats(
        self,
        *,
        file_diff: dict[str, Any],
        action: PatchCommitAction,
        runtime_state: PatchFilesystemState | None,
        persist_state: bool,
    ) -> dict[str, Any]:
        if runtime_state is None:
            file_diff["file_version"] = 1
            file_diff["net_added"] = file_diff.get("delta_added", 0)
            file_diff["net_removed"] = file_diff.get("delta_removed", 0)
            file_diff["net_partial"] = True
            return file_diff

        tracker_root = runtime_state.get(_APPLY_PATCH_STATS_STATE_KEY)
        if not isinstance(tracker_root, dict):
            tracker_root = {}
        tracker_files = tracker_root.get("files")
        if not isinstance(tracker_files, dict):
            tracker_files = {}

        file_key = action.path.removeprefix("/workspace/")
        before_text = action.before_content or ""
        after_text = action.after_content or ""

        entry_obj = tracker_files.get(file_key)
        entry = entry_obj if isinstance(entry_obj, dict) else {}
        baseline_text = entry.get("baseline_text")
        current_text = entry.get("current_text")
        if not isinstance(baseline_text, str):
            baseline_text = before_text if action.action != "Add" else ""
        if not isinstance(current_text, str):
            current_text = before_text if action.action != "Add" else ""

        version = entry.get("version")
        if not isinstance(version, int) or version < 0:
            version = 0
        partial = bool(entry.get("partial"))

        if persist_state:
            current_text = after_text
            version += 1

        if (
            len(baseline_text) > _MAX_TRACKED_FILE_CHARS
            or len(current_text) > _MAX_TRACKED_FILE_CHARS
        ):
            partial = True

        net_added = file_diff.get("delta_added", 0)
        net_removed = file_diff.get("delta_removed", 0)
        if not partial:
            net_added, net_removed = _compute_line_change_counts(
                baseline_text, current_text
            )

        file_diff["file_version"] = version if version > 0 else 1
        file_diff["net_added"] = net_added
        file_diff["net_removed"] = net_removed
        file_diff["net_partial"] = partial

        if persist_state:
            if partial:
                tracker_files[file_key] = {
                    "baseline_text": "",
                    "current_text": "",
                    "version": version,
                    "partial": True,
                }
            else:
                tracker_files[file_key] = {
                    "baseline_text": baseline_text,
                    "current_text": current_text,
                    "version": version,
                    "partial": False,
                }
            tracker_root["files"] = tracker_files
            runtime_state[_APPLY_PATCH_STATS_STATE_KEY] = tracker_root

        return file_diff

    def _summarize_action_counts(
        self,
        actions: list[PatchCommitAction],
    ) -> dict[str, int]:
        summary = {"Add": 0, "Update": 0, "Delete": 0}
        for action in actions:
            if action.action in summary:
                summary[action.action] += 1
        return summary

    # ===== Patch execution: sync =====
    def _apply_patch_sync(
        self,
        backend: BackendProtocol,
        patch_content: str,
        *,
        dry_run: bool = False,
        runtime_state: PatchFilesystemState | None = None,
    ) -> str:
        # Main flow:
        # 1) parse patch sections
        # 2) read current files and compute commit actions
        # 3) optionally return dry-run diff metadata
        # 4) commit writes/deletes and return result payload
        fallbacks: list[str] = []
        try:
            file_patches = parse_patch_content(patch_content)
        except ValueError as exc:
            error_text = str(exc)
            return self._strict_patch_error(
                error_code="PATCH_PARSE_ERROR",
                message=_build_parse_error_message(error_text),
                phase="parse",
                changed_files=0,
                hunks_applied=0,
                fallbacks=[f"parse_error:{_classify_parse_error(error_text)}"],
                actions={"add": 0, "update": 0, "delete": 0},
                retryable=True,
            )

        updated_hunks = 0
        changed_files = 0
        commit_actions: list[PatchCommitAction] = []
        resolved_patches: list[tuple[FilePatch, str]] = []

        for file_patch in file_patches:
            try:
                resolved_patches.append(
                    (file_patch, _resolve_patch_path(file_patch.path))
                )
            except ValueError as exc:
                return self._strict_patch_error(
                    error_code="PATCH_PATH_ERROR",
                    message=_format_error_message(
                        reason=f"Invalid patch path '{file_patch.path}'.",
                        fix="Use a workspace-relative path that resolves inside `/workspace`.",
                    ),
                    phase="resolve",
                    matched_files=len(file_patches),
                    fallbacks=[f"path_resolve_error({file_patch.path}): {exc}"],
                )

        read_paths = [path for _, path in resolved_patches]
        for file_patch, _ in resolved_patches:
            if file_patch.move_to is None:
                continue
            try:
                move_target = _resolve_patch_path(file_patch.move_to)
            except ValueError:
                continue
            if move_target not in read_paths:
                read_paths.append(move_target)
        initial_contents = self._read_files_sync(backend, read_paths)

        for file_patch, path in resolved_patches:
            current_content, read_error = initial_contents.get(
                path,
                (None, f"Error: Unable to read '{path}'."),
            )
            if read_error is not None:
                return self._strict_patch_error(
                    error_code="PATCH_READ_ERROR",
                    message=_format_error_message(
                        reason=f"Unable to read '{path}' before applying patch.",
                        fix="Read the latest file state and retry with an exact SEARCH block.",
                    ),
                    phase="read",
                    matched_files=len(file_patches),
                    fallbacks=[f"read_error({path}): {read_error}"],
                )

            if file_patch.action == "Add":
                add_content = "\n".join(file_patch.add_lines)
                if current_content is not None:
                    return self._strict_patch_error(
                        error_code="PATCH_TARGET_EXISTS",
                        message=_format_error_message(
                            reason=f"Cannot Add File '{path}' because it already exists.",
                            fix="Use `Update File` with an exact SEARCH block instead of overwriting.",
                        ),
                        phase="plan",
                        matched_files=len(file_patches),
                        fallbacks=[f"add_target_exists({path})"],
                    )
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
                    fallbacks.append(f"delete_missing_skipped({path})")
                    continue
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
                return self._strict_patch_error(
                    error_code="PATCH_TARGET_MISSING",
                    message=_format_error_message(
                        reason=f"Cannot Update File '{path}' because it does not exist.",
                        fix="Use `Add File` to create a new file, or re-read the workspace if the path is wrong.",
                    ),
                    phase="plan",
                    matched_files=len(file_patches),
                    fallbacks=[f"update_missing({path})"],
                )

            try:
                updated_content, applied = apply_update_patch(
                    current_content,
                    file_path=path,
                    hunks=file_patch.hunks,
                )
            except ValueError as exc:
                return self._strict_patch_error(
                    error_code="PATCH_APPLY_ERROR",
                    message=_format_error_message(
                        reason=f"Failed to apply Update File for '{path}': {exc}",
                        fix="Read the latest file and retry with an exact, unique SEARCH block.",
                    ),
                    phase="apply",
                    matched_files=len(file_patches),
                    fallbacks=[f"update_apply_error({path}): {exc}"],
                )

            if updated_content == current_content and file_patch.move_to is None:
                continue

            if file_patch.move_to is not None:
                move_target: str | None = None
                try:
                    move_target = _resolve_patch_path(file_patch.move_to)
                except ValueError as exc:
                    return self._strict_patch_error(
                        error_code="PATCH_MOVE_TARGET_ERROR",
                        message=_format_error_message(
                            reason=f"Invalid move target '{file_patch.move_to}' for '{path}'.",
                            fix="Use a workspace-relative destination path.",
                        ),
                        phase="resolve",
                        matched_files=len(file_patches),
                        fallbacks=[f"move_target_invalid({path}): {exc}"],
                    )

                target_current, target_read_error = initial_contents.get(
                    move_target,
                    (None, f"Error: Unable to read '{move_target}'."),
                )
                if target_read_error is not None:
                    return self._strict_patch_error(
                        error_code="PATCH_MOVE_TARGET_READ_ERROR",
                        message=_format_error_message(
                            reason=f"Unable to read move target '{move_target}' for '{path}'.",
                            fix="Re-read the workspace and retry.",
                        ),
                        phase="read",
                        matched_files=len(file_patches),
                        fallbacks=[
                            f"move_target_read_error({path}->{move_target}): {target_read_error}"
                        ],
                    )
                if target_current is not None:
                    return self._strict_patch_error(
                        error_code="PATCH_MOVE_TARGET_EXISTS",
                        message=_format_error_message(
                            reason=(
                                f"Cannot move '{path}' to '{move_target}' because the destination already exists."
                            ),
                            fix="Pick a new destination or update the existing file explicitly.",
                        ),
                        phase="plan",
                        matched_files=len(file_patches),
                        fallbacks=[f"move_target_exists({path}->{move_target})"],
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
            dry_run_file_diffs: list[dict[str, Any]] = []
            for action in commit_actions:
                metadata = self._build_file_diff_result(action=action)
                if metadata is None:
                    continue
                enriched = self._enrich_file_diff_with_session_stats(
                    file_diff=metadata,
                    action=action,
                    runtime_state=runtime_state,
                    persist_state=False,
                )
                dry_run_file_diffs.append(enriched)
                if len(dry_run_file_diffs) >= _MAX_FILE_DIFFS:
                    break
            action_counts = self._summarize_action_counts(commit_actions)
            return self._ok_result(
                message="Patch dry-run passed.",
                details={
                    "phase": "dry_run",
                    "matched_files": len(file_patches),
                    "changed_files": changed_files,
                    "hunks_applied": updated_hunks,
                    "fallbacks": fallbacks,
                    "actions": {
                        "add": action_counts["Add"],
                        "update": action_counts["Update"],
                        "delete": action_counts["Delete"],
                    },
                    "file_diffs": dry_run_file_diffs,
                    "file_diffs_truncated": len(commit_actions)
                    > len(dry_run_file_diffs),
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
                    "fallbacks": fallbacks,
                    "file_diffs": [],
                },
            )

        applied_actions: list[PatchCommitAction] = []
        upload_actions: list[PatchCommitAction] = []
        upload_entries: list[tuple[str, bytes]] = []
        for commit_action in commit_actions:
            if commit_action.action in {"Add", "Update"}:
                if commit_action.after_content is None:
                    fallbacks.append(
                        "commit_error_skipped("
                        f"{commit_action.action}:{commit_action.path}): "
                        f"Error: Missing commit content for '{commit_action.path}'."
                    )
                    continue
                upload_actions.append(commit_action)
                upload_entries.append(
                    (commit_action.path, commit_action.after_content.encode("utf-8"))
                )

        if upload_entries:
            upload_responses = backend.upload_files(upload_entries)
            for action, response in zip(upload_actions, upload_responses, strict=False):
                error = getattr(response, "error", "invalid response")
                if error is not None:
                    fallbacks.append(
                        "commit_error_skipped("
                        f"{action.action}:{action.path}): Error: Unable to write '{action.path}': {error}"
                    )
                    continue
                applied_actions.append(action)
            if len(upload_responses) < len(upload_actions):
                for action in upload_actions[len(upload_responses) :]:
                    fallbacks.append(
                        "commit_error_skipped("
                        f"{action.action}:{action.path}): Error: upload response missing."
                    )

        for commit_action in commit_actions:
            if commit_action.action != "Delete":
                continue
            commit_error = self._delete_file_sync(backend, commit_action.path)
            if commit_error is not None:
                fallbacks.append(
                    "commit_error_skipped("
                    f"{commit_action.action}:{commit_action.path}): {commit_error}"
                )
                continue
            applied_actions.append(commit_action)

        file_diffs: list[dict[str, Any]] = []
        for action in applied_actions:
            metadata = self._build_file_diff_result(action=action)
            if metadata is None:
                continue
            enriched = self._enrich_file_diff_with_session_stats(
                file_diff=metadata,
                action=action,
                runtime_state=runtime_state,
                persist_state=True,
            )
            file_diffs.append(enriched)
            if len(file_diffs) >= _MAX_FILE_DIFFS:
                break
        action_counts = self._summarize_action_counts(applied_actions)

        return self._ok_result(
            message=(
                f"Applied patch across {changed_files} file(s) "
                f"(add {action_counts['Add']}, update {action_counts['Update']}, "
                f"delete {action_counts['Delete']}; update hunks {updated_hunks})."
            ),
            details={
                "phase": "commit",
                "matched_files": len(file_patches),
                "changed_files": changed_files,
                "hunks_applied": updated_hunks,
                "fallbacks": fallbacks,
                "actions": {
                    "add": action_counts["Add"],
                    "update": action_counts["Update"],
                    "delete": action_counts["Delete"],
                },
                "file_diffs": file_diffs,
                "file_diffs_truncated": len(applied_actions) > len(file_diffs),
            },
        )

    # ===== Patch execution: async =====
    async def _apply_patch_async(
        self,
        backend: BackendProtocol,
        patch_content: str,
        *,
        dry_run: bool = False,
        runtime_state: PatchFilesystemState | None = None,
    ) -> str:
        # Async variant mirrors _apply_patch_sync to keep behavior consistent.
        fallbacks: list[str] = []
        try:
            file_patches = parse_patch_content(patch_content)
        except ValueError as exc:
            error_text = str(exc)
            return self._strict_patch_error(
                error_code="PATCH_PARSE_ERROR",
                message=_build_parse_error_message(error_text),
                phase="parse",
                changed_files=0,
                hunks_applied=0,
                fallbacks=[f"parse_error:{_classify_parse_error(error_text)}"],
                actions={"add": 0, "update": 0, "delete": 0},
                retryable=True,
            )

        updated_hunks = 0
        changed_files = 0
        commit_actions: list[PatchCommitAction] = []
        resolved_patches: list[tuple[FilePatch, str]] = []

        for file_patch in file_patches:
            try:
                resolved_patches.append(
                    (file_patch, _resolve_patch_path(file_patch.path))
                )
            except ValueError as exc:
                return self._strict_patch_error(
                    error_code="PATCH_PATH_ERROR",
                    message=_format_error_message(
                        reason=f"Invalid patch path '{file_patch.path}'.",
                        fix="Use a workspace-relative path that resolves inside `/workspace`.",
                    ),
                    phase="resolve",
                    matched_files=len(file_patches),
                    fallbacks=[f"path_resolve_error({file_patch.path}): {exc}"],
                )

        read_paths = [path for _, path in resolved_patches]
        for file_patch, _ in resolved_patches:
            if file_patch.move_to is None:
                continue
            try:
                move_target = _resolve_patch_path(file_patch.move_to)
            except ValueError:
                continue
            if move_target not in read_paths:
                read_paths.append(move_target)
        initial_contents = await self._read_files_async(backend, read_paths)

        for file_patch, path in resolved_patches:
            current_content, read_error = initial_contents.get(
                path,
                (None, f"Error: Unable to read '{path}'."),
            )
            if read_error is not None:
                return self._strict_patch_error(
                    error_code="PATCH_READ_ERROR",
                    message=_format_error_message(
                        reason=f"Unable to read '{path}' before applying patch.",
                        fix="Read the latest file state and retry with an exact SEARCH block.",
                    ),
                    phase="read",
                    matched_files=len(file_patches),
                    fallbacks=[f"read_error({path}): {read_error}"],
                )

            if file_patch.action == "Add":
                add_content = "\n".join(file_patch.add_lines)
                if current_content is not None:
                    return self._strict_patch_error(
                        error_code="PATCH_TARGET_EXISTS",
                        message=_format_error_message(
                            reason=f"Cannot Add File '{path}' because it already exists.",
                            fix="Use `Update File` with an exact SEARCH block instead of overwriting.",
                        ),
                        phase="plan",
                        matched_files=len(file_patches),
                        fallbacks=[f"add_target_exists({path})"],
                    )
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
                    fallbacks.append(f"delete_missing_skipped({path})")
                    continue
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
                return self._strict_patch_error(
                    error_code="PATCH_TARGET_MISSING",
                    message=_format_error_message(
                        reason=f"Cannot Update File '{path}' because it does not exist.",
                        fix="Use `Add File` to create a new file, or re-read the workspace if the path is wrong.",
                    ),
                    phase="plan",
                    matched_files=len(file_patches),
                    fallbacks=[f"update_missing({path})"],
                )

            try:
                updated_content, applied = apply_update_patch(
                    current_content,
                    file_path=path,
                    hunks=file_patch.hunks,
                )
            except ValueError as exc:
                return self._strict_patch_error(
                    error_code="PATCH_APPLY_ERROR",
                    message=_format_error_message(
                        reason=f"Failed to apply Update File for '{path}': {exc}",
                        fix="Read the latest file and retry with an exact, unique SEARCH block.",
                    ),
                    phase="apply",
                    matched_files=len(file_patches),
                    fallbacks=[f"update_apply_error({path}): {exc}"],
                )

            if updated_content == current_content and file_patch.move_to is None:
                continue

            if file_patch.move_to is not None:
                move_target: str | None = None
                try:
                    move_target = _resolve_patch_path(file_patch.move_to)
                except ValueError as exc:
                    return self._strict_patch_error(
                        error_code="PATCH_MOVE_TARGET_ERROR",
                        message=_format_error_message(
                            reason=f"Invalid move target '{file_patch.move_to}' for '{path}'.",
                            fix="Use a workspace-relative destination path.",
                        ),
                        phase="resolve",
                        matched_files=len(file_patches),
                        fallbacks=[f"move_target_invalid({path}): {exc}"],
                    )

                target_current, target_read_error = initial_contents.get(
                    move_target,
                    (None, f"Error: Unable to read '{move_target}'."),
                )
                if target_read_error is not None:
                    return self._strict_patch_error(
                        error_code="PATCH_MOVE_TARGET_READ_ERROR",
                        message=_format_error_message(
                            reason=f"Unable to read move target '{move_target}' for '{path}'.",
                            fix="Re-read the workspace and retry.",
                        ),
                        phase="read",
                        matched_files=len(file_patches),
                        fallbacks=[
                            f"move_target_read_error({path}->{move_target}): {target_read_error}"
                        ],
                    )
                if target_current is not None:
                    return self._strict_patch_error(
                        error_code="PATCH_MOVE_TARGET_EXISTS",
                        message=_format_error_message(
                            reason=(
                                f"Cannot move '{path}' to '{move_target}' because the destination already exists."
                            ),
                            fix="Pick a new destination or update the existing file explicitly.",
                        ),
                        phase="plan",
                        matched_files=len(file_patches),
                        fallbacks=[f"move_target_exists({path}->{move_target})"],
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
            dry_run_file_diffs: list[dict[str, Any]] = []
            for action in commit_actions:
                metadata = self._build_file_diff_result(action=action)
                if metadata is None:
                    continue
                enriched = self._enrich_file_diff_with_session_stats(
                    file_diff=metadata,
                    action=action,
                    runtime_state=runtime_state,
                    persist_state=False,
                )
                dry_run_file_diffs.append(enriched)
                if len(dry_run_file_diffs) >= _MAX_FILE_DIFFS:
                    break
            action_counts = self._summarize_action_counts(commit_actions)
            return self._ok_result(
                message="Patch dry-run passed.",
                details={
                    "phase": "dry_run",
                    "matched_files": len(file_patches),
                    "changed_files": changed_files,
                    "hunks_applied": updated_hunks,
                    "fallbacks": fallbacks,
                    "actions": {
                        "add": action_counts["Add"],
                        "update": action_counts["Update"],
                        "delete": action_counts["Delete"],
                    },
                    "file_diffs": dry_run_file_diffs,
                    "file_diffs_truncated": len(commit_actions)
                    > len(dry_run_file_diffs),
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
                    "fallbacks": fallbacks,
                    "file_diffs": [],
                },
            )

        applied_actions: list[PatchCommitAction] = []
        upload_actions: list[PatchCommitAction] = []
        upload_entries: list[tuple[str, bytes]] = []
        for commit_action in commit_actions:
            if commit_action.action in {"Add", "Update"}:
                if commit_action.after_content is None:
                    fallbacks.append(
                        "commit_error_skipped("
                        f"{commit_action.action}:{commit_action.path}): "
                        f"Error: Missing commit content for '{commit_action.path}'."
                    )
                    continue
                upload_actions.append(commit_action)
                upload_entries.append(
                    (commit_action.path, commit_action.after_content.encode("utf-8"))
                )

        if upload_entries:
            upload_responses = await backend.aupload_files(upload_entries)
            for action, response in zip(upload_actions, upload_responses, strict=False):
                error = getattr(response, "error", "invalid response")
                if error is not None:
                    fallbacks.append(
                        "commit_error_skipped("
                        f"{action.action}:{action.path}): Error: Unable to write '{action.path}': {error}"
                    )
                    continue
                applied_actions.append(action)
            if len(upload_responses) < len(upload_actions):
                for action in upload_actions[len(upload_responses) :]:
                    fallbacks.append(
                        "commit_error_skipped("
                        f"{action.action}:{action.path}): Error: upload response missing."
                    )

        for commit_action in commit_actions:
            if commit_action.action != "Delete":
                continue
            commit_error = await self._delete_file_async(backend, commit_action.path)
            if commit_error is not None:
                fallbacks.append(
                    "commit_error_skipped("
                    f"{commit_action.action}:{commit_action.path}): {commit_error}"
                )
                continue
            applied_actions.append(commit_action)

        file_diffs: list[dict[str, Any]] = []
        for action in applied_actions:
            metadata = self._build_file_diff_result(action=action)
            if metadata is None:
                continue
            enriched = self._enrich_file_diff_with_session_stats(
                file_diff=metadata,
                action=action,
                runtime_state=runtime_state,
                persist_state=True,
            )
            file_diffs.append(enriched)
            if len(file_diffs) >= _MAX_FILE_DIFFS:
                break
        action_counts = self._summarize_action_counts(applied_actions)

        return self._ok_result(
            message=(
                f"Applied patch across {changed_files} file(s) "
                f"(add {action_counts['Add']}, update {action_counts['Update']}, "
                f"delete {action_counts['Delete']}; update hunks {updated_hunks})."
            ),
            details={
                "phase": "commit",
                "matched_files": len(file_patches),
                "changed_files": changed_files,
                "hunks_applied": updated_hunks,
                "fallbacks": fallbacks,
                "actions": {
                    "add": action_counts["Add"],
                    "update": action_counts["Update"],
                    "delete": action_counts["Delete"],
                },
                "file_diffs": file_diffs,
                "file_diffs_truncated": len(applied_actions) > len(file_diffs),
            },
        )

    # ===== Backend file I/O helpers =====
    def _read_files_sync(
        self,
        backend: BackendProtocol,
        file_paths: list[str],
    ) -> dict[str, tuple[str | None, str | None]]:
        if not file_paths:
            return {}
        responses = backend.download_files(file_paths)
        results: dict[str, tuple[str | None, str | None]] = {}
        for index, path in enumerate(file_paths):
            if index >= len(responses):
                results[path] = (None, f"Error: Unable to read '{path}'.")
                continue
            response = responses[index]
            if response.error is not None:
                if response.error == "file_not_found":
                    results[path] = (None, None)
                else:
                    results[path] = (
                        None,
                        f"Error: Unable to read '{path}': {response.error}",
                    )
                continue
            if response.content is None:
                results[path] = (None, f"Error: Empty file payload for '{path}'.")
                continue
            decoded_content, decode_error = self._decode_file_content(
                file_path=path,
                raw_content=response.content,
            )
            if decode_error is not None:
                results[path] = (None, decode_error)
                continue
            results[path] = (decoded_content, None)
        return results

    async def _read_files_async(
        self,
        backend: BackendProtocol,
        file_paths: list[str],
    ) -> dict[str, tuple[str | None, str | None]]:
        if not file_paths:
            return {}
        responses = await backend.adownload_files(file_paths)
        results: dict[str, tuple[str | None, str | None]] = {}
        for index, path in enumerate(file_paths):
            if index >= len(responses):
                results[path] = (None, f"Error: Unable to read '{path}'.")
                continue
            response = responses[index]
            if response.error is not None:
                if response.error == "file_not_found":
                    results[path] = (None, None)
                else:
                    results[path] = (
                        None,
                        f"Error: Unable to read '{path}': {response.error}",
                    )
                continue
            if response.content is None:
                results[path] = (None, f"Error: Empty file payload for '{path}'.")
                continue
            decoded_content, decode_error = self._decode_file_content(
                file_path=path,
                raw_content=response.content,
            )
            if decode_error is not None:
                results[path] = (None, decode_error)
                continue
            results[path] = (decoded_content, None)
        return results

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
        return self._decode_file_content(
            file_path=file_path,
            raw_content=response.content,
        )

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
        return self._decode_file_content(
            file_path=file_path,
            raw_content=response.content,
        )

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

    def _decode_file_content(
        self,
        *,
        file_path: str,
        raw_content: bytes,
    ) -> tuple[str | None, str | None]:
        try:
            return raw_content.decode("utf-8"), None
        except UnicodeDecodeError as exc:
            return (
                None,
                "Error: Unable to read "
                f"'{file_path}': file is not valid UTF-8 text ({exc.reason}).",
            )

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


# ===== Parser helpers =====
def _strip_fence(patch_content: str) -> str:
    text = patch_content.strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        if len(lines) >= 2:
            text = "\n".join(lines[1:-1]).strip()
    return text


def _looks_like_unified_diff(text: str) -> bool:
    return _UNIFIED_DIFF_MARKER_RE.search(text) is not None


def _classify_parse_error(error_text: str) -> str:
    if "Missing </search>" in error_text:
        return "missing_search_close"
    if "Missing </replace>" in error_text:
        return "missing_replace_close"
    if "Found <replace> without a preceding </search>" in error_text:
        return "replace_without_search"
    if "Must contain at least one <search>...</search>" in error_text:
        return "missing_search_block"
    if "must not contain body lines" in error_text:
        return "delete_body_not_allowed"
    if "appears multiple times" in error_text:
        return "duplicate_file_section"
    return "invalid_patch_format"


def _clean_parse_error_text(error_text: str) -> str:
    cleaned = error_text.replace(" (or ======= for legacy format)", "")
    cleaned = cleaned.replace(" (or >>>>>>> REPLACE for legacy format)", "")
    return cleaned


def _format_error_message(*, reason: str, fix: str) -> str:
    return f"Reason: {reason} Fix: {fix}"


def _build_parse_error_message(error_text: str) -> str:
    cleaned_error = _clean_parse_error_text(error_text)
    if "Missing </search>" in error_text:
        return _format_error_message(
            reason=cleaned_error,
            fix=(
                "Re-read the file and retry with a smaller complete patch. "
                "Ensure `</search>` is on its own line before `<replace>`."
            ),
        )
    if "Missing </replace>" in error_text:
        return _format_error_message(
            reason=cleaned_error,
            fix=(
                "Re-read the file and retry with a smaller complete patch. "
                "Ensure `</replace>` is on its own line and the payload ends with `*** End Patch`."
            ),
        )
    if "Found <replace> without a preceding </search>" in error_text:
        return _format_error_message(
            reason=cleaned_error,
            fix=(
                "Every `Update File` hunk must contain a complete "
                "`<search>...</search>` block before `<replace>...</replace>`."
            ),
        )
    if "Must contain at least one <search>...</search>" in error_text:
        return _format_error_message(
            reason=cleaned_error,
            fix=(
                "`Update File` only supports exact `<search>...</search>` "
                "and `<replace>...</replace>` blocks."
            ),
        )
    return _format_error_message(
        reason=cleaned_error,
        fix="Re-read the target file and regenerate a smaller, fully closed patch.",
    )


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
        add_lines = _parse_add_lines(body_lines=body_lines)
        return FilePatch(action="Add", path=path, add_lines=add_lines)

    move_to, update_body_lines = _extract_move_to(body_lines=body_lines)
    hunks = _parse_update_hunks(path=path, body_lines=update_body_lines)
    return FilePatch(action="Update", path=path, move_to=move_to, hunks=hunks)


def _extract_move_to(
    *,
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
            if move_to is None:
                maybe_target = stripped[len("*** Move to:") :].strip()
                if maybe_target:
                    move_to = maybe_target
            continue

        first_content_seen = True
        remaining.append(line)

    return move_to, remaining


def _parse_add_lines(*, body_lines: list[str]) -> tuple[str, ...]:
    # Add File uses raw body text as final file content.
    return tuple(body_lines)


def _parse_update_hunks(*, path: str, body_lines: list[str]) -> tuple[PatchHunk, ...]:
    # Supported syntaxes:
    # - Preferred XML: <search>...</search> + <replace>...</replace>
    # - Legacy fallback: <<<<<<< SEARCH ... ======= ... >>>>>>> REPLACE
    hunks: list[PatchHunk] = []
    state = "TEXT"
    current_search: list[str] = []
    current_replace: list[str] = []

    for line in body_lines:
        stripped = line.strip()

        if stripped in {"<search>", "<<<<<<< SEARCH"}:
            if state != "TEXT":
                raise ValueError(f"Update File '{path}': Found nested search block.")
            state = "SEARCH"
            current_search = []
            current_replace = []

        elif stripped == "</search>":
            if state != "SEARCH":
                raise ValueError(
                    f"Update File '{path}': Found </search> without a preceding <search> block."
                )
            state = "WAITING_REPLACE"

        elif stripped == "<replace>":
            # Tolerate missing </search> by treating <replace> as an implicit close.
            if state == "SEARCH" or state == "WAITING_REPLACE":
                state = "REPLACE"
            else:
                raise ValueError(
                    f"Update File '{path}': Found <replace> without a preceding </search>."
                )

        elif stripped == "=======":
            if state != "SEARCH":
                raise ValueError(
                    f"Update File '{path}': Found ======= without a preceding SEARCH block."
                )
            state = "REPLACE"

        elif stripped in {"</replace>", ">>>>>>> REPLACE"}:
            if state != "REPLACE":
                raise ValueError(
                    f"Update File '{path}': Found replace block close marker without an open replace block."
                )
            state = "TEXT"

            search_text = "\n".join(current_search)
            replace_text = "\n".join(current_replace)
            hunks.append(PatchHunk(search_text=search_text, replace_text=replace_text))

        else:
            if state == "SEARCH":
                current_search.append(line)
            elif state == "REPLACE":
                current_replace.append(line)

    if state == "SEARCH":
        raise ValueError(
            f"Update File '{path}': Missing </search> (or ======= for legacy format)."
        )
    if state == "WAITING_REPLACE":
        raise ValueError(f"Update File '{path}': Missing <replace> after </search>.")
    if state == "REPLACE":
        raise ValueError(
            f"Update File '{path}': Missing </replace> (or >>>>>>> REPLACE for legacy format)."
        )

    if not hunks:
        raise ValueError(
            f"Update File '{path}': Must contain at least one <search>...</search> and <replace>...</replace> block."
        )

    return tuple(hunks)


def _apply_single_hunk(
    content: str,
    *,
    file_path: str,
    hunk: PatchHunk,
    hunk_index: int,
) -> str:
    _ = hunk_index
    search_text = hunk.search_text
    replace_text = hunk.replace_text

    # Require a unique match to prevent accidental broad replacements.
    matches = content.count(search_text)
    if matches == 1:
        return content.replace(search_text, replace_text, 1)

    if matches == 0:
        raise ValueError(
            f"PATCH_NO_MATCH: SEARCH block for '{file_path}' has no exact match. "
            "Read the latest file and ensure SEARCH text matches source exactly."
        )

    if matches > 1:
        raise ValueError(
            f"PATCH_AMBIGUOUS_MATCH: SEARCH block for '{file_path}' matched {matches} locations. "
            "Add more surrounding context to make it unique."
        )

    return content
