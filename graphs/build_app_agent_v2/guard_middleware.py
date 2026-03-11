"""Tool call guards for create_agent-based build app graph."""

from __future__ import annotations

import difflib
import hashlib
import posixpath
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from langchain.agents.middleware.types import (
    AgentMiddleware,
    AgentState,
    ToolCallRequest,
)
from langchain_core.messages import ToolMessage
from langgraph.types import Command

_WRITE_TOOLS = {"edit_file", "write_file", "apply_patch"}
_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_PATCH_FILE_HEADER_RE = re.compile(
    r"^\*\*\* (?:Add|Update|Delete) File:\s*(.+?)\s*$",
    re.MULTILINE,
)


class ToolGuardState(AgentState):
    """Additional state managed by tool-call guard middleware."""

    write_counts_in_round: dict[str, int]
    write_content_hashes_in_round: dict[str, str]
    writes_per_file_total: dict[str, int]
    edit_calls_per_file_total: dict[str, int]
    small_edit_calls_per_file_total: dict[str, int]
    tool_calls_total: int
    blocked_writes_total: int
    blocked_fragmented_edits_total: int
    noop_writes_total: int
    model_rounds_total: int
    tool_guard_summary: dict[str, Any]


class ToolCallGuardMiddleware(AgentMiddleware[ToolGuardState, Any, Any]):
    """Prevent noisy repeated writes and fragmented micro-edits."""

    state_schema = ToolGuardState

    def __init__(
        self,
        *,
        max_writes_per_file_per_round: int = 1,
        max_writes_per_file_total: int = 0,
        max_edit_calls_per_file_total: int = 3,
        small_edit_char_threshold: int = 160,
        max_small_edits_per_file_total: int = 2,
        blocked_new_file_names: tuple[str, ...] = ("test-responsive.html",),
    ) -> None:
        self.max_writes_per_file_per_round = max_writes_per_file_per_round
        self.max_writes_per_file_total = max_writes_per_file_total
        self.max_edit_calls_per_file_total = max_edit_calls_per_file_total
        self.small_edit_char_threshold = small_edit_char_threshold
        self.max_small_edits_per_file_total = max_small_edits_per_file_total
        self.blocked_new_file_names = set(blocked_new_file_names)

    def before_agent(
        self,
        state: ToolGuardState,
        runtime: Any,
    ) -> dict[str, Any]:
        """Initialize metrics before each run."""
        _ = (state, runtime)
        return {
            "write_counts_in_round": {},
            "write_content_hashes_in_round": {},
            "writes_per_file_total": {},
            "edit_calls_per_file_total": {},
            "small_edit_calls_per_file_total": {},
            "tool_calls_total": 0,
            "blocked_writes_total": 0,
            "blocked_fragmented_edits_total": 0,
            "noop_writes_total": 0,
            "model_rounds_total": 0,
            "tool_guard_summary": {},
        }

    def before_model(
        self,
        state: ToolGuardState,
        runtime: Any,
    ) -> dict[str, Any]:
        """Reset per-round counters before each model call."""
        _ = runtime
        rounds = int((state or {}).get("model_rounds_total", 0)) + 1
        return {
            "write_counts_in_round": {},
            "write_content_hashes_in_round": {},
            "model_rounds_total": rounds,
        }

    def after_agent(
        self,
        state: ToolGuardState,
        runtime: Any,
    ) -> dict[str, Any]:
        """Persist a compact summary for runtime inspection."""
        _ = runtime
        summary = {
            "tool_calls_total": int((state or {}).get("tool_calls_total", 0)),
            "model_rounds_total": int((state or {}).get("model_rounds_total", 0)),
            "blocked_writes_total": int((state or {}).get("blocked_writes_total", 0)),
            "blocked_fragmented_edits_total": int(
                (state or {}).get("blocked_fragmented_edits_total", 0)
            ),
            "noop_writes_total": int((state or {}).get("noop_writes_total", 0)),
            "writes_per_file_total": dict(
                (state or {}).get("writes_per_file_total") or {}
            ),
            "edit_calls_per_file_total": dict(
                (state or {}).get("edit_calls_per_file_total") or {}
            ),
            "small_edit_calls_per_file_total": dict(
                (state or {}).get("small_edit_calls_per_file_total") or {}
            ),
        }
        return {"tool_guard_summary": summary}

    def _increment_counter(self, state: dict[str, Any], key: str) -> None:
        state[key] = int(state.get(key, 0)) + 1

    def _extract_apply_patch_paths(self, patch_content: Any) -> list[str]:
        if not isinstance(patch_content, str):
            return []
        paths: list[str] = []
        seen: set[str] = set()
        for match in _PATCH_FILE_HEADER_RE.finditer(patch_content):
            path = match.group(1).strip()
            if not path or path in seen:
                continue
            seen.add(path)
            paths.append(path)
        return paths

    def _normalize_workspace_path(self, file_path: str) -> str:
        """Normalize file paths so sandbox reads are anchored under /workspace."""
        path = file_path.strip()
        if not path:
            return path
        if path.startswith("/"):
            return posixpath.normpath(path)
        return posixpath.normpath(posixpath.join("/workspace", path))

    def _read_file_content(
        self, request: ToolCallRequest, file_path: str
    ) -> str | None:
        """Read raw file content from sandbox backend for diff metadata."""
        try:
            from backends.docker import DockerBackend

            backend = DockerBackend(request.runtime)
            responses = backend.download_files([file_path])
        except Exception:  # pragma: no cover - metadata is best-effort
            return None

        if not responses:
            return None
        response = responses[0]
        if response.error is not None or response.content is None:
            return None
        try:
            return response.content.decode("utf-8")
        except UnicodeDecodeError:
            return None

    async def _aread_file_content(
        self,
        request: ToolCallRequest,
        file_path: str,
    ) -> str | None:
        """Async read raw file content from sandbox backend for diff metadata."""
        try:
            from backends.docker import DockerBackend

            backend = DockerBackend(request.runtime)
            responses = await backend.adownload_files([file_path])
        except Exception:  # pragma: no cover - metadata is best-effort
            return None

        if not responses:
            return None
        response = responses[0]
        if response.error is not None or response.content is None:
            return None
        try:
            return response.content.decode("utf-8")
        except UnicodeDecodeError:
            return None

    def _compute_hunks(self, before: str, after: str) -> list[dict[str, int]]:
        """Compute unified-diff hunk ranges with line numbers."""
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
            match = _HUNK_RE.match(line)
            if not match:
                continue

            old_start = int(match.group(1))
            old_count = int(match.group(2) or "1")
            new_start = int(match.group(3))
            new_count = int(match.group(4) or "1")
            hunks.append(
                {
                    "old_start": old_start,
                    "old_count": old_count,
                    "new_start": new_start,
                    "new_count": new_count,
                }
            )

        return hunks

    def _build_file_diff_metadata(
        self,
        *,
        tool_name: str,
        file_path: str,
        before: str | None,
        after: str | None,
    ) -> dict[str, Any] | None:
        """Build line-number based diff metadata for frontend rendering."""
        if before is None and after is None:
            return None
        if before == after:
            return None

        before_text = before or ""
        after_text = after or ""
        hunks = self._compute_hunks(before_text, after_text)
        if not hunks:
            return None

        return {
            "tool_name": tool_name,
            "file_path": file_path,
            "before_line_count": len(before_text.splitlines()),
            "after_line_count": len(after_text.splitlines()),
            "hunks": hunks,
        }

    def _attach_metadata_to_message(
        self,
        message: ToolMessage,
        metadata: dict[str, Any],
    ) -> ToolMessage:
        existing_kwargs = dict(message.additional_kwargs or {})
        existing_kwargs["file_diff"] = metadata
        return message.model_copy(update={"additional_kwargs": existing_kwargs})

    def _attach_diff_metadata(
        self,
        result: ToolMessage | Command[Any],
        metadata: dict[str, Any],
    ) -> ToolMessage | Command[Any]:
        """Attach diff metadata into tool outputs for UI consumption."""
        if isinstance(result, ToolMessage):
            return self._attach_metadata_to_message(result, metadata)

        if not isinstance(result, Command) or not isinstance(result.update, dict):
            return result

        update = dict(result.update)
        messages = update.get("messages")
        if isinstance(messages, list):
            patched_messages: list[Any] = []
            attached = False
            for msg in messages:
                if isinstance(msg, ToolMessage):
                    patched_messages.append(
                        self._attach_metadata_to_message(msg, metadata)
                    )
                    attached = True
                else:
                    patched_messages.append(msg)
            if attached:
                update["messages"] = patched_messages

        existing_diffs = list(update.get("tool_file_diffs") or [])
        existing_diffs.append(metadata)
        update["tool_file_diffs"] = existing_diffs

        return Command(
            graph=result.graph,
            update=update,
            resume=result.resume,
            goto=result.goto,
        )

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command[Any]],
    ) -> ToolMessage | Command[Any]:
        tool_name = request.tool_call.get("name")
        tool_call_id = request.tool_call.get("id", "")
        args = request.tool_call.get("args") or {}

        state = request.state if isinstance(request.state, dict) else {}
        self._increment_counter(state, "tool_calls_total")

        if tool_name not in _WRITE_TOOLS or not isinstance(args, dict):
            return handler(request)

        write_counts = dict(state.get("write_counts_in_round") or {})
        write_hashes = dict(state.get("write_content_hashes_in_round") or {})
        write_totals = dict(state.get("writes_per_file_total") or {})
        edit_totals = dict(state.get("edit_calls_per_file_total") or {})
        small_edit_totals = dict(state.get("small_edit_calls_per_file_total") or {})

        if tool_name == "apply_patch":
            if bool(args.get("dry_run")):
                return handler(request)

            patch_paths = self._extract_apply_patch_paths(args.get("patch_content"))
            if not patch_paths:
                self._increment_counter(state, "blocked_writes_total")
                return ToolMessage(
                    content=(
                        "Blocked apply_patch: no `*** Add/Update/Delete File:` "
                        "path found in patch_content."
                    ),
                    tool_call_id=tool_call_id,
                    status="error",
                )

            for path in patch_paths:
                current_round_writes = int(write_counts.get(path, 0))
                if current_round_writes >= self.max_writes_per_file_per_round:
                    self._increment_counter(state, "blocked_writes_total")
                    return ToolMessage(
                        content=(
                            f"Blocked apply_patch for '{path}'. "
                            "This file has already been written in the current round. "
                            "Please merge edits into one patch and retry in the next round."
                        ),
                        tool_call_id=tool_call_id,
                        status="error",
                    )

                current_total_writes = int(write_totals.get(path, 0))
                if (
                    self.max_writes_per_file_total > 0
                    and current_total_writes >= self.max_writes_per_file_total
                ):
                    self._increment_counter(state, "blocked_writes_total")
                    return ToolMessage(
                        content=(
                            f"Blocked apply_patch for '{path}'. "
                            "This file already reached the total write limit for this run. "
                            "Please consolidate remaining edits into one planned patch."
                        ),
                        tool_call_id=tool_call_id,
                        status="error",
                    )

            before_map = {
                path: self._read_file_content(
                    request,
                    self._normalize_workspace_path(path),
                )
                for path in patch_paths
            }
            result = handler(request)
            after_map = {
                path: self._read_file_content(
                    request,
                    self._normalize_workspace_path(path),
                )
                for path in patch_paths
            }

            for path in patch_paths:
                metadata = self._build_file_diff_metadata(
                    tool_name=tool_name,
                    file_path=path,
                    before=before_map.get(path),
                    after=after_map.get(path),
                )
                if metadata is not None:
                    result = self._attach_diff_metadata(result, metadata)
                    write_counts[path] = int(write_counts.get(path, 0)) + 1
                    write_totals[path] = int(write_totals.get(path, 0)) + 1

            state["write_counts_in_round"] = write_counts
            state["write_content_hashes_in_round"] = write_hashes
            state["writes_per_file_total"] = write_totals
            state["edit_calls_per_file_total"] = edit_totals
            state["small_edit_calls_per_file_total"] = small_edit_totals
            return result

        file_path = args.get("file_path")
        if not isinstance(file_path, str) or not file_path.strip():
            return handler(request)

        path = file_path.strip()
        file_name = Path(path).name

        if tool_name == "write_file" and file_name in self.blocked_new_file_names:
            self._increment_counter(state, "blocked_writes_total")
            return ToolMessage(
                content=(
                    f"Blocked write_file for '{file_name}'. "
                    "Please modify the existing source file directly instead of "
                    "creating a temporary verification file."
                ),
                tool_call_id=tool_call_id,
                status="error",
            )

        current_round_writes = int(write_counts.get(path, 0))
        if current_round_writes >= self.max_writes_per_file_per_round:
            self._increment_counter(state, "blocked_writes_total")
            return ToolMessage(
                content=(
                    f"Blocked {tool_name} for '{path}'. "
                    "This file has already been written in the current round. "
                    "Please merge edits into one patch and retry in the next round."
                ),
                tool_call_id=tool_call_id,
                status="error",
            )

        current_total_writes = int(write_totals.get(path, 0))
        if (
            self.max_writes_per_file_total > 0
            and current_total_writes >= self.max_writes_per_file_total
        ):
            self._increment_counter(state, "blocked_writes_total")
            return ToolMessage(
                content=(
                    f"Blocked {tool_name} for '{path}'. "
                    "This file already reached the total write limit for this run. "
                    "Please consolidate remaining edits into one planned patch."
                ),
                tool_call_id=tool_call_id,
                status="error",
            )

        is_small_edit = False
        if tool_name == "edit_file":
            total_edit_calls = int(edit_totals.get(path, 0))
            if total_edit_calls >= self.max_edit_calls_per_file_total:
                self._increment_counter(state, "blocked_writes_total")
                return ToolMessage(
                    content=(
                        f"Blocked edit_file for '{path}'. "
                        "This file already reached the edit_file limit for this run. "
                        "Please read the full file and apply one consolidated update."
                    ),
                    tool_call_id=tool_call_id,
                    status="error",
                )

            old_string = args.get("old_string")
            new_string = args.get("new_string")
            if isinstance(old_string, str) and isinstance(new_string, str):
                edit_span = max(len(old_string), len(new_string))
                is_small_edit = edit_span < self.small_edit_char_threshold

            if is_small_edit:
                total_small_edits = int(small_edit_totals.get(path, 0))
                if total_small_edits >= self.max_small_edits_per_file_total:
                    self._increment_counter(state, "blocked_writes_total")
                    self._increment_counter(state, "blocked_fragmented_edits_total")
                    return ToolMessage(
                        content=(
                            f"Blocked fragmented edit_file for '{path}'. "
                            "Too many small incremental edits were detected. "
                            "Please read the file once and submit one merged write."
                        ),
                        tool_call_id=tool_call_id,
                        status="error",
                    )

        if tool_name == "write_file":
            content = args.get("content")
            if isinstance(content, str):
                content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
                if write_hashes.get(path) == content_hash:
                    self._increment_counter(state, "noop_writes_total")
                    return ToolMessage(
                        content=(
                            f"Skipped write_file for '{path}' because the content is "
                            "identical to the last write in this round."
                        ),
                        tool_call_id=tool_call_id,
                    )
                write_hashes[path] = content_hash

        before_content = self._read_file_content(request, path)
        result = handler(request)
        after_content = self._read_file_content(request, path)
        metadata = self._build_file_diff_metadata(
            tool_name=tool_name,
            file_path=path,
            before=before_content,
            after=after_content,
        )
        if metadata is not None:
            result = self._attach_diff_metadata(result, metadata)

        write_counts[path] = current_round_writes + 1
        write_totals[path] = int(write_totals.get(path, 0)) + 1

        if tool_name == "edit_file":
            edit_totals[path] = int(edit_totals.get(path, 0)) + 1
            if is_small_edit:
                small_edit_totals[path] = int(small_edit_totals.get(path, 0)) + 1

        state["write_counts_in_round"] = write_counts
        state["write_content_hashes_in_round"] = write_hashes
        state["writes_per_file_total"] = write_totals
        state["edit_calls_per_file_total"] = edit_totals
        state["small_edit_calls_per_file_total"] = small_edit_totals

        return result

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[
            [ToolCallRequest],
            Awaitable[ToolMessage | Command[Any]],
        ],
    ) -> ToolMessage | Command[Any]:
        """Async variant of tool guard logic for astream/ainvoke paths."""
        tool_name = request.tool_call.get("name")
        tool_call_id = request.tool_call.get("id", "")
        args = request.tool_call.get("args") or {}

        state = request.state if isinstance(request.state, dict) else {}
        self._increment_counter(state, "tool_calls_total")

        if tool_name not in _WRITE_TOOLS or not isinstance(args, dict):
            return await handler(request)

        write_counts = dict(state.get("write_counts_in_round") or {})
        write_hashes = dict(state.get("write_content_hashes_in_round") or {})
        write_totals = dict(state.get("writes_per_file_total") or {})
        edit_totals = dict(state.get("edit_calls_per_file_total") or {})
        small_edit_totals = dict(state.get("small_edit_calls_per_file_total") or {})

        if tool_name == "apply_patch":
            if bool(args.get("dry_run")):
                return await handler(request)

            patch_paths = self._extract_apply_patch_paths(args.get("patch_content"))
            if not patch_paths:
                self._increment_counter(state, "blocked_writes_total")
                return ToolMessage(
                    content=(
                        "Blocked apply_patch: no `*** Add/Update/Delete File:` "
                        "path found in patch_content."
                    ),
                    tool_call_id=tool_call_id,
                    status="error",
                )

            for path in patch_paths:
                current_round_writes = int(write_counts.get(path, 0))
                if current_round_writes >= self.max_writes_per_file_per_round:
                    self._increment_counter(state, "blocked_writes_total")
                    return ToolMessage(
                        content=(
                            f"Blocked apply_patch for '{path}'. "
                            "This file has already been written in the current round. "
                            "Please merge edits into one patch and retry in the next round."
                        ),
                        tool_call_id=tool_call_id,
                        status="error",
                    )

                current_total_writes = int(write_totals.get(path, 0))
                if (
                    self.max_writes_per_file_total > 0
                    and current_total_writes >= self.max_writes_per_file_total
                ):
                    self._increment_counter(state, "blocked_writes_total")
                    return ToolMessage(
                        content=(
                            f"Blocked apply_patch for '{path}'. "
                            "This file already reached the total write limit for this run. "
                            "Please consolidate remaining edits into one planned patch."
                        ),
                        tool_call_id=tool_call_id,
                        status="error",
                    )

            before_map = {
                path: await self._aread_file_content(
                    request,
                    self._normalize_workspace_path(path),
                )
                for path in patch_paths
            }
            result = await handler(request)
            after_map = {
                path: await self._aread_file_content(
                    request,
                    self._normalize_workspace_path(path),
                )
                for path in patch_paths
            }

            for path in patch_paths:
                metadata = self._build_file_diff_metadata(
                    tool_name=tool_name,
                    file_path=path,
                    before=before_map.get(path),
                    after=after_map.get(path),
                )
                if metadata is not None:
                    result = self._attach_diff_metadata(result, metadata)
                    write_counts[path] = int(write_counts.get(path, 0)) + 1
                    write_totals[path] = int(write_totals.get(path, 0)) + 1

            state["write_counts_in_round"] = write_counts
            state["write_content_hashes_in_round"] = write_hashes
            state["writes_per_file_total"] = write_totals
            state["edit_calls_per_file_total"] = edit_totals
            state["small_edit_calls_per_file_total"] = small_edit_totals
            return result

        file_path = args.get("file_path")
        if not isinstance(file_path, str) or not file_path.strip():
            return await handler(request)

        path = file_path.strip()
        file_name = Path(path).name

        if tool_name == "write_file" and file_name in self.blocked_new_file_names:
            self._increment_counter(state, "blocked_writes_total")
            return ToolMessage(
                content=(
                    f"Blocked write_file for '{file_name}'. "
                    "Please modify the existing source file directly instead of "
                    "creating a temporary verification file."
                ),
                tool_call_id=tool_call_id,
                status="error",
            )

        current_round_writes = int(write_counts.get(path, 0))
        if current_round_writes >= self.max_writes_per_file_per_round:
            self._increment_counter(state, "blocked_writes_total")
            return ToolMessage(
                content=(
                    f"Blocked {tool_name} for '{path}'. "
                    "This file has already been written in the current round. "
                    "Please merge edits into one patch and retry in the next round."
                ),
                tool_call_id=tool_call_id,
                status="error",
            )

        current_total_writes = int(write_totals.get(path, 0))
        if (
            self.max_writes_per_file_total > 0
            and current_total_writes >= self.max_writes_per_file_total
        ):
            self._increment_counter(state, "blocked_writes_total")
            return ToolMessage(
                content=(
                    f"Blocked {tool_name} for '{path}'. "
                    "This file already reached the total write limit for this run. "
                    "Please consolidate remaining edits into one planned patch."
                ),
                tool_call_id=tool_call_id,
                status="error",
            )

        is_small_edit = False
        if tool_name == "edit_file":
            total_edit_calls = int(edit_totals.get(path, 0))
            if total_edit_calls >= self.max_edit_calls_per_file_total:
                self._increment_counter(state, "blocked_writes_total")
                return ToolMessage(
                    content=(
                        f"Blocked edit_file for '{path}'. "
                        "This file already reached the edit_file limit for this run. "
                        "Please read the full file and apply one consolidated update."
                    ),
                    tool_call_id=tool_call_id,
                    status="error",
                )

            old_string = args.get("old_string")
            new_string = args.get("new_string")
            if isinstance(old_string, str) and isinstance(new_string, str):
                edit_span = max(len(old_string), len(new_string))
                is_small_edit = edit_span < self.small_edit_char_threshold

            if is_small_edit:
                total_small_edits = int(small_edit_totals.get(path, 0))
                if total_small_edits >= self.max_small_edits_per_file_total:
                    self._increment_counter(state, "blocked_writes_total")
                    self._increment_counter(state, "blocked_fragmented_edits_total")
                    return ToolMessage(
                        content=(
                            f"Blocked fragmented edit_file for '{path}'. "
                            "Too many small incremental edits were detected. "
                            "Please read the file once and submit one merged write."
                        ),
                        tool_call_id=tool_call_id,
                        status="error",
                    )

        if tool_name == "write_file":
            content = args.get("content")
            if isinstance(content, str):
                content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
                if write_hashes.get(path) == content_hash:
                    self._increment_counter(state, "noop_writes_total")
                    return ToolMessage(
                        content=(
                            f"Skipped write_file for '{path}' because the content is "
                            "identical to the last write in this round."
                        ),
                        tool_call_id=tool_call_id,
                    )
                write_hashes[path] = content_hash

        before_content = await self._aread_file_content(request, path)
        result = await handler(request)
        after_content = await self._aread_file_content(request, path)
        metadata = self._build_file_diff_metadata(
            tool_name=tool_name,
            file_path=path,
            before=before_content,
            after=after_content,
        )
        if metadata is not None:
            result = self._attach_diff_metadata(result, metadata)

        write_counts[path] = current_round_writes + 1
        write_totals[path] = int(write_totals.get(path, 0)) + 1

        if tool_name == "edit_file":
            edit_totals[path] = int(edit_totals.get(path, 0)) + 1
            if is_small_edit:
                small_edit_totals[path] = int(small_edit_totals.get(path, 0)) + 1

        state["write_counts_in_round"] = write_counts
        state["write_content_hashes_in_round"] = write_hashes
        state["writes_per_file_total"] = write_totals
        state["edit_calls_per_file_total"] = edit_totals
        state["small_edit_calls_per_file_total"] = small_edit_totals

        return result
