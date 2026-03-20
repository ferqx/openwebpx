# OpenWebPX 项目文档索引

欢迎使用 OpenWebPX 项目文档。本项目是一个基于 LangGraph 的高性能 AI Agent 平台，专注于自动化应用构建与代码审查，并提供安全隔离的 Docker 沙箱环境。

## 项目定位
OpenWebPX 旨在为开发者提供一个可私有化部署、安全可控、且与主流 SCM（GitHub/GitLab）深度集成的智能助手。它通过图形化智能体（Graphs）和中间件栈，实现了从需求分析到代码实现、预览及自动化审查的全流程闭环。

## 核心架构图 (Markdown 表述)

```mermaid
graph TD
    A[用户界面/API] --> B[FastAPI 路由层]
    B --> C[Auth 模块]
    B --> D[SCM 模块]
    B --> E[Code Review 模块]

    B --> F[LangGraph 运行时]
    F --> G[build_app_agent_v3]
    F --> H[其他智能体]

    G --> I[Docker 中间件]
    I --> J[Docker 基础设施层]
    J --> K[线程隔离容器 (Sandbox)]

    K --> L[代码工作区 /workspace]
    K --> M[Web 服务运行期]
```

## 模块文档链接

1.  **[认证与授权 (Auth)](auth_module.md)**: 介绍多驱动支持、数据库持久化及 RBAC。
2.  **[隔离沙箱 (Sandbox)](sandbox_module.md)**: 线程与容器映射、Git 同步及环境初始化。
3.  **[SCM 集成 (SCM)](scm_module.md)**: GitHub/GitLab 连接管理与 Token 加密。
4.  **[代码审查 (Code Review)](code_review_module.md)**: Webhook 触发、审查配置及异步任务。
5.  **[AI 智能体 (Agents)](agents_module.md)**: 重点介绍 `build_app_agent_v3` 及补丁协议。
6.  **[Docker 基础设施 (Docker Infra)](docker_infra_module.md)**: 容器生命周期与资源控制。

---
*本文档由 OpenWebPX 自动生成并对齐最新代码实现。*
