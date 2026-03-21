# 系统架构与设计

## 1. 技术栈
- **前端框架**: React 19 + TypeScript
- **构建工具**: Vite + Tailwind CSS 4
- **组件库**: 基于 Shadcn UI (Radix UI) 深度封装
- **状态管理**: 基于 Context API 的分层设计 (ThreadProvider, StreamProvider)
- **AI 交互**: Vercel AI SDK + LangGraph SDK
- **沙箱技术**: CodeSandbox Nodebox (@codesandbox/nodebox)
- **路由**: React Router DOM 7

## 2. 核心路由与页面
- `/` (Portal): 门户页面，包含任务创建面板和任务列表。
- `/tasks/:id` (Task Detail): 任务详情页面，主要的 AI 对话和工具展示入口。
- `/apps/:id` (App Chat): 应用对话页。
- `/oauth/scm/callback`: SCM 授权回调页面。

## 3. 业务组件设计
项目遵循 **Container -> Business Component -> UI Component -> Hooks** 的分层原则。

- **src/pages/**: 路由容器，负责初始状态加载和路由分发。
- **src/business/**: 领域特定业务逻辑组件 (如 `thread-chat/` 处理对话 UI, `portal/` 处理门户面板)。
- **src/components/ui/**: 基础 UI 库，严禁包含业务代码。
- **src/hooks/**: 跨组件复用的业务逻辑钩子 (如 `use-thread-chat.ts`)。

## 4. 数据流与 Provider 协作
- **Auth Provider**: 全局认证状态与用户信息。
- **Thread Provider**: 线程元数据加载、线程状态维护 (starting / running / completed / stopped)。
- **Stream Provider**: 对接后端的流式数据协议，处理消息块 (Chunks) 解析与展示。

## 5. 状态转换逻辑
1. 门户创建任务 -> 后端返回 `thread_id`。
2. 跳转 `/tasks/:thread_id` -> 加载线程元数据。
3. 进入会话逻辑 -> `StreamProvider` 订阅流，实时更新消息列表。
4. 运行中操作 -> 发起 `POST /cancel` (thread 级) 触发后台停止，前端流中断。
