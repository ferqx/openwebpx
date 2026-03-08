"""DockerBackend: 使用docker-py进行容器化执行的沙箱后端。

该后端假设Docker容器已存在，并通过运行时状态中存储的容器ID进行标识。
它提供在该容器内的文件操作和命令执行功能。

容器的生命周期（创建、清理）由DockerMiddleware管理。
"""

from __future__ import annotations

import asyncio
import logging
import re
import shlex
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import docker
from deepagents.backends.protocol import (
    ExecuteResponse,
    FileDownloadResponse,
    FileUploadResponse,
)
from deepagents.backends.sandbox import BaseSandbox
from docker.errors import APIError, DockerException, NotFound
from docker.models.containers import Container

if TYPE_CHECKING:
    from langchain.tools import ToolRuntime

logger = logging.getLogger(__name__)
_GLAB_RE = re.compile(r"\bglab\b", re.IGNORECASE)
_GH_RE = re.compile(r"\bgh\b", re.IGNORECASE)
_GLAB_MR_CREATE_RE = re.compile(r"\bglab\s+mr\s+create\b", re.IGNORECASE)
_EXEC_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
_SCM_BASH_ENV = "/etc/profile.d/openwebpx-scm.sh"
_GITLAB_MR_REST_HINT = (
    "create GitLab merge requests via REST API with "
    "`Authorization: Bearer $GITLAB_TOKEN`, for example "
    "`curl -X POST https://gitlab.example.com/api/v4/projects/<numeric-id>/merge_requests "
    "--data-urlencode source_branch=... --data-urlencode target_branch=... "
    '--data-urlencode title=... -H "Authorization: Bearer $GITLAB_TOKEN"`.'
)


def _docker_unavailable_message(exc: DockerException) -> str:
    """返回更可操作的 Docker 不可用诊断信息。"""
    base = "Docker is not available."
    details = str(exc).strip()
    socket_exists = Path("/var/run/docker.sock").exists()
    permission_denied = (
        "PermissionError(13" in details or "Permission denied" in details
    )
    if permission_denied:
        guidance = (
            " The Docker socket is present but this process cannot access it. If "
            "OpenWebPX is running inside Docker, add the service container to the "
            "host Docker socket group, for example via group_add with "
            "DOCKER_GID=$(stat -c '%g' /var/run/docker.sock), and keep "
            "DOCKER_HOST=unix:///var/run/docker.sock."
        )
    elif not socket_exists:
        guidance = (
            " If OpenWebPX is running inside Docker, mount /var/run/docker.sock into "
            "the service container and set DOCKER_HOST=unix:///var/run/docker.sock. "
            "Otherwise ensure Docker is installed and the daemon is running on the host."
        )
    else:
        guidance = (
            " Ensure the Docker daemon is running and that this process can access "
            "/var/run/docker.sock."
        )
    if details:
        return f"{base}{guidance} Original error: {details}"
    return f"{base}{guidance}"


