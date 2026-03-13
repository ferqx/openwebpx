from __future__ import annotations

import json
from typing import Any

BIND_ALL_HOST = "0.0.0.0"  # nosec B104


def parse_package_json(raw_output: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(raw_output)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def detect_package_manager_from_package_json(
    package_json: dict[str, Any] | None,
) -> str | None:
    if isinstance(package_json, dict):
        pm_raw = package_json.get("packageManager")
        if isinstance(pm_raw, str):
            normalized = pm_raw.strip().lower()
            for manager in ("pnpm", "yarn", "npm"):
                if normalized.startswith(f"{manager}@"):
                    return manager
    return None


def lockfile_checks() -> list[tuple[str, str]]:
    return [
        (
            "pnpm",
            "[ -f pnpm.lock ] || [ -f pnpm-lock.yaml ] || [ -f pnpm-lock.yml ]",
        ),
        ("yarn", "[ -f yarn.lock ]"),
        (
            "npm",
            "[ -f npm.lock ] || [ -f package-lock.json ] || [ -f npm-shrinkwrap.json ]",
        ),
    ]


def has_workspace_protocol(package_json: dict[str, Any] | None) -> bool:
    if not isinstance(package_json, dict):
        return False
    dependency_sections = (
        "dependencies",
        "devDependencies",
        "peerDependencies",
        "optionalDependencies",
    )
    for section_name in dependency_sections:
        section = package_json.get(section_name)
        if not isinstance(section, dict):
            continue
        for value in section.values():
            if isinstance(value, str) and value.strip().startswith("workspace:"):
                return True
    return False


def resolve_start_script(package_json: dict[str, Any]) -> str | None:
    scripts = package_json.get("scripts")
    if not isinstance(scripts, dict):
        return None
    for name in ("dev", "start", "preview"):
        if isinstance(scripts.get(name), str):
            return name
    return None


def detect_framework(package_json: dict[str, Any]) -> str:
    dependencies: dict[str, Any] = {}
    for key in ("dependencies", "devDependencies"):
        section = package_json.get(key)
        if isinstance(section, dict):
            dependencies.update(section)

    if "next" in dependencies:
        return "next"
    if "nuxt" in dependencies:
        return "nuxt"
    if "react-scripts" in dependencies:
        return "cra"
    if "vite" in dependencies:
        return "vite"
    if "astro" in dependencies:
        return "astro"
    return "unknown"


def build_start_command(
    *,
    package_manager: str,
    start_script: str,
    framework: str,
    port: int,
) -> str:
    base = f"{package_manager} run {start_script}"
    if framework == "next":
        return f"{base} -- --hostname {BIND_ALL_HOST} --port {port}"
    if framework in {"vite", "nuxt", "astro"}:
        return f"{base} -- --host {BIND_ALL_HOST} --port {port}"
    return base


def resolve_package_manager_spec(
    *,
    package_manager: str,
    package_json: dict[str, Any] | None,
) -> str:
    if not isinstance(package_json, dict):
        return f"{package_manager}@latest"
    raw = package_json.get("packageManager")
    if isinstance(raw, str):
        normalized = raw.strip()
        if normalized.lower().startswith(f"{package_manager}@"):
            return normalized
    return f"{package_manager}@latest"


def strict_package_manager_reason(
    *,
    detected_manager: str,
    package_json: dict[str, Any] | None,
) -> str | None:
    strict_manager_declared = False
    if isinstance(package_json, dict):
        pm_raw = package_json.get("packageManager")
        if isinstance(pm_raw, str):
            normalized = pm_raw.strip().lower()
            strict_manager_declared = normalized.startswith(f"{detected_manager}@")
    if strict_manager_declared:
        return "package.json#packageManager"
    if has_workspace_protocol(package_json):
        return "workspace protocol dependencies"
    return None


def collect_port_bindings_from_attrs(attrs: dict[str, Any]) -> dict[str, list[int]]:
    ports = attrs.get("NetworkSettings", {}).get("Ports", {})
    bindings: dict[str, list[int]] = {}
    if not isinstance(ports, dict):
        return bindings

    for container_port, host_mappings in ports.items():
        if not isinstance(host_mappings, list):
            continue
        host_ports: list[int] = []
        for mapping in host_mappings:
            if not isinstance(mapping, dict):
                continue
            port_raw = mapping.get("HostPort")
            if isinstance(port_raw, str) and port_raw.isdigit():
                host_ports.append(int(port_raw))
        if host_ports:
            bindings[container_port] = host_ports
    return bindings


def build_preview_urls(
    bindings: dict[str, list[int]], *, healthcheck_path: str
) -> list[str]:
    urls: list[str] = []
    for host_ports in bindings.values():
        for host_port in host_ports:
            urls.append(f"http://127.0.0.1:{host_port}{healthcheck_path}")
    return sorted(set(urls))


def extract_error_lines(logs: str) -> list[str]:
    keywords = (
        "error",
        "exception",
        "traceback",
        "failed",
        "vite",
        "syntaxerror",
        "unhandled",
        "eaddrinuse",
    )
    lines: list[str] = []
    for raw in logs.splitlines():
        line = raw.strip()
        if not line:
            continue
        if any(word in line.lower() for word in keywords):
            lines.append(line)
    return lines[:12]


def build_diagnostic_message(status: dict[str, Any]) -> str | None:
    if not status.get("app_detected"):
        return None

    alerts: list[str] = []
    startup_error = status.get("startup_error")
    if isinstance(startup_error, str) and startup_error.strip():
        alerts.append("startup_error")

    if not status.get("service_running"):
        alerts.append("service_not_running")

    probes = status.get("preview_probes")
    probe_values = list(probes.values()) if isinstance(probes, dict) else []
    if probe_values and all(str(v).startswith("error:") for v in probe_values):
        alerts.append("preview_unreachable")

    error_lines = status.get("error_lines")
    if isinstance(error_lines, list) and error_lines:
        alerts.append("runtime_errors_in_logs")

    if not alerts:
        return None

    preview_lines = []
    if isinstance(probes, dict):
        for url, result in probes.items():
            preview_lines.append(f"- {url} -> {result}")

    log_excerpt = ""
    if isinstance(error_lines, list) and error_lines:
        log_excerpt = "\n".join(f"- {line}" for line in error_lines[:8])
    elif isinstance(status.get("log_tail"), str):
        tail = str(status["log_tail"]).strip()
        if tail:
            log_excerpt = tail[-1200:]

    return (
        "[Runtime Diagnostics]\n"
        "Web app sandbox runtime check found issues that require fixing in this run.\n\n"
        f"Detected issues: {', '.join(alerts)}\n"
        f"Framework: {status.get('framework')}\n"
        f"Package manager: {status.get('package_manager')}\n"
        f"Start script: {status.get('start_script')}\n"
        f"Start command: {status.get('start_command')}\n"
        f"Service running: {status.get('service_running')}\n"
        f"Service PID: {status.get('service_pid')}\n"
        "Preview probes:\n"
        f"{chr(10).join(preview_lines) if preview_lines else '- no mapped preview URL'}\n\n"
        "Error excerpt:\n"
        f"{log_excerpt or '- no logs captured'}\n\n"
        "Action required: inspect code/build/runtime config, fix the root cause, "
        "then rerun the service and verify preview URL returns 2xx/3xx."
    )
