# Sandbox Module

This module provides a sandbox environment for executing code safely. Currently, it supports a Docker-based sandbox.

## DockerSandbox

The `DockerSandbox` class implements the **`Sandbox`** interface using Docker containers.

### Requirements

- Docker Engine must be installed and running on the host system.
- The user running the application must have permissions to access the Docker daemon (e.g., be in the `docker` group).

### Usage

```python
import asyncio
from src.sandbox.docker import DockerSandbox

async def main():
    # Initialize sandbox with a specific image (default is python:3.12-slim)
    sandbox = DockerSandbox(image="python:3.12-slim")
    
    try:
        # Start the container
        await sandbox.start()
        
        # Execute a command
        exit_code, stdout, stderr = await sandbox.execute("echo 'Hello World'")
        print(f"Output: {stdout}")
        
    finally:
        # cleanup (stop and remove container)
        await sandbox.stop()

if __name__ == "__main__":
    asyncio.run(main())
```

### Configuration

You can configure the sandbox with the following parameters:

- `image`: The Docker image to use (default: `python:3.12-slim`).
- `cpu_quota`: CPU quota in microseconds (default: `50000` which is 0.5 CPU).
- `mem_limit`: Memory limit (default: `512m`).
