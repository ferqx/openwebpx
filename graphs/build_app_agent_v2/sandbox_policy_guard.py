"""Centralized sandbox policy guards for command and path restrictions."""

from __future__ import annotations

import posixpath
import re
import shlex
from pathlib import PurePosixPath

from deepagents.backends.utils import validate_path

_DANGEROUS_GIT_COMMAND_PATTERNS = (
    re.compile(r"\bgit\s+reset\s+--hard\b", re.IGNORECASE),
    re.compile(r"\bgit\s+clean\b[^\n;]*\s-f", re.IGNORECASE),
    re.compile(r"\bgit\s+push\b[^\n;]*\s--force(?:-with-lease)?\b", re.IGNORECASE),
    re.compile(r"\bgit\s+update-ref\b", re.IGNORECASE),
    re.compile(r"\bgit\s+rebase\b[^\n;]*\s--onto\b", re.IGNORECASE),
)
_GIT_DIR_WRITE_HINTS = (
    " >",
    ">>",
    "rm ",
    "mv ",
    "cp ",
    "touch ",
    "install ",
    "tee ",
    "truncate ",
    "sed -i",
    "perl -i",
)
_DANGEROUS_RM_GLOB_TARGETS = {"*", ".*", "..", "../", "/"}
_SCM_AUTH_LOGIN_PATTERNS = (
    re.compile(r"\bglab\s+auth\s+login\b", re.IGNORECASE),
    re.compile(r"\bgh\s+auth\s+login\b", re.IGNORECASE),
)


def resolve_sandbox_patch_path(
    raw_path: str,
    *,
    workspace_root: str = "/workspace",
) -> str:
    """Resolve and validate patch path within sandbox workspace."""
    candidate = raw_path.strip()
    if not candidate:
        raise ValueError("Patch path is empty.")
    if candidate.startswith("/"):
        raise ValueError(
            f"Absolute patch path '{raw_path}' is not allowed. "
            f"Use a relative path under '{workspace_root}'."
        )

    joined = str(PurePosixPath(workspace_root).joinpath(candidate))
    normalized = posixpath.normpath(joined)
    if normalized != workspace_root and not normalized.startswith(f"{workspace_root}/"):
        raise ValueError(
            f"Relative patch path '{raw_path}' escapes '{workspace_root}'."
        )
    if ".git" in PurePosixPath(normalized).parts:
        raise ValueError(f"Patch path '{raw_path}' targets forbidden '.git' directory.")
    return validate_path(normalized)


