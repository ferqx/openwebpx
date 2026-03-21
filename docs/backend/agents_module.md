# AI 智能体模块 (Agents)

## 简介
AI 智能体模块是 OpenWebPX 的大脑，基于 LangGraph 构建。该模块定义了一系列具备状态管理、工具调用和中间件能力的图模型。核心智能体 `build_app_agent_v3`（位于 `graphs/build_app_agent_v3/`）专门用于处理应用构建、代码补丁生成及运行时自愈等复杂工程任务。

## 功能详情
- **build_app_agent_v3**:
  - **全自动构建**: 从空仓库或现有项目开始，自动识别框架并编写核心代码。
  - **补丁协议 (Patch Protocol)**: 不直接覆写文件，而是生成 `SEARCH/REPLACE` 格式的补丁，确保文件修改的精确性和最小副作用。
  - **环境自愈与诊断**: 自动探测环境中的缺失工具（如 `pytest`, `pnpm`）并尝试通过 shell 命令（如 `pip install`）进行自动修复。
  - **模糊匹配建议**: 当补丁匹配失败时，中间件会自动计算最接近的代码块并向 Agent 提供 "Did you mean...?" 建议，显著提升纠错效率。
- **性能评测 (Benchmark)**:
  - 建立在 `tests/benchmark/` 下的一套标准化任务集（L1-L3）。
  - 支持通过 `make benchmark` 一键运行全量任务并获得量化成功率报告。
- **工具遥测 (Telemetry)**:
  - 自动记录所有关键工具（`apply_patch`, `execute`）的执行轨迹。
  - 数据持久化至 `tool_telemetry` 数据库表，支持通过 API 进行性能分析。

## 技术实现
- **补丁协议与增强**:
  - 实现于 `patch_filesystem_middleware.py`。
  - 引入了基于 `difflib` 的模糊匹配算法，用于在补丁失败时生成自愈建议。
- **中间件栈 (Middleware Stack)**:
  - `ModelRetryMiddleware`: 模型重试控制。
  - `DockerMiddleware`: 容器环境绑定。
  - `SummarizationMiddleware`: 对话历史摘要。
  - **遥测集成**: 在中间件层捕获工具结果，异步写入 `app/services/telemetry.py`。
- **解耦设计**: 通过 `app/core/` 抽象层访问数据库和配置，不再直接硬编码依赖父平台。

## 性能/质量指标
- **成功率指标**: 基准任务（L1-L3）成功率目前稳定在 100%。
- **监控指标**: 支持统计全局工具调用成功率、常见错误代码分布及工具使用频率。

## 维护建议
- **回归测试**: 在修改 `prompts.py` 或中间件逻辑后，务必运行 `make benchmark` 确保没有性能退化。
- **遥测审计**: 定期通过 `/api/telemetry/stats` 接口审计 Agent 在真实生产环境下的表现，针对高频失败场景优化提示词。
