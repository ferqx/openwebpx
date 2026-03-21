# Docker 基础设施模块 (Infrastructure)

## 简介
Docker 基础设施模块负责管理 Agent 执行任务所需的沙箱环境。该模块通过 `DockerMiddleware` 与 Docker Daemon 交互，确保每个 Agent 会话都在一个隔离、安全且功能完备的容器中运行。

## 功能详情
- **沙箱隔离**: 每个线程（Thread）绑定一个独立的容器实例，实现进程级和文件系统的强隔离。
- **镜像预装工具链**:
  - **基础语言**: Python 3.12, Node.js 20。
  - **包管理器**: `pnpm` (物理安装), `npm`, `yarn`。
  - **测试与审计**: `pytest`, `pytest-asyncio`, `ruff`。
  - **进程管理**: `pm2`。
  - **系统工具**: `git`, `curl`, `jq`, `ripgrep` (rg), `gcc` 等。
- **生命周期管理**: 自动创建、启动、恢复以及延迟销毁容器（默认 30 分钟不活动后停止）。

## 技术实现
- **镜像定义**: `deployments/docker/Dockerfile.agent` 基于 Alpine 3.20 构建，采用“物理安装”策略替代 Corepack 动态拉取，以确保在无网/隔离环境下的稳定性。
- **环境变量控制**:
  - `NPM_CONFIG_PREFIX=/usr/local`: 确保全局安装的二进制文件直接进入系统 PATH。
  - `PYTHONUNBUFFERED=1`: 保证日志实时输出。
- **容器引导协议**: `middleware/docker.py` 在容器启动后自动执行 SCM 环境注入、仓库同步、依赖探测及服务拉起。

## 性能/质量指标
- **启动延迟**: 在已有镜像情况下，容器就绪时间小于 2 秒。
- **稳健性**: 修复了旧版中 `corepack` 在 Alpine 镜像下由于网络隔离导致的引导失败问题。

## 维护建议
- **镜像重建**: 修改 `Dockerfile.agent` 后，执行 `docker build --no-cache -t sandbox-agent:latest -f deployments/docker/Dockerfile.agent .`。
- **磁盘清理**: 定期运行 `docker system prune` 或清理长期未活动的沙箱容器。
