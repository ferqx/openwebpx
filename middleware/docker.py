"""DockerMiddleware: Middleware that creates and manages Docker sandbox containers.

This middleware ensures a Docker container exists for the conversation thread,
stores its ID in runtime state, and cleans it up when appropriate. It does NOT
provide filesystem or execution tools directly; those are provided by
FilesystemMiddleware configured with DockerBackend.

Example:
    ```python
    from deepagents import create_deep_agent
    from deepagents.middleware.filesystem import FilesystemMiddleware
    from agent_server.backends.docker import DockerBackend
    from agent_server.middleware.docker import DockerMiddleware

    # Create agent with Docker sandbox
    agent = create_deep_agent(
        middleware=[
            DockerMiddleware(image="python:3.12-alpine"),
            FilesystemMiddleware(backend=DockerBackend),
        ]
    )
    ```
"""

import logging
from typing import Any, cast

import docker
from docker.errors import DockerException, NotFound
from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langchain.tools import ToolRuntime

logger = logging.getLogger(__name__)


class DockerState(AgentState):
    """
    State schema for DockerMiddleware.
    Stores the Docker container ID associated with the conversation thread.
    """

    container_id: str | None


class DockerMiddleware(AgentMiddleware):
    """Middleware that manages Docker container lifecycle for sandboxed agents.

    This middleware creates a Docker container on the first model call of a
    conversation thread, stores the container ID in runtime state, and ensures
    the container is removed when the conversation ends (if auto_cleanup=True).

    The container runs a long‑living command (`tail -f /dev/null`) to keep it
    alive. All filesystem and execution tools should be backed by a DockerBackend
    that reads the same container ID from runtime state.

    Args:
        image: Docker image to use for the container.
            Default: "python:3.12-alpine"
        workdir: Working directory inside the container.
            Default: "/workspace"
        auto_cleanup: Whether to automatically stop and remove the container
            when the conversation ends (i.e., when the runtime is finalized).
            Default: True
        **container_kwargs: Additional arguments passed to `docker run`
            (e.g., environment variables, volumes, network, etc.).
    """

    state_schema = DockerState

    def __init__(
        self,
        *,
        image: str = "python:3.12-alpine",
        workdir: str = "/workspace",
        auto_cleanup: bool = True,
        **container_kwargs: Any,
    ) -> None:
        """Initialize DockerMiddleware."""
        self.image = image
        self.workdir = workdir
        self.auto_cleanup = auto_cleanup
        self.container_kwargs = container_kwargs
        self._client: docker.DockerClient | None = None

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

    def _ensure_container(self, state: DockerState) -> str:
        """Ensure a container exists for the current runtime.

        If a container ID is already stored in runtime state, verify it exists.
        Otherwise create a new container and store its ID.

        Returns:
            Container ID (string).
        """
        container_id: str | None = state.get("container_id")
        if container_id:
            try:
                self.client.containers.get(container_id)
                logger.debug("Using existing container %s", container_id)
                # container_id is guaranteed to be a non-empty string here
                return cast("str", container_id)
            except NotFound:
                logger.warning("Container %s not found, creating new one", container_id)
                # fall through to create new container

        # Create new container
        logger.info("Creating Docker container from image %s", self.image)
        try:
            container = self.client.containers.run(
                self.image,
                command=["tail", "-f", "/dev/null"],  # keep alive
                detach=True,
                working_dir=self.workdir,
                **self.container_kwargs,
            )

            if not container.id:
                raise RuntimeError("Failed to create Docker container: No ID returned")

            logger.info("Created container %s", container.id)
            return container.id
        except DockerException as e:
            logger.error("Failed to create Docker container: %s", e)
            raise RuntimeError(f"Failed to create Docker container: {e}") from e

    def _cleanup_container(self, runtime: ToolRuntime) -> None:
        """Stop and remove the container associated with this runtime."""
        state = runtime.state
        container_id = state.get("docker_container_id")
        if not container_id:
            return
        try:
            container = self.client.containers.get(container_id)
            container.stop()
            container.remove()
            logger.info("Cleaned up container %s", container_id)
        except NotFound:
            pass
        except DockerException as e:
            logger.warning("Failed to clean up container %s: %s", container_id, e)
        finally:
            # Remove container ID from state
            runtime.state.update({"container_id": None})

    def before_model(self, state: DockerState) -> dict[str, Any]:
        container_id = self._ensure_container(state)

        return {"container_id": container_id}

    def finalize(self, runtime: ToolRuntime) -> None:
        """Clean up container when conversation ends (if auto_cleanup=True)."""
        if self.auto_cleanup:
            self._cleanup_container(runtime)
