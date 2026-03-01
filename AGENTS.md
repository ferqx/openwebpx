# AGENTS.md

AI 代理在本仓库工作时请遵循以下协议。

## 1. 目标与范围
- 本项目是 **Aegra**：兼容 Agent Protocol 的自托管 Agent Server。
- 代理的首要目标是：在不破坏现有行为的前提下，高质量完成用户请求。

## 2. 文档优先级
- **最高优先级文档：** `CLAUDE.md`
- 本文件仅提供执行协议与最小导航，不重复维护完整技术细节。
- 若本文件与 `CLAUDE.md` 存在冲突，以 `CLAUDE.md` 为准。
- TODO: 当前仓库未发现 `CLAUDE.md`，新增后请同步更新本文件中的导航与命令索引。

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
- 涉及数据库变更时，使用 `scripts/migrate.py` 和 Alembic 流程。

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

## 7. 安全与配置
- 禁止提交密钥、令牌、密码等敏感信息。
- 新增配置项时同步更新 `.env.example` 与相关文档（如适用）。

## 8. 快速入口
- 项目总览、启动、测试、迁移、规范：`CLAUDE.md`
- Docker 快速启动：`README.md`（`docker compose up`）
- 运行入口：`run_server.py`、`app/main.py`
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
- 2026-03-01（SCM 连接中心兼容修复）：
  - 修复 `/integrations/scm/connections` 在读取历史 `scm_tokens.github_auth_mode` 值（如 `oauth`）时触发 `400: GitHub auth_mode 仅支持 github_app` 的问题。
  - 处理策略：连接列表读取场景对历史值执行兼容降级（统一视为 `github_app`），不影响授权读取与刷新主流程。
  - 新增回归测试：`test_scm_connections_route_tolerates_legacy_github_auth_mode`，覆盖历史脏数据下连接列表接口可用性。
