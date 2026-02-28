"""用于沙箱生命周期和运行时诊断的Docker中间件。

该中间件确保每个线程都有一个Docker容器，并持续将Web应用运行时健康状况反馈给代理，包括：
- 基于Node的Web项目的自动引导/安装/启动
- 从Docker端口映射发现预览URL
- HTTP探测结果
- 将启动/日志/运行时错误注入为SystemMessage以实现自我修复
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import shlex
import time
from collections.abc import Callable
from contextlib import suppress
from pathlib import PurePosixPath
from typing import Any, cast
from urllib.parse import quote, urlparse

import docker
import httpx
from docker.errors import DockerException, NotFound
from docker.models.containers import Container
from langchain.agents.middleware.types import AgentMiddleware, AgentState, hook_config
from langchain_core.messages import AIMessage
from sqlalchemy import select

logger = logging.getLogger(__name__)
# 沙盒内服务必须监听全接口，才能通过 Docker 端口映射被宿主机预览访问。
BIND_ALL_HOST = "0.0.0.0"  # nosec B104
DEFAULT_WEB_SANDBOX_IMAGE = "node:20-bookworm"
DEFAULT_WEB_SANDBOX_CONTAINER_PORT = 3000


class DockerState(AgentState):
    """由DockerMiddleware在线程的多个回合间持久化的状态。"""

    container_id: str | None  # Docker容器ID
    service_status: dict[str, Any] | None  # 服务运行状态信息
    service_bootstrapped: bool | None  # 服务是否已完成引导
    service_restart_count: int | None  # 服务重启次数计数
    last_diagnostic_fingerprint: str | None  # 上次诊断信息的指纹（用于去重）
    repo_sync_signature: str | None  # 最近一次仓库同步签名（容器+仓库+分支）
    repo_sync_success: bool | None  # 最近一次仓库同步是否成功
    repo_sync_error: str | None  # 最近一次仓库同步错误


class ContainerDestroyedError(RuntimeError):
    """线程绑定容器已销毁，当前会话应直接结束。"""


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

    def _restore_container_if_needed(
        self, container: Container, *, container_id: str
    ) -> None:
        """若容器非 running，则尝试恢复。

        目标是保证线程已绑定容器在新一轮对话开始时可继续复用。
        """
        with suppress(DockerException):
            container.reload()

        status = str(getattr(container, "status", "") or "").lower()
        if status == "running":
            return

        try:
            if status == "paused":
                container.unpause()
            else:
                container.start()
            container.reload()
        except NotFound as exc:
            raise ContainerDestroyedError(
                "当前线程绑定的容器已销毁，请重新创建线程以启动新的容器服务。"
            ) from exc
        except DockerException as exc:
            raise RuntimeError(
                f"Failed to start existing container '{container_id}': {exc}"
            ) from exc

        restored_status = str(getattr(container, "status", "") or "").lower()
        if restored_status != "running":
            raise RuntimeError(
                f"Failed to restore container '{container_id}', current status: {restored_status or 'unknown'}"
            )

    def _ensure_container(self, state: DockerState) -> str:
        # 优先复用已有容器，保证同一 thread 在多轮会话中上下文连续。
        container_id: str | None = state.get("container_id")
        if container_id:
            try:
                container = self.client.containers.get(container_id)
                self._restore_container_if_needed(container, container_id=container_id)
                return cast("str", container_id)
            except NotFound:
                raise ContainerDestroyedError(
                    "当前线程绑定的容器已销毁，请重新创建线程以启动新的容器服务。"
                ) from None

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

    def _destroy_container(self, container_id: str) -> tuple[bool, str | None]:
        """销毁线程绑定容器。"""
        try:
            container = self.client.containers.get(container_id)
            container.remove(force=True)
            return True, None
        except NotFound:
            return True, None
        except DockerException as exc:
            return False, str(exc)

    def _persist_thread_container_mapping(
        self,
        *,
        runtime: Any,
        container_id: str,
    ) -> None:
        """将 thread_id -> container_id 映射持久化到 runtime.store。"""
        if runtime is None:
            return

        config = getattr(runtime, "config", None)
        store = getattr(runtime, "store", None)
        if not isinstance(config, dict) or store is None:
            return

        configurable = config.get("configurable")
        if not isinstance(configurable, dict):
            return

        thread_id = configurable.get("thread_id")
        if not isinstance(thread_id, str) or not thread_id.strip():
            return

        try:
            store.put(
                ("docker_backend", "thread_container"),
                thread_id.strip(),
                {"container_id": container_id},
            )
        except Exception:  # pragma: no cover - 非关键路径
            logger.debug(
                "Failed to persist thread/container mapping for thread %s",
                thread_id,
            )

    def _extract_thread_id(self, runtime: Any) -> str | None:
        """从 runtime.config 提取 thread_id。"""
        config = getattr(runtime, "config", None)
        if not isinstance(config, dict):
            return None

        configurable = config.get("configurable")
        if not isinstance(configurable, dict):
            return None

        thread_id = configurable.get("thread_id")
        if isinstance(thread_id, str) and thread_id.strip():
            return thread_id.strip()
        return None

    async def _aload_thread_repo_binding(self, runtime: Any) -> dict[str, str] | None:
        """读取线程仓库绑定信息（repo/branch/provider 等）。"""
        thread_id = self._extract_thread_id(runtime)
        if not thread_id:
            return None

        try:
            from aegra_api.core.orm import Thread as ThreadORM
            from aegra_api.core.orm import _get_session_maker
        except Exception:  # pragma: no cover - 容错路径
            return None

        session_maker = _get_session_maker()
        async with session_maker() as session:
            thread = await session.scalar(
                select(ThreadORM).where(ThreadORM.thread_id == thread_id)
            )

        if thread is None:
            return None

        metadata = (
            thread.metadata_json if isinstance(thread.metadata_json, dict) else {}
        )
        repo = str(metadata.get("repo") or "").strip()
        if not repo or repo in {"未绑定仓库", "none", "null"}:
            return None

        provider_raw = str(metadata.get("provider") or "").strip().lower()
        if provider_raw == "github":
            provider = "github"
        elif provider_raw in {"gitlab", "gitlab_enterprise"}:
            provider = "gitlab"
        else:
            return None

        branch = str(metadata.get("branch") or "main").strip() or "main"
        gitlab_base_url = str(metadata.get("gitlab_base_url") or "").strip()
        github_auth_mode = str(metadata.get("github_auth_mode") or "").strip().lower()

        return {
            "thread_id": thread_id,
            "user_id": str(thread.user_id),
            "provider": provider,
            "repo": repo,
            "branch": branch,
            "gitlab_base_url": gitlab_base_url,
            "github_auth_mode": github_auth_mode,
        }

    def _build_repo_remote_urls(
        self,
        *,
        provider: str,
        repo: str,
        token: str,
        gitlab_base_url: str | None,
    ) -> tuple[str, str]:
        """构建公开 remote URL 与临时鉴权 URL。"""
        if provider == "github":
            public_url = f"https://github.com/{repo}.git"
            username = "x-access-token"
        else:
            from app.routers.scm import _normalize_gitlab_base_url

            normalized_base = _normalize_gitlab_base_url(gitlab_base_url)
            public_url = f"{normalized_base.rstrip('/')}/{repo}.git"
            username = "oauth2"

        parsed = urlparse(public_url)
        token_escaped = quote(token, safe="")
        auth_netloc = f"{username}:{token_escaped}@{parsed.netloc}"
        auth_url = f"{parsed.scheme}://{auth_netloc}{parsed.path}"
        if parsed.query:
            auth_url = f"{auth_url}?{parsed.query}"
        return public_url, auth_url

    def _sanitize_repo_sync_error(self, output: str, token: str) -> str:
        """清理错误输出里的敏感 token。"""
        cleaned = output or ""
        if token:
            cleaned = cleaned.replace(token, "***")
            escaped = quote(token, safe="")
            if escaped:
                cleaned = cleaned.replace(escaped, "***")
        return cleaned[-4000:]

    def _report_progress(
        self,
        reporter: Callable[[str, str, str], None] | None,
        *,
        stage: str,
        level: str,
        message: str,
    ) -> None:
        if reporter is None:
            return

        normalized_message = str(message).strip()
        if not normalized_message:
            return

        normalized_level = level.strip().lower() if isinstance(level, str) else "info"
        if normalized_level not in {"info", "warning", "error", "debug"}:
            normalized_level = "info"

        try:
            reporter(stage, normalized_level, normalized_message)
        except Exception:  # pragma: no cover - 非关键链路
            logger.debug("Failed to report bootstrap progress", exc_info=True)

    def _sync_repo_in_container(
        self,
        *,
        container: Container,
        public_url: str,
        auth_url: str,
        branch: str,
        token: str,
        reporter: Callable[[str, str, str], None] | None = None,
    ) -> tuple[bool, str | None]:
        """在容器内执行 clone/fetch/checkout，并在完成后恢复公开 remote。"""
        workdir_q = shlex.quote(self.workdir)
        branch_q = shlex.quote(branch)
        auth_url_q = shlex.quote(auth_url)
        public_url_q = shlex.quote(public_url)
        sync_cmd = (
            "set -e; "
            f"WORKDIR={workdir_q}; "
            f"BRANCH={branch_q}; "
            f"AUTH_URL={auth_url_q}; "
            f"PUBLIC_URL={public_url_q}; "
            'if [ -d "$WORKDIR/.git" ]; then '
            'echo "[git] update existing repository"; '
            'git -C "$WORKDIR" remote set-url origin "$AUTH_URL"; '
            'git -C "$WORKDIR" fetch --depth 1 origin "$BRANCH"; '
            'git -C "$WORKDIR" checkout -B "$BRANCH" FETCH_HEAD; '
            'git -C "$WORKDIR" remote set-url origin "$PUBLIC_URL"; '
            'elif [ -z "$(ls -A "$WORKDIR" 2>/dev/null)" ]; then '
            'echo "[git] clone fresh repository"; '
            'git clone --depth 1 --branch "$BRANCH" "$AUTH_URL" "$WORKDIR"; '
            'git -C "$WORKDIR" remote set-url origin "$PUBLIC_URL"; '
            "else "
            'echo "[git] initialize repository in non-empty directory"; '
            'git -C "$WORKDIR" init; '
            'git -C "$WORKDIR" remote remove origin >/dev/null 2>&1 || true; '
            'git -C "$WORKDIR" remote add origin "$AUTH_URL"; '
            'git -C "$WORKDIR" fetch --depth 1 origin "$BRANCH"; '
            'git -C "$WORKDIR" checkout -B "$BRANCH" FETCH_HEAD; '
            'git -C "$WORKDIR" remote set-url origin "$PUBLIC_URL"; '
            "fi"
        )

        self._report_progress(
            reporter,
            stage="repo",
            level="info",
            message=f"开始拉取仓库分支：{branch}",
        )

        code, output = self._exec_stream(
            container,
            sync_cmd,
            on_output_line=(
                lambda line: self._report_progress(
                    reporter,
                    stage="repo",
                    level="info",
                    message=self._sanitize_repo_sync_error(line, token),
                )
            )
            if reporter is not None
            else None,
        )
        if code == 0:
            self._report_progress(
                reporter,
                stage="repo",
                level="info",
                message="仓库拉取完成。",
            )
            return True, None

        error_message = self._sanitize_repo_sync_error(output, token)
        self._report_progress(
            reporter,
            stage="repo",
            level="error",
            message=f"仓库拉取失败：{error_message}",
        )
        return False, error_message

    async def _maybe_sync_thread_repository(
        self,
        state: DockerState,
        runtime: Any,
        *,
        container_id: str,
        reporter: Callable[[str, str, str], None] | None = None,
    ) -> dict[str, Any] | None:
        """按线程 metadata 自动同步仓库代码到容器工作目录。"""
        binding = await self._aload_thread_repo_binding(runtime)
        if not binding:
            return None

        signature = "|".join(
            [
                container_id,
                binding["provider"],
                binding["repo"],
                binding["branch"],
                binding.get("gitlab_base_url", ""),
                binding.get("github_auth_mode", ""),
            ]
        )
        if (
            state.get("repo_sync_signature") == signature
            and state.get("repo_sync_success") is True
        ):
            return None

        provider = binding["provider"]
        user_id = binding["user_id"]
        gitlab_base_url = binding.get("gitlab_base_url") or None
        github_auth_mode = (
            binding.get("github_auth_mode") if provider == "github" else None
        )
        if github_auth_mode == "":
            github_auth_mode = None

        try:
            from app.routers.scm import _resolve_scm_access_token

            token = await _resolve_scm_access_token(
                user_id=user_id,
                provider=provider,
                gitlab_base_url=gitlab_base_url,
                github_auth_mode=github_auth_mode,
            )
        except Exception as exc:  # noqa: BLE001
            detail = getattr(exc, "detail", None)
            message = (
                str(detail).strip()
                if isinstance(detail, str) and detail.strip()
                else str(exc).strip() or "unknown error"
            )
            return {
                "repo_sync_signature": signature,
                "repo_sync_success": False,
                "repo_sync_error": f"仓库授权不可用：{message}",
            }

        try:
            public_url, auth_url = self._build_repo_remote_urls(
                provider=provider,
                repo=binding["repo"],
                token=token,
                gitlab_base_url=gitlab_base_url,
            )
        except Exception as exc:  # noqa: BLE001
            return {
                "repo_sync_signature": signature,
                "repo_sync_success": False,
                "repo_sync_error": f"构建仓库地址失败：{exc}",
            }

        try:
            container = await asyncio.to_thread(
                self.client.containers.get, container_id
            )
            await asyncio.to_thread(
                lambda: self._restore_container_if_needed(
                    container,
                    container_id=container_id,
                )
            )
        except Exception as exc:  # noqa: BLE001
            return {
                "repo_sync_signature": signature,
                "repo_sync_success": False,
                "repo_sync_error": f"容器不可用，无法同步仓库：{exc}",
            }

        ok, sync_error = await asyncio.to_thread(
            lambda: self._sync_repo_in_container(
                container=container,
                public_url=public_url,
                auth_url=auth_url,
                branch=binding["branch"],
                token=token,
                reporter=reporter,
            )
        )
        if ok:
            return {
                "repo_sync_signature": signature,
                "repo_sync_success": True,
                "repo_sync_error": None,
            }

        return {
            "repo_sync_signature": signature,
            "repo_sync_success": False,
            "repo_sync_error": (
                f"自动同步仓库失败（{binding['repo']}#{binding['branch']}）："
                f"{sync_error or 'unknown error'}"
            ),
            "messages": [
                AIMessage(
                    content=(
                        "[Repo Bootstrap] 自动同步仓库失败，请先修复仓库拉取问题后再继续开发。\n"
                        f"仓库：{binding['repo']}\n"
                        f"分支：{binding['branch']}\n"
                        f"错误：{sync_error or 'unknown error'}"
                    )
                )
            ],
        }

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

    def _exec_stream(
        self,
        container: Container,
        command: str,
        *,
        workdir: str | None = None,
        environment: dict[str, str] | None = None,
        on_output_line: Callable[[str], None] | None = None,
    ) -> tuple[int, str]:
        """以流式方式执行容器命令，并按行回调输出。"""
        api = container.client.api
        exec_create_resp = api.exec_create(
            container.id,
            cmd=["sh", "-lc", command],
            workdir=workdir or self.workdir,
            environment=environment,
        )
        exec_id = exec_create_resp.get("Id")
        if not isinstance(exec_id, str) or not exec_id:
            raise RuntimeError("Failed to create docker exec session")

        stream = api.exec_start(exec_id, stream=True, demux=False)
        output = ""
        pending_line = ""

        for chunk in stream:
            if not chunk:
                continue
            text_chunk = (
                chunk.decode("utf-8", errors="replace")
                if isinstance(chunk, bytes)
                else str(chunk)
            )
            output += text_chunk
            if len(output) > 120000:
                output = output[-120000:]

            if on_output_line is None:
                continue

            pending_line += text_chunk
            while "\n" in pending_line:
                line, pending_line = pending_line.split("\n", 1)
                line = line.rstrip("\r").strip()
                if line:
                    on_output_line(line)

        if on_output_line is not None:
            tail = pending_line.rstrip("\r\n").strip()
            if tail:
                on_output_line(tail)

        inspect = api.exec_inspect(exec_id)
        exit_code = inspect.get("ExitCode")
        if not isinstance(exit_code, int):
            exit_code = 1
        return exit_code, output

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
        # 锁文件强约束：存在锁文件时必须使用对应包管理器，避免误用导致依赖树漂移。
        lockfile_checks: list[tuple[str, str]] = [
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
        for manager, cond in lockfile_checks:
            code, _ = self._exec(container, cond)
            if code == 0:
                return manager

        # 无锁文件时再按可用命令选择，最后兜底 npm。
        for manager in ("pnpm", "yarn", "npm"):
            code, _ = self._exec(container, f"command -v {manager} >/dev/null 2>&1")
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
        self,
        container: Container,
        package_manager: str,
        *,
        reporter: Callable[[str, str, str], None] | None = None,
    ) -> tuple[bool, str | None]:
        has_pm, _ = self._exec(
            container, f"command -v {package_manager} >/dev/null 2>&1"
        )
        if has_pm != 0:
            message = f"Package manager '{package_manager}' is required but not available in container."
            self._report_progress(
                reporter,
                stage="bootstrap",
                level="error",
                message=message,
            )
            return False, message

        # 若 node_modules 已存在则跳过安装，加速增量修复场景。
        has_node_modules, _ = self._exec(container, "[ -d node_modules ]")
        if has_node_modules == 0:
            self._report_progress(
                reporter,
                stage="bootstrap",
                level="info",
                message="检测到 node_modules，跳过依赖安装。",
            )
            return True, None

        install_cmd_by_manager = {
            "pnpm": "pnpm install",
            "yarn": "yarn install",
            "npm": "npm install",
        }
        install_cmd = install_cmd_by_manager.get(package_manager, "npm install")
        self._report_progress(
            reporter,
            stage="bootstrap",
            level="info",
            message=f"开始安装依赖：{install_cmd}",
        )
        code, output = self._exec_stream(
            container,
            install_cmd,
            on_output_line=(
                lambda line: self._report_progress(
                    reporter,
                    stage="bootstrap",
                    level="info",
                    message=f"[deps] {line}",
                )
            )
            if reporter is not None
            else None,
        )
        if code != 0:
            return (
                False,
                f"Dependency install failed ({install_cmd}):\n{output[-3000:]}",
            )
        self._report_progress(
            reporter,
            stage="bootstrap",
            level="info",
            message="依赖安装完成。",
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
        reporter: Callable[[str, str, str], None] | None = None,
    ) -> tuple[bool, str | None]:
        # 启动命令统一后台执行并落日志，便于后续自动诊断与 API 查询。
        run_cmd = self._build_start_command(
            package_manager=package_manager,
            start_script=start_script,
            framework=framework,
            port=port,
        )
        self._report_progress(
            reporter,
            stage="bootstrap",
            level="info",
            message=f"启动服务：{run_cmd}",
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
        running, pid = self._is_service_running(container)
        if not running:
            _, logs = self._exec(
                container,
                f"tail -n 120 {shlex.quote(self.service_log_path)} 2>/dev/null || true",
            )
            for line in logs.splitlines()[-24:]:
                cleaned = line.strip()
                if not cleaned:
                    continue
                self._report_progress(
                    reporter,
                    stage="bootstrap",
                    level="warning",
                    message=f"[service] {cleaned}",
                )
            return False, f"Service exited immediately after start.\n{logs[-3000:]}"
        self._report_progress(
            reporter,
            stage="bootstrap",
            level="info",
            message=f"服务已启动，pid={pid or 'unknown'}",
        )
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
        self,
        state: DockerState,
        container: Container,
        reporter: Callable[[str, str, str], None] | None = None,
    ) -> dict[str, Any]:
        # service_status 是给 agent 与调试 API 共同消费的结构化运行态快照。
        status: dict[str, Any] = {
            "container_id": container.id,  # 容器ID
            "workdir": self.workdir,  # 工作目录
            "repo_sync": {
                "signature": state.get("repo_sync_signature"),
                "success": state.get("repo_sync_success"),
                "error": state.get("repo_sync_error"),
            },  # 仓库自动同步状态
            "app_detected": False,  # 是否检测到应用（package.json）
            "framework": "unknown",  # 检测到的框架（next、vite、cra等）
            "package_manager": None,  # 包管理器（npm、yarn、pnpm）
            "start_script": None,  # 启动脚本名称（dev、start、preview）
            "start_command": None,  # 完整的启动命令
            "service_running": False,  # 服务是否正在运行
            "service_pid": None,  # 服务进程ID
            "dependencies_installed": None,  # 依赖是否已安装
            "startup_attempted": False,  # 是否尝试过启动服务
            "startup_skipped": False,  # 是否跳过启动（例如缺少启动脚本）
            "startup_skip_reason": None,  # 跳过启动原因
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

        installed, install_error = self._install_dependencies(
            container,
            package_manager,
            reporter=reporter,
        )
        status["dependencies_installed"] = installed
        if not installed:
            status["startup_error"] = install_error

        running, pid = self._is_service_running(container)
        status["service_running"] = running
        status["service_pid"] = pid

        if start_script is None:
            # 有 package.json 但缺可执行脚本时，仅跳过启动，不阻断初始化主流程。
            status["startup_skipped"] = True
            status["startup_skip_reason"] = (
                "Found package.json but no runnable script. Expected one of: dev/start/preview."
            )
        else:
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
                    reporter=reporter,
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

    async def ainitialize_environment(
        self,
        *,
        state: DockerState | dict[str, Any] | None = None,
        runtime: Any = None,
        progress_reporter: Callable[[str, str, str], None] | None = None,
    ) -> dict[str, Any]:
        """显式执行线程环境初始化（容器、仓库、依赖/服务）。"""

        current_state = cast("DockerState", dict(state or {}))
        steps: list[dict[str, Any]] = []

        def push_step(
            key: str,
            title: str,
            status: str,
            detail: str | None = None,
        ) -> None:
            step: dict[str, Any] = {
                "key": key,
                "title": title,
                "status": status,
            }
            if detail:
                step["detail"] = detail
            steps.append(step)

        try:
            container_id = await asyncio.to_thread(
                lambda: self._ensure_container(current_state)
            )
        except ContainerDestroyedError as exc:
            push_step("container", "容器创建", "error", str(exc))
            return {
                "success": False,
                "error": str(exc),
                "steps": steps,
                "updates": {},
            }
        except Exception as exc:  # noqa: BLE001
            error_message = f"容器初始化失败：{exc}"
            push_step("container", "容器创建", "error", error_message)
            return {
                "success": False,
                "error": error_message,
                "steps": steps,
                "updates": {},
            }

        self._persist_thread_container_mapping(
            runtime=runtime, container_id=container_id
        )
        push_step("container", "容器创建", "success", f"container={container_id[:12]}")
        self._report_progress(
            progress_reporter,
            stage="container",
            level="info",
            message=f"容器就绪：{container_id[:12]}",
        )

        updates: dict[str, Any] = {
            "container_id": container_id,
            "service_bootstrapped": bool(current_state.get("service_bootstrapped")),
            "service_restart_count": int(
                current_state.get("service_restart_count") or 0
            ),
            "repo_sync_signature": current_state.get("repo_sync_signature"),
            "repo_sync_success": current_state.get("repo_sync_success"),
            "repo_sync_error": current_state.get("repo_sync_error"),
        }
        merged_state = cast("DockerState", {**current_state, **updates})

        binding = (
            await self._aload_thread_repo_binding(runtime)
            if runtime is not None
            else None
        )
        if binding:
            repo_update = await self._maybe_sync_thread_repository(
                state=merged_state,
                runtime=runtime,
                container_id=container_id,
                reporter=progress_reporter,
            )
            if repo_update:
                updates.update(
                    {
                        key: value
                        for key, value in repo_update.items()
                        if key != "messages"
                    }
                )
                merged_state = cast("DockerState", {**merged_state, **updates})

                if updates.get("repo_sync_success") is False:
                    repo_error = str(
                        updates.get("repo_sync_error") or "自动同步仓库失败"
                    )
                    push_step("repo", "拉取代码", "error", repo_error)
                    self._report_progress(
                        progress_reporter,
                        stage="repo",
                        level="error",
                        message=repo_error,
                    )
                    return {
                        "success": False,
                        "error": repo_error,
                        "steps": steps,
                        "updates": updates,
                        "container_id": container_id,
                    }

                push_step(
                    "repo",
                    "拉取代码",
                    "success",
                    f"{binding['repo']}#{binding['branch']}",
                )
            else:
                push_step(
                    "repo",
                    "拉取代码",
                    "success",
                    f"{binding['repo']}#{binding['branch']} 已是最新",
                )
                self._report_progress(
                    progress_reporter,
                    stage="repo",
                    level="info",
                    message="仓库已是最新，无需重复拉取。",
                )
        else:
            push_step("repo", "拉取代码", "skipped", "未绑定仓库，跳过")
            self._report_progress(
                progress_reporter,
                stage="repo",
                level="info",
                message="未绑定仓库，跳过代码拉取。",
            )

        try:
            container = await asyncio.to_thread(
                self.client.containers.get, container_id
            )
            await asyncio.to_thread(
                lambda: self._restore_container_if_needed(
                    container,
                    container_id=container_id,
                )
            )
            runtime_status = await asyncio.to_thread(
                lambda: self._build_runtime_status(
                    merged_state,
                    container,
                    reporter=progress_reporter,
                )
            )
        except Exception as exc:  # noqa: BLE001
            bootstrap_error = f"环境引导失败：{exc}"
            push_step("bootstrap", "下载依赖并启动", "error", bootstrap_error)
            self._report_progress(
                progress_reporter,
                stage="bootstrap",
                level="error",
                message=bootstrap_error,
            )
            return {
                "success": False,
                "error": bootstrap_error,
                "steps": steps,
                "updates": updates,
                "container_id": container_id,
            }

        restart_count = int(updates.get("service_restart_count") or 0)
        if runtime_status.get("startup_attempted"):
            restart_count += 1

        updates["service_restart_count"] = restart_count
        updates["service_status"] = runtime_status
        updates["service_bootstrapped"] = True

        if not runtime_status.get("app_detected"):
            push_step(
                "bootstrap",
                "下载依赖并启动",
                "skipped",
                "未检测到 package.json，跳过依赖安装",
            )
            self._report_progress(
                progress_reporter,
                stage="bootstrap",
                level="info",
                message="未检测到 package.json，跳过依赖安装与启动。",
            )
            return {
                "success": True,
                "steps": steps,
                "updates": updates,
                "container_id": container_id,
                "service_status": runtime_status,
            }

        startup_error = runtime_status.get("startup_error")
        if isinstance(startup_error, str) and startup_error.strip():
            push_step("bootstrap", "下载依赖并启动", "error", startup_error)
            self._report_progress(
                progress_reporter,
                stage="bootstrap",
                level="error",
                message=startup_error,
            )
            return {
                "success": False,
                "error": startup_error,
                "steps": steps,
                "updates": updates,
                "container_id": container_id,
                "service_status": runtime_status,
            }

        startup_skipped = bool(runtime_status.get("startup_skipped"))
        startup_skip_reason = runtime_status.get("startup_skip_reason")
        if startup_skipped:
            skip_detail = (
                startup_skip_reason.strip()
                if isinstance(startup_skip_reason, str) and startup_skip_reason.strip()
                else "未配置可执行启动脚本，已跳过启动。"
            )
            push_step("bootstrap", "下载依赖并启动", "skipped", skip_detail)
            self._report_progress(
                progress_reporter,
                stage="bootstrap",
                level="warning",
                message=skip_detail,
            )
            return {
                "success": True,
                "steps": steps,
                "updates": updates,
                "container_id": container_id,
                "service_status": runtime_status,
            }

        if not runtime_status.get("service_running"):
            service_error = "服务未成功启动，请检查依赖与启动脚本"
            push_step("bootstrap", "下载依赖并启动", "error", service_error)
            self._report_progress(
                progress_reporter,
                stage="bootstrap",
                level="error",
                message=service_error,
            )
            return {
                "success": False,
                "error": service_error,
                "steps": steps,
                "updates": updates,
                "container_id": container_id,
                "service_status": runtime_status,
            }

        package_manager = runtime_status.get("package_manager")
        start_script = runtime_status.get("start_script")
        push_step(
            "bootstrap",
            "下载依赖并启动",
            "success",
            f"{package_manager or 'unknown'} run {start_script or 'dev'}",
        )
        self._report_progress(
            progress_reporter,
            stage="bootstrap",
            level="info",
            message="依赖与服务启动流程已完成。",
        )
        return {
            "success": True,
            "steps": steps,
            "updates": updates,
            "container_id": container_id,
            "service_status": runtime_status,
        }

    async def areset_environment(
        self,
        *,
        state: DockerState | dict[str, Any] | None = None,
        destroy_container: bool = True,
        progress_reporter: Callable[[str, str, str], None] | None = None,
    ) -> dict[str, Any]:
        """重置线程环境状态，可选销毁容器。"""

        current_state = cast("DockerState", dict(state or {}))
        current_container_id = current_state.get("container_id")
        container_id = (
            current_container_id.strip()
            if isinstance(current_container_id, str) and current_container_id.strip()
            else None
        )

        destroyed_container_id: str | None = None
        reset_error: str | None = None

        if destroy_container and container_id:
            self._report_progress(
                progress_reporter,
                stage="container",
                level="info",
                message=f"准备销毁旧容器：{container_id[:12]}",
            )
            destroyed, destroy_error = await asyncio.to_thread(
                lambda: self._destroy_container(container_id)
            )
            if destroyed:
                destroyed_container_id = container_id
                self._report_progress(
                    progress_reporter,
                    stage="container",
                    level="info",
                    message=f"旧容器已销毁：{container_id[:12]}",
                )
            else:
                reset_error = f"销毁旧容器失败：{destroy_error}"
                self._report_progress(
                    progress_reporter,
                    stage="container",
                    level="error",
                    message=reset_error,
                )

        updates: dict[str, Any] = {
            "container_id": None if destroy_container else container_id,
            "service_status": None,
            "service_bootstrapped": False,
            "service_restart_count": 0,
            "last_diagnostic_fingerprint": None,
            "repo_sync_signature": None,
            "repo_sync_success": None,
            "repo_sync_error": None,
        }

        return {
            "success": reset_error is None,
            "error": reset_error,
            "updates": updates,
            "container_id": updates.get("container_id"),
            "destroyed_container_id": destroyed_container_id,
        }

    def _fingerprint(self, text: str) -> str:
        # 用短哈希做幂等键，避免同一错误在每轮都重复注入。
        return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]

    @hook_config(can_jump_to=["end"])
    def before_agent(
        self, state: DockerState, runtime: Any = None
    ) -> dict[str, Any] | None:
        # 在 agent 主循环前确保容器存在，并初始化计数类状态。
        try:
            container_id = self._ensure_container(state)
        except ContainerDestroyedError:
            return {
                "jump_to": "end",
                "messages": [
                    AIMessage(
                        content=(
                            "当前线程绑定的容器已销毁，无法继续本次对话。"
                            "请重新创建线程进行对话。"
                        )
                    )
                ],
            }
        self._persist_thread_container_mapping(
            runtime=runtime, container_id=container_id
        )
        return {
            "container_id": container_id,
            "service_bootstrapped": bool(state.get("service_bootstrapped")),
            "service_restart_count": int(state.get("service_restart_count") or 0),
            "repo_sync_signature": state.get("repo_sync_signature"),
            "repo_sync_success": state.get("repo_sync_success"),
            "repo_sync_error": state.get("repo_sync_error"),
        }

    @hook_config(can_jump_to=["end"])
    async def abefore_agent(
        self, state: DockerState, runtime: Any = None
    ) -> dict[str, Any] | None:
        """异步入口：在容器可用后执行仓库自动同步。"""
        base_update = self.before_agent(state=state, runtime=runtime)
        if base_update is None:
            return None
        if not isinstance(base_update, dict):
            return base_update
        if base_update.get("jump_to") == "end":
            return base_update

        container_id = base_update.get("container_id")
        if not isinstance(container_id, str) or not container_id.strip():
            return base_update

        repo_update = await self._maybe_sync_thread_repository(
            state=state,
            runtime=runtime,
            container_id=container_id.strip(),
        )
        if not repo_update:
            return base_update

        merged = dict(base_update)
        for key, value in repo_update.items():
            if key == "messages" and isinstance(value, list):
                existing_messages = (
                    list(merged.get("messages", []))
                    if isinstance(merged.get("messages"), list)
                    else []
                )
                existing_messages.extend(value)
                merged["messages"] = existing_messages
            else:
                merged[key] = value
        return merged

    def after_agent(self, state: DockerState) -> dict[str, Any] | None:
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


def build_web_sandbox_docker_middleware(**overrides: Any) -> DockerMiddleware:
    """构建统一的 Web 沙盒 Docker 中间件配置。"""

    params: dict[str, Any] = {
        "image": DEFAULT_WEB_SANDBOX_IMAGE,
        "ports": {f"{DEFAULT_WEB_SANDBOX_CONTAINER_PORT}/tcp": None},
        "environment": {"HOST": BIND_ALL_HOST},
        "auto_start_service": True,
        "default_container_port": DEFAULT_WEB_SANDBOX_CONTAINER_PORT,
        "healthcheck_path": "/",
    }
    params.update(overrides)
    return DockerMiddleware(**params)
