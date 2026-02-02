
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from docker.errors import DockerException, NotFound
from src.sandbox.docker import DockerSandbox

@pytest.fixture
def mock_docker_client():
    client = MagicMock()
    return client

@pytest.fixture
def mock_container():
    container = MagicMock()
    # Setup default return values for container attributes/methods
    container.short_id = "123456"
    return container

@pytest.mark.asyncio
async def test_sandbox_initialization(mock_docker_client):
    sandbox = DockerSandbox(client=mock_docker_client)
    assert sandbox._client == mock_docker_client
    assert sandbox._container is None

@pytest.mark.asyncio
async def test_sandbox_start(mock_docker_client, mock_container):
    sandbox = DockerSandbox(client=mock_docker_client)
    mock_docker_client.containers.run.return_value = mock_container
    
    await sandbox.start()
    
    mock_docker_client.containers.run.assert_called_once_with(
        sandbox.image,
        detach=True,
        tty=True,
        cpu_quota=sandbox.cpu_quota,
        mem_limit=sandbox.mem_limit
    )
    assert sandbox._container == mock_container

@pytest.mark.asyncio
async def test_sandbox_stop(mock_docker_client, mock_container):
    sandbox = DockerSandbox(client=mock_docker_client)
    sandbox._container = mock_container
    
    await sandbox.stop()
    
    mock_container.stop.assert_called_once()
    mock_container.remove.assert_called_once()
    assert sandbox._container is None

@pytest.mark.asyncio
async def test_sandbox_stop_not_found(mock_docker_client, mock_container):
    sandbox = DockerSandbox(client=mock_docker_client)
    sandbox._container = mock_container
    
    mock_container.stop.side_effect = NotFound("Container not found")
    
    await sandbox.stop()
    
    # Should handle exception gracefully
    assert sandbox._container is None

@pytest.mark.asyncio
async def test_sandbox_execute(mock_docker_client, mock_container):
    sandbox = DockerSandbox(client=mock_docker_client)
    sandbox._container = mock_container
    
    # exec_run returns (exit_code, (stdout_bytes, stderr_bytes))
    mock_container.exec_run.return_value = (0, (b"output", b""))
    
    exit_code, stdout, stderr = await sandbox.execute("echo test")
    
    assert exit_code == 0
    assert stdout == "output"
    assert stderr == ""
    mock_container.exec_run.assert_called_once_with("echo test", demux=True)

@pytest.mark.asyncio
async def test_sandbox_execute_no_container(mock_docker_client):
    sandbox = DockerSandbox(client=mock_docker_client)
    
    with pytest.raises(RuntimeError, match="Sandbox not started"):
        await sandbox.execute("echo test")
