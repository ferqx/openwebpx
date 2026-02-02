import asyncio
import logging
from typing import Optional, Tuple

import docker
from docker.errors import DockerException, NotFound
from docker.models.containers import Container

from src.sandbox.base import Sandbox

logger = logging.getLogger(__name__)


class DockerSandbox(Sandbox):
    """
    Docker-based sandbox environment.
    Uses the docker python library to manage containers.
    """

    def __init__(
        self,
        image: str = "python:3.12-slim",
        cpu_quota: int = 50000,
        mem_limit: str = "512m",
        client: Optional[docker.DockerClient] = None,
    ):
        """
        Initialize the DockerSandbox.

        Args:
            image: Docker image to use.
            cpu_quota: CPU quota (50000 = 0.5 CPU).
            mem_limit: Memory limit (e.g., "512m").
            client: Optional docker client instance.
        """
        self.image = image
        self.cpu_quota = cpu_quota
        self.mem_limit = mem_limit
        self._client = client or docker.from_env()
        self._container: Optional[Container] = None

    async def start(self) -> None:
        """
        Start the sandbox container.
        """
        loop = asyncio.get_running_loop()
        try:
            self._container = await loop.run_in_executor(
                None,
                lambda: self._client.containers.run(
                    self.image,
                    detach=True,
                    tty=True,  # Keep running
                    cpu_quota=self.cpu_quota,
                    mem_limit=self.mem_limit,
                    # Network isolation?
                    # network_mode="none" # Optional: strictly isolate if needed
                ),
            )

            if self._container is None:
                raise DockerException("Failed to start container")

            logger.info(f"Started sandbox container {self._container.short_id}")
        except DockerException as e:
            logger.error(f"Failed to start docker sandbox: {e}")
            raise

    async def stop(self) -> None:
        """
        Stop and remove the sandbox container.
        """
        if self._container:
            loop = asyncio.get_running_loop()
            try:
                # reload to get current status? Not strictly needed for stop/remove usually
                await loop.run_in_executor(
                    None,
                    lambda: (
                        self._container.stop(timeout=1)
                        if self._container is not None
                        else None
                    ),
                )
                await loop.run_in_executor(None, self._container.remove)
                logger.info(
                    f"Stopped and removed sandbox container {self._container.short_id}"
                )
            except NotFound:
                logger.warning("Container not found during stop")
            except DockerException as e:
                logger.error(f"Error stopping container: {e}")
            finally:
                self._container = None

    async def execute(self, cmd: str) -> Tuple[int, str, str]:
        """
        Execute a command in the sandbox.

        Returns:
            (exit_code, stdout, stderr)
        """
        if not self._container:
            raise RuntimeError("Sandbox not started")

        loop = asyncio.get_running_loop()
        try:
            # exec_run with demux=True returns (exit_code, (stdout, stderr))
            result = await loop.run_in_executor(
                None,
                lambda: (
                    self._container.exec_run(cmd, demux=True)
                    if self._container is not None
                    else None
                ),
            )

            if result is None:
                raise DockerException("Failed to execute command in container")

            exit_code, output = result

            # output is (stdout_bytes, stderr_bytes)
            stdout_bytes, stderr_bytes = output

            stdout_str = stdout_bytes.decode("utf-8") if stdout_bytes else ""
            stderr_str = stderr_bytes.decode("utf-8") if stderr_bytes else ""

            return exit_code, stdout_str, stderr_str

        except DockerException as e:
            logger.error(f"Failed to execute command: {e}")
            raise
