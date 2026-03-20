# Docker 基础设施层 (Docker Infra)

## 简介
Docker 基础设施层（主要实现在 `backends/docker.py` 和 `app/services/docker_executor.py`）是 OpenWebPX 与底层虚拟化资源的交互层。它封装了所有容器操作指令，为上层业务提供一致的 API，用于管理容器生命周期、资源配额及运行时状态。

## 功能详情
- **容器生命周期管理**:
  - 支持容器的 `create`, `start`, `stop`, `remove` 及 `exec`。
  - 支持文件系统的双向传输（`upload` / `download`），实现宿主机与沙箱间的高效代码流转。
- **资源配额控制**:
  - 支持通过环境变量灵活控制 CPU 和内存限制。
  - 通过 `docker-py` 的底层参数（如 `mem_limit`, `cpu_quota`）实现容器级隔离。
- **运行期诊断**:
  - **端口映射发现**: 自动发现容器内监听的动态端口，并将其映射为可供外部预览的 URL。
  - **日志追踪 (Log Tailing)**: 实时提取容器内特定路径（如 `agent-web.log`）的输出。
  - **状态探活**: 通过 `kill -0` 等原子操作探测容器内进程存活状况。

## 技术实现
- **Backend 协议**: 定义了 `SandboxBackendProtocol`，确保上层 Agent 工具链能以统一接口与 Docker、Local 或 K8s 后端交互。
- **执行器模式**: `app/services/docker_executor.py` 将常见的运维指令（如安装依赖、启动服务）封装为可重用的服务函数，内置了超时处理和流式输出逻辑。
- **端口绑定解析**: 核心逻辑位于 `app/services/docker_runtime.py`，通过解析 Docker 容器的 `NetworkSettings.Ports` 自动生成本地可访问的访问地址。

## 性能/质量指标
- **隔离性**: 强制要求每个容器拥有独立的网络栈（可通过配置连接特定 Docker Network）。
- **稳定性**: 使用 `backoff` 重试机制应对 Docker Daemon 在高负载下的瞬时响应延迟。
- **透明度**: 通过结构化的 `service_status` 字典，将容器底层信息（如 `Container ID`）完全透出，便于开发期调试。

## 维护建议
- **镜像版本控制**: 建议在生产部署时指定固定的 `SANDBOX_IMAGE_TAG`，防止 `latest` 标签带来的环境不确定性。
- **磁盘清理**: 容器产生的临时文件和 `node_modules` 可能会占用大量磁盘，需配合 SCM 清理机制定期运行 `docker container prune` 和 `docker volume prune`。
- **安全加固**: 尽量避免在容器内授予 Root 权限，建议在 Dockerfile 中通过 `USER` 指令锁定非特权账户运行 Agent 任务。
