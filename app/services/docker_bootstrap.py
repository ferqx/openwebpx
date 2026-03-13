from __future__ import annotations

import shlex
from pathlib import PurePosixPath


def build_corepack_prepare_command(pm_spec: str) -> str:
    return (
        "if command -v corepack >/dev/null 2>&1; then "
        "corepack enable >/dev/null 2>&1 || true; "
        f"corepack prepare {shlex.quote(pm_spec)} --activate; "
        "else exit 127; fi"
    )


def install_command_for_manager(package_manager: str) -> str:
    install_cmd_by_manager = {
        "pnpm": "pnpm install",
        "yarn": "yarn install",
        "npm": "npm install",
    }
    return install_cmd_by_manager.get(package_manager, "npm install")


def service_pid_check_command(service_pid_path: str) -> str:
    quoted = shlex.quote(service_pid_path)
    return (
        f"if [ -f {quoted} ]; then "
        f"PID=$(cat {quoted}); "
        'if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then echo "$PID"; '
        "else exit 2; fi; "
        "else exit 3; fi"
    )


def build_service_launch_command(
    *,
    run_cmd: str,
    service_log_path: str,
    service_pid_path: str,
) -> str:
    log_dir = str(PurePosixPath(service_log_path).parent)
    pid_dir = str(PurePosixPath(service_pid_path).parent)
    return (
        f"mkdir -p {shlex.quote(log_dir)} {shlex.quote(pid_dir)}; "
        f"rm -f {shlex.quote(service_pid_path)}; "
        f"nohup {run_cmd} > {shlex.quote(service_log_path)} 2>&1 & "
        f"echo $! > {shlex.quote(service_pid_path)}; "
        f"cat {shlex.quote(service_pid_path)}"
    )


def build_tail_logs_command(service_log_path: str, *, lines: int = 120) -> str:
    return f"tail -n {lines} {shlex.quote(service_log_path)} 2>/dev/null || true"
