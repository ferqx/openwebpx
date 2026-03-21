# 核心业务 Hooks 解析

本项目采用了大量的自定义 Hooks 来分离 UI 与复杂的业务状态（如 AI 消息处理、SCM 授权、环境引导等）。

## 1. 对话流处理 (`src/hooks/`)

### `useThreadChat`
- **定位**: 任务详情页的核心对话逻辑。
- **职责**:
  - 对原始 LangGraph 消息进行规格化 (`normalizeThreadChatMessages`)。
  - 处理环境初始化 (`useThreadEnvironmentBootstrap`)。
  - 管理提交状态与错误重试。
  - 维护乐观更新 (Optimistic UI) 逻辑。
- **依赖**: `ThreadProvider`, `StreamProvider`。

### `useThreadEnvironmentBootstrap`
- **定位**: 任务启动前的环境拉取与准备。
- **职责**:
  - 监控 `starting` 状态的消息。
  - 封装环境初始化的各阶段显示文本。
  - 触发重置初始化逻辑。

### `useThreadChatTurnState`
- **定位**: 会话回合管理。
- **职责**:
  - 记录并恢复失败的消息回合。
  - 追踪每轮对话的消耗量。

## 2. 门户与 SCM 逻辑 (`src/hooks/`)

### `usePortalPageController`
- **定位**: 门户页面的总控 Hook。
- **职责**:
  - 统一协调 SCM 连接、仓库列表、任务列表的加载顺序。
  - 处理 SCM 授权弹窗的唤起逻辑。

### `usePortalScmConnections`
- **定位**: SCM 授权状态管理器。
- **职责**:
  - 对接后端 `/integrations/scm/connections`。
  - 封装授权、取消授权、连接探测的异步状态。

## 3. 设计模式与最佳实践
- **Ref 引用机制**: 关键的闭包参数（如回调函数）通过 `useRef` 保持引用，避免 `useEffect` 的不必要重运行。
- **工具函数抽离**: 将纯逻辑计算抽离至同名的 `utils.ts` 文件（如 `thread-chat-utils.ts`），以便于编写单元测试。
- **状态规格化**: 在数据进入 UI 渲染前进行规格化转换，确保 UI 组件不需要感知后端复杂的嵌套数据结构。
