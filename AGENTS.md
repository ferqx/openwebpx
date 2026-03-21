# AGENTS.md

AI 代理在本仓库工作时请遵循以下协议。

## 1. 目标与范围
- 本项目是 **Aegra**：兼容 Agent Protocol 的自托管 Agent Server。
- 代理的首要目标是：在不破坏现有行为的前提下，高质量完成用户请求。

## 2. 文档优先级
- **最高优先级文档：** `CLAUDE.md`
- 本文件仅提供执行协议与最小导航，不重复维护完整技术细节。
- 若本文件与 `CLAUDE.md` 存在冲突，以 `CLAUDE.md` 为准。
- `CLAUDE.md` 已创建，包含完整的技术细节、命令索引和架构说明。

## 3. 工作流程（必须执行）
1. 先阅读与任务直接相关的代码与测试。
2. 小步修改，保持改动最小化、可回滚。
3. 优先修复根因，不做表面补丁。
4. 完成后运行相关校验（至少包含受影响范围测试）。
5. 输出变更说明：修改文件、行为变化、验证结果、风险点。

## 4. 代码与架构约束
- 遵循现有分层：API 层 / Service 层 / Core 基础设施层。
- 保持导入、命名、类型标注、错误处理风格与现有代码一致。
- 非必要不引入新依赖、不做大规模重构。
- 进行重构/优化时，优先把“规则判断、状态归一化、命令构造、纯函数逻辑”下沉到 `app/services`；路由与中间件保留编排职责，不要把新逻辑继续堆回超大文件。
- 重构期优先补“编排层测试 + service 单测”，再继续拆生产代码；若新边界没有测试保护，禁止继续深拆高风险主流程。
- 涉及数据库变更时，使用 `scripts/migrate.py` 和 Alembic 流程。
- 新增或修改的“非直观逻辑”必须添加简短注释，说明意图与约束（避免解释显而易见的语句）。

## 5. 测试与质量门禁
- 常用命令（详见 `CLAUDE.md`）：
  - `make dev-install`（安装开发依赖并配置 pre-commit hooks）
  - `uv run pytest`
  - `uv run pytest tests/<file>.py -k <pattern>`（受影响范围回归）
  - `make test-cov`（生成覆盖率报告）
  - `uv run ruff check .`
  - `uv run mypy src`
  - `make security`（Bandit 安全扫描）
  - `make ci-check`（本地执行格式化/静态检查/测试）
  - `make run`（本地启动服务）
  - `python scripts/migrate.py upgrade`（应用数据库迁移）
  - `python scripts/migrate.py revision --autogenerate -m "<msg>"`（生成迁移）
  - `python scripts/migrate.py current`（查看当前迁移版本）
- 若无法运行某项检查，需在结果中明确说明原因与影响。

## 6. 文件与变更策略
- 仅修改为完成当前任务所必需的文件。
- 不得无关格式化全仓库。
- 不要修改与任务无关的公共接口。
- 未经明确要求，不进行破坏性操作（如删除大量文件、重置历史）。
- 涉及 `build_app_agent_v3` 的 `apply_patch` 时，禁止任何“猜测式”降级处理：`SEARCH` 未精确命中、目标文件缺失/已存在、路径非法、编码异常、混合换行等情况必须直接失败并把原因返回给模型；严禁自动追加内容、覆盖文件、宽松匹配或静默规范化文本。
- 涉及 `build_app_agent_v3` 的大文件修改时，必须将 `apply_patch` 拆成多个局部块；禁止整文件级 `<search>...</search>` / `<replace>...</replace>` 替换。若出现 `Missing </replace>`、`Missing </search>` 等解析错误，必须重新生成更小且完整闭合的 patch，禁止在失败补丁后续写尾部。

## 7. 安全与配置
- 禁止提交密钥、令牌、密码等敏感信息。
- 新增配置项时同步更新 `.env.example` 与相关文档（如适用）。

## 8. 快速入口
- 项目总览、启动、测试、迁移、规范：`CLAUDE.md`
- Docker 快速启动：`README.md`（`docker compose up`）
- 运行入口：`run_server.py`、`app/main.py`
- 当前默认任务图：`aegra.json`、`graphs/build_app_agent_v3/agent.py`
- 沙箱路由编排入口：`app/routers/sandbox.py`
- 沙箱/容器服务层入口：`app/services/sandbox_*.py`、`app/services/docker_*.py`
- 代码审查后端入口：`app/routers/code_review.py`（设置接口 + webhook 触发）
- 迁移脚本：`scripts/migrate.py`
- 测试目录：`tests/`

## 9. 输出规范（给用户）
- 先给结论，再给关键细节。
- 明确列出：
  - 改了什么
  - 为什么这样改
  - 如何验证
  - 仍存在哪些风险/后续建议

## 10. 功能变更动态记录
- 变更记录已迁移至 `changelogs/` 目录。
- 请在该目录下按日期查看相应的 Markdown 文件。
