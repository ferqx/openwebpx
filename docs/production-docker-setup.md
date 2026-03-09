# Production Docker Setup

Use the production compose file for a non-reloading deployment:

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

## Docker-backed sandbox requirement

OpenWebPX can create per-thread sandbox containers through `DockerMiddleware`.
When the main API service itself runs in Docker, that container must be able to
talk to the host Docker daemon.

Langfuse follows the same networking rule: do not use `localhost` unless
Langfuse runs inside the same container. In Docker deployments, configure
`LANGFUSE_BASE_URL` with either `http://host.docker.internal:3000` for a host
service or `http://<service-name>:3000` for another container.

Required service configuration:

```yaml
services:
  aegra:
    environment:
      - DOCKER_HOST=unix:///var/run/docker.sock
    user: "${AEGRA_DOCKER_USER:-0:0}"
    group_add:
      - "${DOCKER_GID}"
    extra_hosts:
      - "host.docker.internal:host-gateway"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
```

Default behavior:

1. `AEGRA_DOCKER_USER=0:0` keeps the service running as `root`, which is the most
   reliable choice on macOS Docker Desktop because `/var/run/docker.sock` is often
   exposed as `root:root` with `srw-rw----` permissions.
2. `DOCKER_GID` is still accepted for Linux hosts where the socket is group-writable
   and you want to run the service as a non-root user.

Linux non-root option:

```bash
export DOCKER_GID=$(stat -c '%g' /var/run/docker.sock)
export AEGRA_DOCKER_USER=app
```

Or write the same value into `.env` before starting the stack.

Without that socket mount, environment bootstrap fails with errors similar to:

```text
Docker is not available.
```

## Validation

After the stack starts, verify Docker access from inside the API container:

```bash
docker compose -f docker-compose.prod.yml exec aegra python -c "import docker; print(docker.from_env().ping())"
```

Expected output:

```text
True
```

If this fails:

1. Confirm the host Docker daemon is running.
2. Confirm `/var/run/docker.sock` exists on the host.
3. Confirm the `aegra` container has the socket mounted and `DOCKER_HOST` set.
4. If running non-root on Linux, confirm the socket is group-writable and the `aegra`
   container was started with the host Docker socket group id.
5. On macOS Docker Desktop, prefer `AEGRA_DOCKER_USER=0:0`.
6. Recreate the service after manifest changes:

```bash
docker compose -f docker-compose.prod.yml up -d --build --force-recreate aegra
```