class DockerBackend(BaseSandbox):
    """在现有Docker容器中运行命令的沙箱后端。

    该后端期望运行时状态中存在键为"container_id"的容器ID。
    它将使用该容器进行所有操作。
    如果容器ID缺失或无效，操作将失败。

    该后端不创建或销毁容器；该职责由DockerMiddleware负责。

    Attributes:
        runtime: 用于访问状态的ToolRuntime实例。
        workdir: 容器内的工作目录（默认：/workspace）。
        client: Docker客户端实例。
    """

    def __init__(
        self,
        runtime: ToolRuntime,
        *,
        workdir: str = "/workspace",
    ) -> None:
        """初始化DockerBackend。

        Args:
            runtime: 提供状态访问的ToolRuntime实例。
            workdir: 容器内的工作目录。
            **kwargs: 忽略（用于兼容性）。
        """
        super().__init__()
        self.runtime = runtime
        self.workdir = workdir
        self._client: docker.DockerClient | None = None
        self._container: Container | None = None

    @property
    def client(self) -> docker.DockerClient:
        """延迟加载的Docker客户端。"""
        if self._client is None:
            try:
                self._client = docker.from_env()
            except DockerException as e:
                logger.error("Failed to initialize Docker client: %s", e)
                raise RuntimeError(_docker_unavailable_message(e)) from e
        return self._client

    def _get_thread_id(self) -> str | None:
        """从运行时配置提取 thread_id。"""
        config: Any = getattr(self.runtime, "config", None)
        if not isinstance(config, dict):
            return None
        configurable = config.get("configurable")
        if not isinstance(configurable, dict):
            return None
        thread_id = configurable.get("thread_id")
        if isinstance(thread_id, str) and thread_id.strip():
            return thread_id.strip()
        return None

    def _store_container_mapping(self, *, thread_id: str, container_id: str) -> None:
        """将 thread_id -> container_id 映射持久化到 LangGraph store。"""
        store = getattr(self.runtime, "store", None)
        if store is None:
            return
        try:
            store.put(
                ("docker_backend", "thread_container"),
                thread_id,
                {"container_id": container_id},
            )
        except Exception:  # pragma: no cover - 非关键路径
            logger.debug("Failed to persist container mapping for thread %s", thread_id)

    def _load_container_mapping(self, *, thread_id: str) -> str | None:
        """从 LangGraph store 读取 thread_id -> container_id 映射。"""
        store = getattr(self.runtime, "store", None)
        if store is None:
            return None
        try:
            item = store.get(("docker_backend", "thread_container"), thread_id)
        except Exception:  # pragma: no cover - 非关键路径
            logger.debug("Failed to load container mapping for thread %s", thread_id)
            return None

        value = getattr(item, "value", None) if item is not None else None
        if not isinstance(value, dict):
            return None
        container_id = value.get("container_id")
        if isinstance(container_id, str) and container_id.strip():
            return container_id.strip()
        return None

    @property
    def container(self) -> Container:
        """从运行时状态获取Docker容器。

        Returns:
            Docker容器对象。

        Raises:
            RuntimeError: 如果容器ID缺失或容器未找到。
        """
        if self._container is not None:
            return self._container

        state = self.runtime.state if isinstance(self.runtime.state, dict) else {}
        container_id = state.get("container_id")
        thread_id = self._get_thread_id()

        if isinstance(container_id, str) and container_id.strip():
            container_id = container_id.strip()
            if thread_id:
                self._store_container_mapping(
                    thread_id=thread_id,
                    container_id=container_id,
                )

        if not container_id and thread_id:
            container_id = self._load_container_mapping(thread_id=thread_id)

        if not container_id:
            raise RuntimeError(
                "在运行时状态下未找到 Docker 容器 ID. "
                "确保 DockerMiddleware 已成功创建容器."
            )

        try:
            self._container = self.client.containers.get(container_id)
        except NotFound:
            raise RuntimeError(
                f"Docker container {container_id} not found. It may have been removed."
            ) from None
        except DockerException as e:
            raise RuntimeError(f"Failed to get container {container_id}: {e}") from e

        logger.debug("Using Docker container %s", container_id)
        return self._container

    @property
    def id(self) -> str:
        """沙箱后端实例的唯一标识符。"""
        return f"docker:{self.container.id}"

    def execute(self, command: str) -> ExecuteResponse:
        """在Docker容器中执行命令。

        Args:
            command: 要执行的shell命令。

        Returns:
            包含合并的stdout/stderr输出和退出码的ExecuteResponse。
        """
        environment, token_for_sanitize = self._build_execution_environment()
        cli_auth_error = self._validate_scm_cli_auth(command, environment)
        if cli_auth_error is not None:
            return ExecuteResponse(
                output=f"Error: {cli_auth_error}",
                exit_code=1,
                truncated=False,
            )
        container = self.container
        try:
            exec_result = container.exec_run(
                cmd=["bash", "-lc", command],
                workdir=self.workdir,
                environment=environment,
            )
            output = exec_result.output.decode("utf-8", errors="replace")
            if token_for_sanitize:
                output = output.replace(token_for_sanitize, "***")
            exit_code = exec_result.exit_code
            truncated = False
            if len(output) > 100_000:
                output = output[:100_000] + "\n[Output truncated due to size]"
                truncated = True
            return ExecuteResponse(
                output=output, exit_code=exit_code, truncated=truncated
            )
        except DockerException as e:
            logger.error("Docker exec failed: %s", e)
            return ExecuteResponse(
                output=f"Error executing command in container: {e}",
                exit_code=1,
                truncated=False,
            )

    def _validate_scm_cli_auth(
        self,
        command: str,
        environment: dict[str, str],
    ) -> str | None:
        if _GLAB_MR_CREATE_RE.search(command):
            return (
                "`glab mr create` is disabled in sandbox because GitLab OAuth "
                f"tokens are handled more reliably via REST API; {_GITLAB_MR_REST_HINT}"
            )
        if _GLAB_RE.search(command) and not (
            environment.get("GLAB_TOKEN")
            or environment.get("GITLAB_TOKEN")
            or environment.get("GITLAB_ACCESS_TOKEN")
        ):
            return (
                "SCM authorization unavailable for GitLab CLI command. "
                "Please re-authorize GitLab integration in OpenWebPX; "
                "do not run `glab auth login` in sandbox."
            )
        if _GH_RE.search(command) and not (
            environment.get("GH_TOKEN") or environment.get("GITHUB_TOKEN")
        ):
            return (
                "SCM authorization unavailable for GitHub CLI command. "
                "Please re-authorize GitHub integration in OpenWebPX; "
                "do not run `gh auth login` in sandbox."
            )
        return None

    def _build_execution_environment(self) -> tuple[dict[str, str], str | None]:
        env = {
            "PATH": _EXEC_PATH,
            "SHELL": "/bin/bash",
            "BASH_ENV": _SCM_BASH_ENV,
        }
        token: str | None = None
        context = self._repo_auth_context_from_state()
        identity = self._repo_git_identity_from_state()

        if identity is not None:
            name = identity.get("name", "").strip()
            email = identity.get("email", "").strip().lower()
            if name:
                env["GIT_AUTHOR_NAME"] = name
                env["GIT_COMMITTER_NAME"] = name
            if email:
                env["GIT_AUTHOR_EMAIL"] = email
                env["GIT_COMMITTER_EMAIL"] = email

        if context is not None:
            token = self._resolve_repo_access_token_from_context(context)
            provider = context.get("provider", "").strip().lower()
            if token:
                if provider == "gitlab":
                    gitlab_base = str(context.get("gitlab_base_url") or "").strip()
                    gitlab_host = urlparse(gitlab_base).netloc if gitlab_base else ""
                    if gitlab_host:
                        env["GLAB_HOST"] = gitlab_host
                        env["GITLAB_HOST"] = gitlab_host
                    env["SCM_TOKEN"] = token
                    env["GITLAB_TOKEN"] = token
                    env["GLAB_TOKEN"] = token
                    env["GITLAB_ACCESS_TOKEN"] = token
                elif provider == "github":
                    env["SCM_TOKEN"] = token
                    env["GH_TOKEN"] = token
                    env["GITHUB_TOKEN"] = token

        return env, token

    def _repo_auth_context_from_state(self) -> dict[str, str] | None:
        state = self.runtime.state if isinstance(self.runtime.state, dict) else {}
        raw = state.get("repo_auth_context")
        if not isinstance(raw, dict):
            return None
        user_id = str(raw.get("user_id") or "").strip()
        provider = str(raw.get("provider") or "").strip().lower()
        repo = str(raw.get("repo") or "").strip()
        if not user_id or provider not in {"github", "gitlab"} or not repo:
            return None
        return {
            "user_id": user_id,
            "provider": provider,
            "repo": repo,
            "gitlab_base_url": str(raw.get("gitlab_base_url") or "").strip(),
            "github_auth_mode": str(raw.get("github_auth_mode") or "").strip(),
        }

    def _repo_git_identity_from_state(self) -> dict[str, str] | None:
        state = self.runtime.state if isinstance(self.runtime.state, dict) else {}
        raw = state.get("repo_git_identity")
        if not isinstance(raw, dict):
            return None
        name = str(raw.get("name") or "").strip()
        email = str(raw.get("email") or "").strip().lower()
        if not name and not email:
            return None
        return {"name": name, "email": email}

    def _resolve_repo_access_token_from_context(
        self, context: dict[str, str]
    ) -> str | None:
        try:
            from app.routers.scm import _resolve_scm_access_token
        except Exception:
            return None

        try:
            token = self._run_async_blocking(
                _resolve_scm_access_token(
                    user_id=context["user_id"],
                    provider=context["provider"],
                    gitlab_base_url=context.get("gitlab_base_url") or None,
                    github_auth_mode=context.get("github_auth_mode") or None,
                )
            )
        except Exception:
            return None
        if isinstance(token, str) and token.strip():
            return token.strip()
        return None

    def _run_async_blocking(self, coro: Any) -> Any:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)

        holder: dict[str, Any] = {}
        error_holder: dict[str, BaseException] = {}

        def _runner() -> None:
            try:
                holder["result"] = asyncio.run(coro)
            except BaseException as exc:  # pragma: no cover - fallback path
                error_holder["error"] = exc

        thread = threading.Thread(target=_runner, daemon=True)
        thread.start()
        thread.join()
        if "error" in error_holder:
            raise error_holder["error"]
        return holder.get("result")

    async def aexecute(self, command: str) -> ExecuteResponse:
        """在Docker容器中异步执行命令。

        Args:
            command: 要执行的shell命令。

        Returns:
            ExecuteResponse，包含合并的stdout/stderr输出和退出码。
        """
        return await asyncio.to_thread(self.execute, command)

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        """上传多个文件到容器。

        使用docker cp将文件复制到容器中。

        Args:
            files: (路径, 内容) 元组列表。

        Returns:
            FileUploadResponse对象列表。
        """
        container = self.container
        responses: list[FileUploadResponse] = []
        for path, content in files:
            try:
                # 确保父目录存在
                dir_path = Path(path).parent
                if dir_path != Path():
                    self.execute(f"mkdir -p {shlex.quote(str(dir_path))}")

                # 在内存中创建tar归档
                import io
                import tarfile

                tar_stream = io.BytesIO()
                with tarfile.open(fileobj=tar_stream, mode="w") as tar:
                    tarinfo = tarfile.TarInfo(name=Path(path).name)
                    tarinfo.size = len(content)
                    tarinfo.mtime = int(time.time())
                    tar.addfile(tarinfo, io.BytesIO(content))
                tar_stream.seek(0)

                # 使用put_archive解压到容器中
                container.put_archive(str(Path(path).parent), tar_stream)
                responses.append(FileUploadResponse(path=path, error=None))
            except Exception as e:
                logger.error("Failed to upload file %s: %s", path, e)
                responses.append(
                    FileUploadResponse(path=path, error="permission_denied")
                )
        return responses

    async def aupload_files(
        self, files: list[tuple[str, bytes]]
    ) -> list[FileUploadResponse]:
        """异步上传多个文件到容器。

        使用docker cp将文件复制到容器中。

        Args:
            files: (路径, 内容) 元组列表。

        Returns:
            FileUploadResponse对象列表。
        """
        return await asyncio.to_thread(self.upload_files, files)

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        """从容器下载多个文件。

        使用docker cp从容器复制文件。

        Args:
            paths: 要下载的文件路径列表。

        Returns:
            FileDownloadResponse对象列表。
        """
        container = self.container
        responses: list[FileDownloadResponse] = []
        for path in paths:
            try:
                stream, stat = container.get_archive(path)
                data = b"".join(stream)
                import io
                import tarfile

                tar_stream = io.BytesIO(data)
                with tarfile.open(fileobj=tar_stream, mode="r") as tar:
                    member = tar.next()
                    if member is None:
                        raise FileNotFoundError(f"No file in archive for {path}")
                    file_obj = tar.extractfile(member)
                    if file_obj is None:
                        raise FileNotFoundError(f"Could not extract {path}")
                    content = file_obj.read()
                responses.append(
                    FileDownloadResponse(path=path, content=content, error=None)
                )
            except NotFound:
                responses.append(
                    FileDownloadResponse(
                        path=path, content=None, error="file_not_found"
                    )
                )
            except APIError as e:
                if getattr(e, "status_code", None) == 404:
                    responses.append(
                        FileDownloadResponse(
                            path=path, content=None, error="file_not_found"
                        )
                    )
                    continue
                logger.error("Failed to download file %s: %s", path, e)
                responses.append(
                    FileDownloadResponse(
                        path=path, content=None, error="permission_denied"
                    )
                )
            except FileNotFoundError:
                responses.append(
                    FileDownloadResponse(
                        path=path, content=None, error="file_not_found"
                    )
                )
            except Exception as e:
                logger.error("Failed to download file %s: %s", path, e)
                responses.append(
                    FileDownloadResponse(
                        path=path, content=None, error="permission_denied"
                    )
                )
        return responses

    async def adownload_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        """异步从容器下载多个文件。

        使用docker cp从容器复制文件。

        Args:
            paths: 要下载的文件路径列表。

        Returns:
            FileDownloadResponse对象列表。
        """
        return await asyncio.to_thread(self.download_files, paths)
