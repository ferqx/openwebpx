# AI 智能体模块 (Agents)

## 简介
AI 智能体模块是 OpenWebPX 的大脑，基于 LangGraph 构建。该模块定义了一系列具备状态管理、工具调用和中间件能力的图模型。核心智能体 `build_app_agent_v3`（位于 `graphs/build_app_agent_v3/`）专门用于处理应用构建、代码补丁生成及运行时自愈等复杂工程任务。

## 功能详情
- **build_app_agent_v3**:
  - **全自动构建**: 从空仓库或现有项目开始，自动识别框架并编写核心代码。
  - **补丁协议 (Patch Protocol)**: 不直接覆写文件，而是生成 `SEARCH/REPLACE` 格式的补丁，确保文件修改的精确性和最小副作用。
  - **上下文注入**: 自动将当前仓库的文件树（File Tree）和运行时诊断信息（Diagnostic Message）注入 Prompt。
  - **思维链路 (Think Tool)**: 支持开启思维链工具（`ThinkToolMiddleware`），使模型在采取行动前进行显式推理。
- **重试机制 (Retries)**:
  - 通过 `ModelRetryMiddleware` 实现自动重试，应对大模型常见的输出格式错误或网络波动。
  - 针对文件补丁应用失败（`PATCH_APPLY_ERROR`），模型会自动获得详细的失败原因并自动修正补丁范围。

## 技术实现
- **补丁协议 (Patch Protocol)**:
  - 实现于 `patch_filesystem_middleware.py`。
  - 采用特定的 `*** Update File: <path>` 语法，强制要求 `<search>` 块必须与文件现有内容**精确匹配**（包括空白字符和缩进）。
  - 支持 `Add`, `Update`, `Delete` 三种原子文件操作。
- **中间件栈 (Middleware Stack)**:
  - `ModelRetryMiddleware`: 模型重试控制。
  - `DockerMiddleware`: 容器环境绑定。
  - `SummarizationMiddleware`: 对话历史长文本摘要，防止 Token 溢出。
  - `PatchFilesystemMiddleware`: 严格的文件操作校验。
  - `SkillsMiddleware`: 智能体技能发现与执行。
- **上下文策略**: `RepositoryContextPromptBuilder` 动态生成当前工作区的快照，包括已映射的预览 URL 和端口绑定信息。

## 性能/质量指标
- **稳定性**: 递归深度默认限制为 1000 回合（`recursion_limit`），具备长任务执行能力。
- **精准度**: 通过严格匹配的补丁协议，从根本上杜绝了大模型修改代码时常见的“随机幻觉”或截断代码问题。
- **模型支持**: 深度对齐 `deepseek-chat` 模型，同时通过 `init_chat_model` 支持灵活切换 OpenAI 或 Anthropic 模型。

## 维护建议
- **补丁重试策略**: 若 Agent 频繁陷入补丁匹配失败（SEARCH 块不匹配），建议增加文件读取次数，以获取最新的文件上下文。
- **Token 控制**: 监控 `SummarizationMiddleware` 的触发阈值，在极大型项目中可适当调低 `trigger` 以保持上下文精简。
- **Prompt 迭代**: 核心提示词位于 `prompts.py`，重大逻辑变更需通过 `build_system_prompt` 进行版本化更新。
