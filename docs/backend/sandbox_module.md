# 隔离沙箱模块 (Sandbox)

## 简介
隔离沙箱模块（主要实现在 `middleware/docker.py` 和 `app/services/docker_runtime.py`）是 OpenWebPX 的核心运行环境管理层。它通过为每一个 LangGraph 线程绑定一个独立的 Docker 容器，确保了代码执行的安全隔离和运行时环境的持久化，实现了“一个对话一个工作区”的无缝体验。

## 功能详情
- **Thread-to-Container 映射**: 系统自动为每个 `thread_id` 维护并持久化一个唯一的 `container_id`。只要线程未删除，跨会话的代码修改和环境状态都会在对应容器中保留。
- **Git 自动同步**:
  - 根据线程元数据（`repo`, `branch`, `provider`），沙箱在初始化时会自动执行 `clone` 或 `fetch/checkout`。
  - 支持向容器内注入受控的 SCM 凭据，允许 Agent 在容器内直接执行原生 `git` 操作。
- **Web 环境自动初始化**:
  - **Node.js 智能检测**: 自动识别 `package.json` 及包管理器（npm, yarn, pnpm）。
  - **Corepack 集成**: 缺失特定版本的 pnpm/yarn 时，沙箱会自动通过 Corepack 下载并激活。
  - **依赖安装与启动**: 自动化执行 `install` 并在后台拉起开发服务器（如 Vite, Next.js）。
- **运行时诊断与自愈**:
  - 实时监控服务端口，通过 HTTP 探测确定 Web 应用是否真正可用。
  - 收集容器日志并提取错误行，将启动/运行错误作为 `SystemMessage` 反馈给 Agent。

## 技术实现
- **容器生命周期管理**:
  - **懒加载机制**: 只有在真正需要执行命令或预览时才通过 `DockerClient` 初始化容器，减少闲置线程的资源占用。
  - **延迟停机 (Stop Delay)**: 默认保留 30 分钟。若此期间无活动，容器会自动转入 `stop` 状态以释放内存，直到下次对话时被秒级拉起。
- **环境隔离**:
  - 容器内默认使用非特权用户运行命令。
  - 工作目录固定在 `/workspace`，所有宿主机文件操作仅限此目录。
- **状态流转**: `DockerState` 类持久化了容器 ID、同步签名（`repo_sync_signature`）及服务引导状态。

## 性能/质量指标
- **启动延迟**:
  - **冷启动**: 依赖网络拉取代码及 `npm install`，受网络影响大。
  - **热启动**: 已存在容器的恢复通常在 1-2 秒内完成。
- **资源控制**: 默认通过 `tail -f /dev/null` 维持长连接，内存占用极低。

## 维护建议
- **镜像预热**: 建议在生产环境中预拉取 `sandbox-agent:latest` 镜像以消除冷启动时的拉取等待。
- **磁盘管理**: 线程被物理删除时，沙箱会触发 `on.threads.delete` 钩子强制销毁容器，但需定期检查 `docker system prune` 释放宿主机磁盘。
- **网络策略**: 若容器需拉取私有 npm 包或内部 API，请确保宿主机防火墙允许容器访问对应的内网段。
