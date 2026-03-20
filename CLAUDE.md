# CLAUDE.md

本文件为 Claude Code (claude.ai/code) 在本代码库中工作时提供指导。

## 项目概述

**Aegra** 是一个自托管的 LangGraph Platform 替代方案 - 基于 FastAPI 和 PostgreSQL 的 AI 智能体后端。它提供零供应商锁定和对智能体基础设施的完全控制。

- **语言**: Python 3.12+
- **包管理器**: uv
- **Web 框架**: FastAPI
- **智能体框架**: LangGraph
- **数据库**: PostgreSQL with pgvector
- **测试**: pytest
- **代码检查/格式化**: ruff
- **类型检查**: mypy

## 架构概览

### 目录结构

```
app/                     # FastAPI 应用程序
├── main.py             # 应用程序入口点
├── routers/            # API 路由处理器
│   ├── auth.py         # 认证路由
│   ├── sandbox.py      # 沙箱线程管理
│   ├── scm.py          # SCM (GitHub/GitLab) 集成
│   └── code_review.py  # 代码审查设置/webhook
├── services/           # 业务逻辑层
│   ├── sandbox_*.py    # 沙箱辅助函数
│   └── docker_*.py     # Docker 服务层
└── auth/               # 认证实现

graphs/                  # LangGraph 智能体定义
├── build_app_agent_v3/ # 主智能体实现
│   ├── agent.py        # 智能体入口点
│   ├── prompts.py      # 系统提示词构造
│   ├── patch_filesystem_middleware.py  # 文件操作
│   ├── repository_context.py         # 仓库分析
│   └── *_middleware.py # 各种中间件
├── react_agent/        # React 风格智能体
└── chats_agent/        # 聊天智能体

middleware/              # 共享中间件
└── docker.py           # Docker 容器生命周期

backends/                # 后端实现
└── docker.py           # Docker 执行后端

tests/                   # 测试套件
alembic/                 # 数据库迁移
```

### 核心架构概念