class SandboxPolicyGuard:
    """Reusable policy guard for sandbox command execution."""

    def __init__(
        self,
        *,
        workspace_root: str = "/workspace",
        max_bulk_file_ops: int = 10,
    ) -> None:
        self.workspace_root = workspace_root
        self.max_bulk_file_ops = max_bulk_file_ops

    def validate_execute_command(self, command: str) -> str | None:
        normalized = command.strip()
        lowered = normalized.lower()

        for pattern in _SCM_AUTH_LOGIN_PATTERNS:
            if pattern.search(normalized):
                return self._policy_violation(
                    reason="interactive SCM CLI login is blocked in sandbox.",
                    safer_alternative=(
                        "use `glab mr create ...` or `gh pr create ...` directly; "
                        "OAuth token is injected automatically from SCM authorization."
                    ),
                )

        for pattern in _DANGEROUS_GIT_COMMAND_PATTERNS:
            if pattern.search(normalized):
                return self._policy_violation(
                    reason=(
                        "dangerous git mutation command is blocked "
                        "(reset --hard / clean -f / force-push / update-ref / rebase --onto)."
                    ),
                    safer_alternative=(
                        "use non-destructive git operations and submit changes "
                        "through PR review."
                    ),
                )

        if self._detect_git_dir_write(lowered):
            return self._policy_violation(
                reason="writing under `.git/` is blocked.",
                safer_alternative=(
                    "edit tracked project files only and avoid touching repository internals."
                ),
            )

        file_op_violation = self._validate_file_ops_policy(normalized)
        if file_op_violation is not None:
            return file_op_violation

        return None

    def _detect_git_dir_write(self, lowered_command: str) -> bool:
        if ".git/" not in lowered_command:
            return False
        return any(hint in lowered_command for hint in _GIT_DIR_WRITE_HINTS)

    def _validate_file_ops_policy(self, command: str) -> str | None:
        for segment in self._split_shell_segments(command):
            violation = self._validate_file_op_segment(segment)
            if violation is not None:
                return violation
        return None

    def _split_shell_segments(self, command: str) -> list[str]:
        segments = re.split(r"(?:&&|\|\||;|\|)", command)
        return [segment.strip() for segment in segments if segment.strip()]

    def _validate_file_op_segment(self, segment: str) -> str | None:
        try:
            tokens = shlex.split(segment)
        except ValueError:
            return None
        if not tokens:
            return None

        if tokens[0] in {"sudo", "env"} and len(tokens) >= 2:
            tokens = tokens[1:]
        if not tokens:
            return None

        if tokens[0] == "apply_patch":
            return self._policy_violation(
                reason=("`apply_patch` is not an executable shell binary in sandbox."),
                safer_alternative=(
                    "invoke the registered `apply_patch` tool directly "
                    "instead of calling it via `execute`."
                ),
            )

        command_name = tokens[0]
        if command_name == "rm":
            return self._validate_rm_tokens(tokens)
        if command_name == "mv":
            return self._validate_mv_tokens(tokens)
        return None

    def _validate_rm_tokens(self, tokens: list[str]) -> str | None:
        options = [token for token in tokens[1:] if token.startswith("-")]
        targets = [token for token in tokens[1:] if not token.startswith("-")]
        if not targets:
            return None

        if self._is_dangerous_rm(options=options, targets=targets):
            return self._policy_violation(
                reason=(
                    "dangerous `rm` pattern is blocked "
                    "(`rm -rf /`, wildcard, or parent-directory targets)."
                ),
                safer_alternative=(
                    "delete specific files under workspace path, "
                    "or use `apply_patch` with `Delete File` for auditable removal."
                ),
            )

        if len(targets) > self.max_bulk_file_ops:
            return self._policy_violation(
                reason=(
                    f"bulk `rm` is blocked when affected targets exceed {self.max_bulk_file_ops}."
                ),
                safer_alternative=(
                    "split deletions into smaller batches, "
                    "or use `apply_patch` `Delete File` operations."
                ),
            )

        path_violation = self._validate_paths_in_workspace(targets)
        if path_violation is not None:
            return path_violation

        return None

    def _validate_mv_tokens(self, tokens: list[str]) -> str | None:
        operands = [token for token in tokens[1:] if not token.startswith("-")]
        if len(operands) < 2:
            return None

        source_count = len(operands) - 1
        if source_count > self.max_bulk_file_ops:
            return self._policy_violation(
                reason=(
                    f"bulk `mv` is blocked when affected sources exceed {self.max_bulk_file_ops}."
                ),
                safer_alternative=(
                    "split rename operations into smaller batches, "
                    "or use `apply_patch` `Move to` for auditable renames."
                ),
            )

        path_violation = self._validate_paths_in_workspace(operands)
        if path_violation is not None:
            return path_violation

        return None

    def _is_dangerous_rm(self, *, options: list[str], targets: list[str]) -> bool:
        option_blob = "".join(options)
        recursive_force = "-rf" in option_blob or (
            "-r" in option_blob and "-f" in option_blob
        )
        if not recursive_force:
            return False
        for target in targets:
            normalized = target.strip()
            if normalized in _DANGEROUS_RM_GLOB_TARGETS:
                return True
            if normalized.startswith("../"):
                return True
        return False

    def _validate_paths_in_workspace(self, paths: list[str]) -> str | None:
        for path in paths:
            candidate = path.strip()
            if not candidate:
                continue
            if candidate.startswith("/") and (
                candidate != self.workspace_root
                and not candidate.startswith(f"{self.workspace_root}/")
            ):
                return self._policy_violation(
                    reason=(
                        f"file operation path '{candidate}' is outside '{self.workspace_root}'."
                    ),
                    safer_alternative=(
                        f"run file operations only under '{self.workspace_root}'."
                    ),
                )
            if candidate == ".." or candidate.startswith("../"):
                return self._policy_violation(
                    reason=(
                        f"file operation path '{candidate}' may escape '{self.workspace_root}'."
                    ),
                    safer_alternative=(
                        "use normalized workspace-relative paths (for example `app/main.py`)."
                    ),
                )
        return None

    def _policy_violation(self, *, reason: str, safer_alternative: str) -> str:
        return f"Policy blocked: {reason} Safe alternative: {safer_alternative}"
