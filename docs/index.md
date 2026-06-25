# sandbox-agent 工程文档

欢迎来到 sandbox-agent 项目文档。这是一个高度兼容、自托管的 LangGraph 服务端实现，旨在为 AI 智能体提供安全、受控的沙箱环境和强大的代码处理能力。

## 核心模块
- [AI 智能体 (Agents)](agents_module.md): 智能体逻辑、补丁协议、**性能评测与遥测**。
- [Docker 基础设施 (Infrastructure)](docker_infra_module.md): 沙箱容器管理与**预装工具链**。
- [身份验证 (Authentication)](auth_module.md): 用户会话与**解耦鉴权架构**。
- [沙箱服务 (Sandbox)](sandbox_module.md): 容器执行与引导流程。
- [SCM 模块 (Source Control)](scm_module.md): GitHub/GitLab 集成与令牌管理。

## 开发者快速开始
1. **环境配置**: 复制 `.env.example` 为 `.env` 并配置必要的模型令牌。
2. **构建沙箱**: `docker build -t sandbox-agent:latest -f deployments/docker/Dockerfile.agent .`
3. **运行服务**: `make run`
4. **性能验证**: `make benchmark`

## 工程质量保证
- **自动评估**: 项目内置 Benchmark 系统，通过真实场景测试 Agent 成功率。
- **数据驱动**: 所有工具调用均通过遥测系统持久化，支持深度性能分析。
- **低耦合设计**: 核心组件（数据库、鉴权、配置）均通过抽象层实现，具备极强的环境适配能力。
