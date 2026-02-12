"""DockerBackend: Sandbox backend using docker-py for containerized execution.

This backend assumes a Docker container already exists and is identified by a
container ID stored in runtime state. It provides file operations and command
execution within that container.

The container lifecycle (creation, cleanup) is managed by DockerMiddleware.
"""

from __future__ import annotations

import asyncio
import logging
import shlex
import time
from pathlib import Path
from typing import TYPE_CHECKING

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
    """Sandbox backend that runs commands in an existing Docker container.

    This backend expects a container ID to be present in runtime state under
    the key "docker_container_id". It will use that container for all operations.
    If the container ID is missing or invalid, operations will fail.

    The backend does NOT create or destroy containers; that responsibility lies
    with the DockerMiddleware.

    Attributes:
        runtime: ToolRuntime instance for accessing state.
        workdir: Working directory inside the container (default: /workspace).
        client: Docker client instance.
    """

    def __init__(
        self,
        runtime: ToolRuntime,
        *,
        workdir: str = "/workspace",
    ) -> None:
        """Initialize DockerBackend.

        Args:
            runtime: ToolRuntime instance providing state access.
            workdir: Working directory inside the container.
            **kwargs: Ignored (for compatibility).
        """
        super().__init__()
        self.runtime = runtime
        self.workdir = workdir
        self._client: docker.DockerClient | None = None
        self._container: Container | None = None

    @property
    def client(self) -> docker.DockerClient:
        """Lazy-loaded Docker client."""
        if self._client is None:
            try:
                self._client = docker.from_env()
            except DockerException as e:
                logger.error("Failed to initialize Docker client: %s", e)
                raise RuntimeError(
                    "Docker is not available. Please ensure Docker is installed and running."
                ) from e
        return self._client

    @property
    def container(self) -> Container:
        """Get the Docker container from runtime state.

        Returns:
            The Docker container object.

        Raises:
            RuntimeError: If container ID is missing or container not found.
        """
        if self._container is not None:
            return self._container

        state = self.runtime.state
        container_id = state.get("container_id")
        if not container_id:
            raise RuntimeError(
                "Docker container ID not found in runtime state. "
                "Ensure DockerMiddleware has created a container."
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
        """Unique identifier for the sandbox backend instance."""
        return f"docker:{self.container.id}"

    def execute(self, command: str) -> ExecuteResponse:
        """Execute a command in the Docker container.

        Args:
            command: Shell command to execute.

        Returns:
            ExecuteResponse with combined stdout/stderr output and exit code.
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
        """Async version of execute."""
        return await asyncio.to_thread(self.execute, command)

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        """Upload multiple files to the container.

        Uses docker cp to copy files into the container.

        Args:
            files: List of (path, content) tuples.

        Returns:
            List of FileUploadResponse objects.
        """
        container = self.container
        responses: list[FileUploadResponse] = []
        for path, content in files:
            try:
                # Ensure parent directory exists
                dir_path = Path(path).parent
                if dir_path != Path():
                    self.execute(f"mkdir -p {shlex.quote(str(dir_path))}")

                # Create tar archive in memory
                import io
                import tarfile

                tar_stream = io.BytesIO()
                with tarfile.open(fileobj=tar_stream, mode="w") as tar:
                    tarinfo = tarfile.TarInfo(name=Path(path).name)
                    tarinfo.size = len(content)
                    tarinfo.mtime = int(time.time())
                    tar.addfile(tarinfo, io.BytesIO(content))
                tar_stream.seek(0)

                # Use put_archive to extract into container
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
        """Async version of upload_files."""
        return await asyncio.to_thread(self.upload_files, files)

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        """Download multiple files from the container.

        Uses docker cp to copy files from the container.

        Args:
            paths: List of file paths to download.

        Returns:
            List of FileDownloadResponse objects.
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
        """Async version of download_files."""
        return await asyncio.to_thread(self.download_files, paths)
