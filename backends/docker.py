"""DockerBackend: 使用docker-py进行容器化执行的沙箱后端。

该后端假设Docker容器已存在，并通过运行时状态中存储的容器ID进行标识。
它提供在该容器内的文件操作和命令执行功能。

容器的生命周期（创建、清理）由DockerMiddleware管理。
"""

from __future__ import annotations

import asyncio
import logging
import shlex
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import docker
from deepagents.backends.protocol import (
    ExecuteResponse,
    FileDownloadResponse,
    FileUploadResponse,
)
from deepagents.backends.sandbox import BaseSandbox
from docker.errors import DockerException, NotFound
from docker.models.containers import Container

if TYPE_CHECKING:
    from langchain.tools import ToolRuntime

logger = logging.getLogger(__name__)


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
                raise RuntimeError(
                    "Docker is not available. Please ensure Docker is installed and running."
                ) from e
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
        container = self.container
        try:
            exec_result = container.exec_run(
                cmd=["sh", "-c", command],
                workdir=self.workdir,
                environment={
                    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
                },
            )
            output = exec_result.output.decode("utf-8", errors="replace")
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
