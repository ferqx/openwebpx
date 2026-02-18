"""用于沙箱生命周期和运行时诊断的Docker中间件。

该中间件确保每个线程都有一个Docker容器，并持续将Web应用运行时健康状况反馈给代理，包括：
- 基于Node的Web项目的自动引导/安装/启动
- 从Docker端口映射发现预览URL
- HTTP探测结果
- 将启动/日志/运行时错误注入为SystemMessage以实现自我修复
"""

from __future__ import annotations

import hashlib
import json
import logging
import shlex
import time
from contextlib import suppress
from pathlib import PurePosixPath
from typing import Any, cast

import docker
import httpx
from docker.errors import DockerException, NotFound
from docker.models.containers import Container
from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langchain_core.messages import SystemMessage

logger = logging.getLogger(__name__)
# 沙盒内服务必须监听全接口，才能通过 Docker 端口映射被宿主机预览访问。
BIND_ALL_HOST = "0.0.0.0"  # nosec B104


class DockerState(AgentState):
    """由DockerMiddleware在线程的多个回合间持久化的状态。"""

    container_id: str | None  # Docker容器ID
    service_status: dict[str, Any] | None  # 服务运行状态信息
    service_bootstrapped: bool | None  # 服务是否已完成引导
    service_restart_count: int | None  # 服务重启次数计数
    last_diagnostic_fingerprint: str | None  # 上次诊断信息的指纹（用于去重）


