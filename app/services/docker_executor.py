from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx

from app.services.docker_bootstrap import (
    build_service_launch_command,
    build_tail_logs_command,
    install_command_for_manager,
    service_pid_check_command,
)


def is_service_running(
    *,
    exec_fn: Callable[[Any, str], tuple[int, str]],
    container: Any,
    service_pid_path: str,
) -> tuple[bool, str | None]:
    code, output = exec_fn(container, service_pid_check_command(service_pid_path))
    if code == 0:
        return True, output.strip() or None
    return False, None


def install_dependencies(
    *,
    exec_fn: Callable[[Any, str], tuple[int, str]],
    exec_stream_fn: Callable[[Any, str, Callable[[str], None] | None], tuple[int, str]],
    report_progress: Callable[[Any, str, str, str], None],
    container: Any,
    package_manager: str,
    reporter: Callable[[str, str, str], None] | None,
) -> tuple[bool, str | None]:
    has_node_modules, _ = exec_fn(container, "[ -d node_modules ]")
    if has_node_modules == 0:
        report_progress(
            reporter,
            "bootstrap",
            "info",
            "检测到 node_modules，跳过依赖安装。",
        )
        return True, None

    install_cmd = install_command_for_manager(package_manager)
    report_progress(
        reporter,
        "bootstrap",
        "info",
        f"开始安装依赖：{install_cmd}",
    )
    code, output = exec_stream_fn(
        container,
        install_cmd,
        (
            lambda line: report_progress(
                reporter,
                "bootstrap",
                "info",
                f"[deps] {line}",
            )
        )
        if reporter is not None
        else None,
    )
    if code != 0:
        return False, f"Dependency install failed ({install_cmd}):\n{output[-3000:]}"
    report_progress(reporter, "bootstrap", "info", "依赖安装完成。")
    return True, None


def tail_service_logs(
    *,
    exec_fn: Callable[[Any, str], tuple[int, str]],
    container: Any,
    service_log_path: str,
    lines: int = 120,
) -> str:
    _, output = exec_fn(
        container,
        build_tail_logs_command(service_log_path, lines=lines),
    )
    return output


def start_service(
    *,
    exec_fn: Callable[[Any, str, dict[str, str] | None], tuple[int, str]],
    report_progress: Callable[[Any, str, str, str], None],
    is_service_running_fn: Callable[[], tuple[bool, str | None]],
    tail_service_logs_fn: Callable[[int], str],
    container: Any,
    run_cmd: str,
    service_log_path: str,
    service_pid_path: str,
    port: int,
    startup_wait_seconds: float,
    reporter: Callable[[str, str, str], None] | None,
    path_env: str,
    bind_all_host: str,
) -> tuple[bool, str | None]:
    report_progress(reporter, "bootstrap", "info", f"启动服务：{run_cmd}")
    env = {
        "HOST": bind_all_host,
        "PORT": str(port),
        "CI": "1",
        "PATH": path_env,
    }
    launch_cmd = build_service_launch_command(
        run_cmd=run_cmd,
        service_log_path=service_log_path,
        service_pid_path=service_pid_path,
    )
    code, output = exec_fn(container, launch_cmd, env)
    if code != 0:
        return False, f"Failed to start service ({run_cmd}):\n{output[-3000:]}"

    time.sleep(max(startup_wait_seconds, 0.5))
    running, pid = is_service_running_fn()
    if not running:
        logs = tail_service_logs_fn(120)
        for line in logs.splitlines()[-24:]:
            cleaned = line.strip()
            if not cleaned:
                continue
            report_progress(reporter, "bootstrap", "warning", f"[service] {cleaned}")
        return False, f"Service exited immediately after start.\n{logs[-3000:]}"

    report_progress(
        reporter, "bootstrap", "info", f"服务已启动，pid={pid or 'unknown'}"
    )
    return True, None


def probe_preview_urls(urls: list[str]) -> dict[str, str]:
    probe: dict[str, str] = {}
    if not urls:
        return probe

    with httpx.Client(timeout=2.5, follow_redirects=True) as client:
        for url in urls[:8]:
            try:
                response = client.get(url)
                probe[url] = f"{response.status_code}"
            except Exception as exc:  # noqa: BLE001
                probe[url] = f"error:{type(exc).__name__}"
    return probe
