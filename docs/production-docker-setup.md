# Production Docker Setup

Use the production compose file for a non-reloading deployment:

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

## Docker-backed sandbox requirement

OpenWebPX can create per-thread sandbox containers through `DockerMiddleware`.
When the main API service itself runs in Docker, that container must be able to
talk to the host Docker daemon.

Required service configuration:

```yaml
services:
  aegra:
    environment:
      - DOCKER_HOST=unix:///var/run/docker.sock
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
```

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
4. Recreate the service after manifest changes:

```bash
docker compose -f docker-compose.prod.yml up -d --build --force-recreate aegra
```