1. **Agent Protocol 兼容性**: 实现 [Agent Protocol](https://github.com/langchain-ai/agent-protocol) 以兼容 Agent Chat UI、LangGraph Studio、CopilotKit。

2. **基于图的智能体**: 智能体在 `graphs/` 中定义为 LangGraph 状态机。主智能体是 `build_app_agent_v3`。

3. **中间件栈**: 智能体使用中间件模式处理横切关注点:
   - `PatchFilesystemMiddleware`: 严格验证的文件操作
   - `DockerMiddleware`: 容器生命周期管理
   - `SummarizationMiddleware`: 对话摘要
   - `ThinkToolMiddleware`: 智能体推理工具

4. **沙箱模型**: 代码执行在与仓库绑定的 Docker 容器中执行。

5. **认证**: 可插拔认证（noop、JWT、OAuth、Firebase）通过 `app/auth/` 实现。

## 常用命令

### 开发环境设置

```bash
# 安装依赖和开发工具
make dev-install

# 或手动:
uv sync
uv run pre-commit install
uv run pre-commit install --hook-type commit-msg
```

### 运行服务器

```bash
# Docker (推荐用于完整功能)
docker compose up

# 或本地开发 (需要 PostgreSQL)
cp .env.example .env
# 编辑 .env 添加你的设置
make run
# 或: uv run python run_server.py
```

### 数据库迁移

```bash
# 应用所有待处理迁移
python scripts/migrate.py upgrade

# 创建新迁移
python scripts/migrate.py revision --autogenerate -m "添加新表"

# 检查当前版本
python scripts/migrate.py current

# 回滚一个迁移
python scripts/migrate.py downgrade

# 重置数据库 (破坏性!)
python scripts/migrate.py reset
```

### 测试

```bash
# 运行所有测试
make test
# 或: uv run pytest

# 运行带覆盖率报告的测试
make test-cov

# 运行特定测试文件
uv run pytest tests/test_build_app_agent_v3_patch_middleware.py

# 使用模式匹配运行
uv run pytest tests/ -k "test_patch"

# 运行 e2e 测试
uv run pytest tests/ -m e2e
```

### 代码质量

```bash
# 格式化和自动修复
make format
# 或: uv run ruff format . && uv run ruff check --fix .

# 仅检查
make lint
# 或: uv run ruff check .

# 类型检查
make type-check
# 或: uv run mypy src/

# 安全扫描
make security
# 或: uv run bandit -c pyproject.toml -r src/

# 运行所有 CI 检查
make ci-check
```

### 清理

```bash
make clean  # 删除缓存文件
```

## 配置

### 环境变量

`.env` 中的关键配置:

```bash
# 必需
OPENAI_API_KEY=sk-...
AEGRA_CONFIG=aegra.json

# 数据库
DATABASE_URL=postgresql://user:pass@host:5432/openwebpx
# 或单独配置: POSTGRES_DB, POSTGRES_HOST, POSTGRES_PASSWORD, POSTGRES_PORT, POSTGRES_USER

# 认证: noop, custom
AUTH_TYPE=noop

# 沙箱容器设置
DOCKER_GID=998
AEGRA_DOCKER_USER=0:0
OPENWEBPX_CONTAINER_STOP_DELAY_SECONDS=1800

# 智能体设置
OPENWEBPX_BUILD_APP_AGENT_V3_MAX_TOKENS=4000
OPENWEBPX_BUILD_APP_AGENT_V3_THINK_TOOL=1
OPENWEBPX_BUILD_APP_AGENT_V3_CONTEXT_MAX_TOKENS=3000
```

查看 `.env.example` 获取完整选项。

### 智能体配置 (`aegra.json`)

```json
{
  "graphs": {
    "agent": "./graphs/react_agent/graph.py:graph",
    "build_app_agent_v3": "./graphs/build_app_agent_v3/agent.py:agent"
  },
  "auth": {
    "path": "./app/auth/aegra_auth.py:auth"
  },
  "http": {
    "app": "./app/main.py:app",
    "enable_custom_route_auth": false
  }
}
```

## 代码库工作指南

### 智能体开发 (`graphs/build_app_agent_v3/`)

主智能体使用基于中间件的架构:

1. **智能体入口** (`agent.py`): 使用中间件栈创建智能体
2. **提示词** (`prompts.py`): 系统提示词构造
3. **文件操作** (`patch_filesystem_middleware.py`): 带 SEARCH/REPLACE 的严格文件修补
4. **仓库上下文** (`repository_context.py`): 智能体上下文的仓库分析
5. **Docker 集成** (`middleware/docker.py`): 容器生命周期

### 测试策略

- 单元测试: `tests/test_*.py` - 测试单个组件
- 中间件测试: `tests/test_build_app_agent_v3_*.py` - 测试智能体中间件
- 集成测试: 需要 Docker, 通过 `OPENWEBPX_RUN_DOCKER_INTEGRATION=1` 启用

### 数据库迁移

Alembic 用于数据库迁移。迁移文件位于 `alembic/versions/`。

在模型更改后创建新迁移:
```bash
python scripts/migrate.py revision --autogenerate -m "描述"
```

### 常见开发任务

1. **添加新路由**: 添加到 `app/routers/`, 导入并在 `app/main.py` 中包含。
   - **Request 参数安全准则**：在路由函数中使用 `Request` 对象时，必须声明为 `request: Request`。**严禁**使用 `request: Request | None = None` 或 `request: Request = None`，否则会导致 FastAPI 尝试将其解析为 Pydantic 模型，触发 "Invalid args for response field" 错误。
   - **参数顺序**：由于 `request: Request` 是无默认值的必填参数，它必须放在所有带默认值（如 `Query(...)`, `Body(...)`）的参数**之前**。
2. **添加中间件**: 添加到 `middleware/` 或 `graphs/` 中的特定图中间件
3. **添加服务**: 添加到 `app/services/` 用于业务逻辑
4. **添加测试**: 创建 `tests/test_<feature>.py`, 遵循现有模式

## CI/CD

项目使用 pre-commit 钩子和 GitHub Actions（如果已配置）。关键检查:

- `ruff`: 代码检查和格式化
- `mypy`: 类型检查
- `bandit`: 安全扫描
- `pytest`: 测试执行

## 故障排查

### Docker 问题
- 确保 Docker 守护进程正在运行
- 检查 `.env` 中的 `DOCKER_GID` 和 `AEGRA_DOCKER_USER`
- 对于 macOS: 为 `AEGRA_DOCKER_USER` 使用 `0:0` (root)

### Docker 数据库持久化问题
**问题**: `docker compose down` 后数据库数据丢失

**原因**:
- 使用了 `docker compose down -v` 会删除命名卷
- 卷被意外删除或清理

**解决方案**:
1. **使用本地目录绑定挂载（推荐用于生产）**:
   编辑 `docker-compose.yml`，在 `postgres_data` 下添加:
   ```yaml
   volumes:
     postgres_data:
       driver_opts:
         type: none
         o: bind
         device: /path/to/your/postgres/data
   ```

2. **备份和恢复**:
   ```bash
   # 备份
   docker exec -t your-db-container pg_dumpall -c -U postgres > dump.sql

   # 恢复
   cat dump.sql | docker exec -i your-db-container psql -U postgres
   ```

3. **避免使用 `-v` 参数**:
   ```bash
   # 危险 - 会删除卷
   docker compose down -v

   # 安全 - 保留卷
   docker compose down
   ```

### 数据库问题
- 确保 PostgreSQL 正在运行或使用 `docker compose up`
- 检查 `DATABASE_URL` 或单独的 `POSTGRES_*` 变量
- 运行 `python scripts/migrate.py upgrade` 应用迁移

### 导入错误
- 确保虚拟环境已激活: `source .venv/bin/activate`
- 或使用 `uv run` 前缀运行命令

### 测试失败
- 某些测试需要 Docker: `OPENWEBPX_RUN_DOCKER_INTEGRATION=1`
- 检查 `.env` 配置

## 参考资料

- **README.md**: 项目概述和快速开始
- **docs/**: 项目功能和架构文档
- **changelogs/**: 功能变更日志
- **AGENTS.md**: 代理工作协议
