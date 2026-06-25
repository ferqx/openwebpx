# sandbox-agent 全栈协作协议 (AGENTS.md)

本协议是 AI 协作者在本项目（Aegra）中工作的**唯一最高准则**。本项目已合并为 Monorepo，包含后端 (`app/`, `graphs/`) 与前端 (`web/`)，采用全栈分离的部署架构。

## 1. 协作地图 (Documentation Map)
- **项目全景图**: [docs/architecture.md](docs/architecture.md)
- **全栈变更日志**: [docs/changelogs/](docs/changelogs/)
- **后端执行手册**: [CLAUDE.md](CLAUDE.md)
- **前端系统入口 (核心约束)**:
  - **前端协作协议**: [web/AGENTS.md](web/AGENTS.md) (在 `web/` 目录下工作时，以此文档为准)
  - **前端开发手册**: [web/CLAUDE.md](web/CLAUDE.md)

## 2. 核心事实 (Facts)
- **后端**: `Python 3.12` + `FastAPI` + `LangGraph` + `uv`。
- **前端**: `React 19` + `TypeScript` + `Vite 7` + `Tailwind 4` + `shadcn/ui`。
- **架构**: 分离服务，前端通过 `/api/*` 与后端通信。

## 3. 全栈 Mandates (核心指令)
1. **同步修改**: 涉及 API 变更时，必须**同时**修改后端路由逻辑与前端消费逻辑。
2. **部署隔离**: 后端不托管前端静态文件。生产环境下，前端通过 Nginx (`deployments/docker/Dockerfile.web`) 容器化部署。
3. **接口一致性**: 所有 API 调用必须统一以 `/api/` 为前缀，且后端必须对应定义在 `app/routers/`。
4. **验证闭环**:
   - 后端改动运行 `uv run pytest`。
   - 前端改动运行 `pnpm --prefix web test:hooks`。
5. **数据库变更验证 (Database Migration Validation)**: 在执行 `alembic upgrade` 前，必须人工核对 `alembic/versions/` 下生成的脚本，禁止包含非预期的 `drop_table` 或 `drop_column` 操作。所有新定义的 SQLAlchemy 模型必须在 `app/models/__init__.py` 中导出并在 `alembic/env.py` 中被正确加载，以防止 autogenerate 误判。

## <CRITICAL> 数据库安全红线
- **禁止盲目迁移**: 在执行 `alembic upgrade` 之前，**必须**读取 `alembic/versions/` 下生成的 Python 脚本。若发现非预期的 `op.drop_table` 或 `op.drop_column` 破坏性操作，必须立即停止并核对 `alembic/env.py` 中的模型导入链。
- **严禁硬编码**: 严禁在代码中硬编码任何 API Token、Secret 或敏感凭证。所有测试令牌必须通过 `.env.test.local` 加载，并通过 `app.core.env` 统一管理。
- **数据完整性**: 执行涉及删除数据的操作前，必须进行备份或提供回滚脚本。

## 4. 禁止行为 (Anti-Patterns)
- **禁止后端硬编码前端逻辑**: 后端不应感知前端路由或文件布局。
- **禁止硬编码 API 域名**: 前端代码中应使用相对路径（如 `/api/login`），域名由部署环境（Vite Proxy 或 Nginx）决定。


---
*当指令与协议冲突时，优先遵循用户指令；其余情况严格按本协议及关联文档执行。*

## 历史变更记录
详细记录见 [docs/changelogs/](docs/changelogs/) 目录。