class DockerMiddleware(AgentMiddleware):
    """管理Docker沙箱生命周期和Web运行时诊断。

    该中间件为每个线程维护一个容器，并在每次模型调用前，
    尝试确保生成的应用可运行。如果发现运行时问题，
    它们会被注入为SystemMessage，以便代理可以自动修复它们。
    """

    state_schema = DockerState

    def __init__(
        self,
        *,
        image: str = "sandbox-agent",
        workdir: str = "/workspace",
        ports: dict[str, int | None] | None = None,
        auto_start_service: bool = True,
        default_container_port: int = 5173,
        startup_wait_seconds: float = 2.0,
        healthcheck_path: str = "/",
        max_restart_attempts: int = 2,
        service_log_path: str | None = None,
        service_pid_path: str | None = None,
        **container_kwargs: Any,
    ) -> None:
        """初始化DockerMiddleware。

        Args:
            image: Docker镜像名称（默认："sandbox-agent"）。
            workdir: 容器内工作目录（默认："/workspace"）。
            ports: 端口映射字典，格式为 {容器端口: 主机端口}。
            auto_start_service: 是否自动启动检测到的服务（默认：True）。
            default_container_port: 默认容器端口（默认：5173）。
            startup_wait_seconds: 服务启动后等待时间（秒）（默认：2.0）。
            healthcheck_path: 健康检查路径（默认："/"）。
            max_restart_attempts: 最大重启尝试次数（默认：2）。
            service_log_path: 服务日志文件路径（默认：<workdir>/.agent-runtime/agent-web.log）。
            service_pid_path: 服务PID文件路径（默认：<workdir>/.agent-runtime/agent-web.pid）。
            **container_kwargs: 传递给docker容器创建的其他参数。
        """
        self.image = image
        self.workdir = workdir
        self.ports = ports
        self.auto_start_service = auto_start_service
        self.default_container_port = default_container_port
        self.startup_wait_seconds = startup_wait_seconds
        self.healthcheck_path = healthcheck_path
        self.max_restart_attempts = max_restart_attempts
        runtime_dir = f"{self.workdir.rstrip('/')}/.agent-runtime"
        self.service_log_path = service_log_path or f"{runtime_dir}/agent-web.log"
        self.service_pid_path = service_pid_path or f"{runtime_dir}/agent-web.pid"
        self.container_kwargs = container_kwargs
        self._client: docker.DockerClient | None = None

    @property
    def client(self) -> docker.DockerClient:
        # 懒加载 Docker Client：只有真正需要访问容器时才初始化，
        # 避免在纯文本对话场景下产生额外开销。
        if self._client is None:
            try:
                self._client = docker.from_env()
            except DockerException as exc:
                logger.error("Failed to initialize Docker client: %s", exc)
                raise RuntimeError(
                    "Docker is not available. Please ensure Docker is installed and running."
                ) from exc
        return self._client

    def _ensure_container(self, state: DockerState) -> str:
        # 优先复用已有容器，保证同一 thread 在多轮会话中上下文连续。
        container_id: str | None = state.get("container_id")
        if container_id:
            try:
                self.client.containers.get(container_id)
                return cast("str", container_id)
            except NotFound:
                logger.warning("Container %s not found, creating new one", container_id)

        # 仅在容器不存在时创建新容器，并保持常驻进程防止容器自动退出。
        try:
            container = self.client.containers.run(
                self.image,
                command=["tail", "-f", "/dev/null"],
                detach=True,
                working_dir=self.workdir,
                ports=self.ports,
                **self.container_kwargs,
            )
        except DockerException as exc:
            raise RuntimeError(f"Failed to create Docker container: {exc}") from exc

        if not container.id:
            raise RuntimeError("Failed to create Docker container: No ID returned")
        logger.info("Created container %s", container.id)
        return container.id

    def _exec(
        self,
        container: Container,
        command: str,
        *,
        workdir: str | None = None,
        environment: dict[str, str] | None = None,
    ) -> tuple[int, str]:
        # 所有容器内命令统一走 sh -lc，确保 shell 语义一致（变量、重定向、&& 等）。
        result = container.exec_run(
            cmd=["sh", "-lc", command],
            workdir=workdir or self.workdir,
            environment=environment,
        )
        output = result.output.decode("utf-8", errors="replace")
        return result.exit_code, output

    def _read_package_json(self, container: Container) -> dict[str, Any] | None:
        # 用特定退出码区分“文件不存在”和“读取失败”，便于上层判定是否是 Node 项目。
        code, output = self._exec(
            container,
            "if [ -f package.json ]; then cat package.json; else exit 42; fi",
        )
        if code == 42:
            return None
        if code != 0:
            return None
        try:
            payload = json.loads(output)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    def _detect_package_manager(self, container: Container) -> str:
        # 按锁文件优先级判断包管理器，减少 lockfile 与命令不匹配带来的安装失败。
        checks: list[tuple[str, str]] = [
            ("pnpm", "[ -f pnpm-lock.yaml ] || [ -f pnpm-lock.yml ]"),
            ("yarn", "[ -f yarn.lock ]"),
            ("npm", "[ -f package-lock.json ] || [ -f npm-shrinkwrap.json ]"),
            ("npm", "true"),
        ]
        for manager, cond in checks:
            code, _ = self._exec(
                container, f"{cond} && command -v {manager} >/dev/null 2>&1"
            )
            if code == 0:
                return manager
        return "npm"

    def _resolve_start_script(self, package_json: dict[str, Any]) -> str | None:
        # 优先 dev，其次 start/preview，兼容大多数前端项目脚本约定。
        scripts = package_json.get("scripts")
        if not isinstance(scripts, dict):
            return None
        for name in ("dev", "start", "preview"):
            if isinstance(scripts.get(name), str):
                return name
        return None

    def _detect_framework(self, package_json: dict[str, Any]) -> str:
        # 仅做轻量依赖检测：不追求 100% 准确，但用于拼接启动参数足够稳定。
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

    def _build_start_command(
        self,
        *,
        package_manager: str,
        start_script: str,
        framework: str,
        port: int,
    ) -> str:
        # 不同框架对 host/port 参数名称不同，这里做统一策略，保证容器外可访问。
        base = f"{package_manager} run {start_script}"
        if framework == "next":
            return f"{base} -- --hostname {BIND_ALL_HOST} --port {port}"
        if framework in {"vite", "nuxt", "astro"}:
            return f"{base} -- --host {BIND_ALL_HOST} --port {port}"
        return base

    def _install_dependencies(
        self, container: Container, package_manager: str
    ) -> tuple[bool, str | None]:
        # 若 node_modules 已存在则跳过安装，加速增量修复场景。
        has_node_modules, _ = self._exec(container, "[ -d node_modules ]")
        if has_node_modules == 0:
            return True, None

        install_cmd_by_manager = {
            "pnpm": "pnpm install",
            "yarn": "yarn install",
            "npm": "npm install",
        }
        install_cmd = install_cmd_by_manager.get(package_manager, "npm install")
        code, output = self._exec(container, install_cmd)
        if code != 0:
            return (
                False,
                f"Dependency install failed ({install_cmd}):\n{output[-3000:]}",
            )
        return True, None

    def _is_service_running(self, container: Container) -> tuple[bool, str | None]:
        # 通过 PID 文件 + kill -0 判断存活，避免仅靠日志判断“假启动”。
        code, output = self._exec(
            container,
            (
                f"if [ -f {shlex.quote(self.service_pid_path)} ]; then "
                f"PID=$(cat {shlex.quote(self.service_pid_path)}); "
                'if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then echo "$PID"; '
                "else exit 2; fi; "
                "else exit 3; fi"
            ),
        )
        if code == 0:
            return True, output.strip() or None
        return False, None

    def _start_service(
        self,
        container: Container,
        *,
        package_manager: str,
        start_script: str,
        framework: str,
        port: int,
    ) -> tuple[bool, str | None]:
        # 启动命令统一后台执行并落日志，便于后续自动诊断与 API 查询。
        run_cmd = self._build_start_command(
            package_manager=package_manager,
            start_script=start_script,
            framework=framework,
            port=port,
        )
        env = {
            "HOST": BIND_ALL_HOST,
            "PORT": str(port),
            "CI": "1",
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        }
        log_dir = str(PurePosixPath(self.service_log_path).parent)
        pid_dir = str(PurePosixPath(self.service_pid_path).parent)
        launch_cmd = (
            f"mkdir -p {shlex.quote(log_dir)} {shlex.quote(pid_dir)}; "
            f"rm -f {shlex.quote(self.service_pid_path)}; "
            f"nohup {run_cmd} > {shlex.quote(self.service_log_path)} 2>&1 & "
            f"echo $! > {shlex.quote(self.service_pid_path)}; "
            f"cat {shlex.quote(self.service_pid_path)}"
        )
        code, output = self._exec(container, launch_cmd, environment=env)
        if code != 0:
            return False, f"Failed to start service ({run_cmd}):\n{output[-3000:]}"

        # 给进程预留最短启动窗口，随后立即校验是否秒退。
        time.sleep(max(self.startup_wait_seconds, 0.5))
        running, _ = self._is_service_running(container)
        if not running:
            _, logs = self._exec(
                container,
                f"tail -n 120 {shlex.quote(self.service_log_path)} 2>/dev/null || true",
            )
            return False, f"Service exited immediately after start.\n{logs[-3000:]}"
        return True, None

    def _collect_port_bindings(self, container: Container) -> dict[str, list[int]]:
        # 容器状态可能变化，先 reload 再读映射，降低端口信息过期概率。
        with suppress(DockerException):
            container.reload()

        ports = container.attrs.get("NetworkSettings", {}).get("Ports", {})
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

    def _build_preview_urls(self, bindings: dict[str, list[int]]) -> list[str]:
        # 统一使用 localhost 生成预览地址，便于本地开发和上层 UI 直接展示。
        urls: list[str] = []
        for host_ports in bindings.values():
            for host_port in host_ports:
                urls.append(f"http://127.0.0.1:{host_port}{self.healthcheck_path}")
        return sorted(set(urls))

    def _probe_preview_urls(self, urls: list[str]) -> dict[str, str]:
        # 主动 HTTP 探测能快速判断“端口打开但服务不可用”的情况。
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

    def _tail_service_logs(self, container: Container, lines: int = 120) -> str:
        _, output = self._exec(
            container,
            f"tail -n {lines} {shlex.quote(self.service_log_path)} 2>/dev/null || true",
        )
        return output

    def _extract_error_lines(self, logs: str) -> list[str]:
        # 提取关键错误行用于 prompt 注入，避免把完整日志全部塞进上下文。
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

    def _build_runtime_status(
        self, state: DockerState, container: Container
    ) -> dict[str, Any]:
        # service_status 是给 agent 与调试 API 共同消费的结构化运行态快照。
        status: dict[str, Any] = {
            "container_id": container.id,  # 容器ID
            "workdir": self.workdir,  # 工作目录
            "app_detected": False,  # 是否检测到应用（package.json）
            "framework": "unknown",  # 检测到的框架（next、vite、cra等）
            "package_manager": None,  # 包管理器（npm、yarn、pnpm）
            "start_script": None,  # 启动脚本名称（dev、start、preview）
            "start_command": None,  # 完整的启动命令
            "service_running": False,  # 服务是否正在运行
            "service_pid": None,  # 服务进程ID
            "dependencies_installed": None,  # 依赖是否已安装
            "startup_attempted": False,  # 是否尝试过启动服务
            "startup_error": None,  # 启动错误信息
            "preview_urls": [],  # 预览URL列表
            "preview_probes": {},  # URL探测结果
            "port_bindings": {},  # 端口绑定映射
            "log_tail": "",  # 服务日志尾部
            "error_lines": [],  # 错误行提取
        }

        package_json = self._read_package_json(container)
        if package_json is None:
            # 非 Node 项目时仍返回端口和探测信息，方便排查“服务未启动”问题。
            bindings = self._collect_port_bindings(container)
            urls = self._build_preview_urls(bindings)
            status["port_bindings"] = bindings
            status["preview_urls"] = urls
            status["preview_probes"] = self._probe_preview_urls(urls)
            return status

        status["app_detected"] = True
        framework = self._detect_framework(package_json)
        package_manager = self._detect_package_manager(container)
        start_script = self._resolve_start_script(package_json)
        start_command = (
            self._build_start_command(
                package_manager=package_manager,
                start_script=start_script,
                framework=framework,
                port=self.default_container_port,
            )
            if start_script
            else None
        )
        status["framework"] = framework
        status["package_manager"] = package_manager
        status["start_script"] = start_script
        status["start_command"] = start_command

        if start_script is None:
            # 有 package.json 但缺可执行脚本，直接给 agent 明确错误方向。
            status["startup_error"] = (
                "Found package.json but no runnable script. Expected one of: dev/start/preview."
            )
        else:
            installed, install_error = self._install_dependencies(
                container, package_manager
            )
            status["dependencies_installed"] = installed
            if not installed:
                status["startup_error"] = install_error

            running, pid = self._is_service_running(container)
            status["service_running"] = running
            status["service_pid"] = pid

            restart_count = int(state.get("service_restart_count") or 0)
            can_restart = restart_count < self.max_restart_attempts

            if (
                self.auto_start_service
                and installed
                and not running
                and status["startup_error"] is None
                and can_restart
            ):
                # 自动自愈：未运行时尝试拉起服务，但限制最大重启次数避免死循环。
                status["startup_attempted"] = True
                started, start_error = self._start_service(
                    container,
                    package_manager=package_manager,
                    start_script=start_script,
                    framework=framework,
                    port=self.default_container_port,
                )
                if not started:
                    status["startup_error"] = start_error
                running, pid = self._is_service_running(container)
                status["service_running"] = running
                status["service_pid"] = pid

        bindings = self._collect_port_bindings(container)
        urls = self._build_preview_urls(bindings)
        probes = self._probe_preview_urls(urls)
        log_tail = self._tail_service_logs(container)
        error_lines = self._extract_error_lines(log_tail)

        status["port_bindings"] = bindings
        status["preview_urls"] = urls
        status["preview_probes"] = probes
        status["log_tail"] = log_tail[-6000:]
        status["error_lines"] = error_lines
        return status

    def _build_diagnostic_message(self, status: dict[str, Any]) -> str | None:
        # 只在存在 actionable 问题时注入系统消息，避免噪音干扰正常对话。
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
            tail = cast("str", status["log_tail"]).strip()
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

    def _fingerprint(self, text: str) -> str:
        # 用短哈希做幂等键，避免同一错误在每轮都重复注入。
        return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]

    def before_agent(self, state: DockerState, runtime: Any) -> dict[str, Any] | None:  # noqa: ARG002
        # 在 agent 主循环前确保容器存在，并初始化计数类状态。
        container_id = self._ensure_container(state)
        return {
            "container_id": container_id,
            "service_bootstrapped": bool(state.get("service_bootstrapped")),
            "service_restart_count": int(state.get("service_restart_count") or 0),
        }

    def before_model(self, state: DockerState, runtime: Any) -> dict[str, Any] | None:  # noqa: ARG002
        # 每次模型调用前执行运行态扫描，让同一轮推理就能拿到最新故障信息。
        container_id = self._ensure_container(state)
        container = self.client.containers.get(container_id)

        status = self._build_runtime_status(state, container)
        update: dict[str, Any] = {
            "container_id": container_id,
            "service_status": status,
            "service_bootstrapped": bool(status.get("app_detected")),
        }

        if status.get("startup_attempted"):
            update["service_restart_count"] = (
                int(state.get("service_restart_count") or 0) + 1
            )

        diagnostic = self._build_diagnostic_message(status)
        if diagnostic:
            fingerprint = self._fingerprint(diagnostic)
            # 仅在诊断变化时注入消息，避免重复上下文占用。
            if state.get("last_diagnostic_fingerprint") != fingerprint:
                update["messages"] = [SystemMessage(content=diagnostic)]
            update["last_diagnostic_fingerprint"] = fingerprint
        else:
            update["last_diagnostic_fingerprint"] = None

        return update

    def after_agent(self, state: DockerState, runtime: Any) -> dict[str, Any] | None:  # noqa: ARG002
        # 结束时再采样一次，确保外部 API 读取到的是最新运行结果。
        container_id = state.get("container_id")
        if not container_id:
            return None

        try:
            container = self.client.containers.get(container_id)
        except (NotFound, DockerException):
            return None

        status = self._build_runtime_status(state, container)
        return {
            "container_id": container_id,
            "service_status": status,
        }
