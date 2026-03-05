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

## 7. 安全与配置
- 禁止提交密钥、令牌、密码等敏感信息。
- 新增配置项时同步更新 `.env.example` 与相关文档（如适用）。

## 8. 快速入口
- 项目总览、启动、测试、迁移、规范：`CLAUDE.md`
- Docker 快速启动：`README.md`（`docker compose up`）
- 运行入口：`run_server.py`、`app/main.py`
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
- 2026-03-05（沙箱执行策略与 SCM 凭据执行链路增强）：
  - `build_app_agent_v2` 新增 `sandbox_policy_guard.py` 并在 `PatchFilesystemMiddleware` 接入：统一拦截危险 git 变更命令、`.git` 写入、越界/批量 `rm|mv` 与 `apply_patch` 误用为 shell 命令等场景。
  - 新增 `workspace_tree_middleware.py`，在模型调用前注入工作区目录树快照到系统提示，减少“盲改”与重复探测。
  - `DockerBackend` 执行命令时会从 state 注入 `repo_auth_context` 与 `repo_git_identity`，自动下发 `GH_TOKEN/GLAB_TOKEN` 与 git author/committer 身份，并对输出中的 token 做脱敏。
  - `DockerMiddleware` 增强仓库绑定信息：保存 SCM 用户画像推导出的 git 身份；会话结束时主动 stop 容器（保留容器以便后续恢复），并在 repo 同步状态中回写认证上下文与身份信息。
  - 线程删除钩子新增容器清理流程：`app/auth/aegra_auth.py` 在 `threads.delete` 时 best-effort 解析并销毁绑定容器，失败只记录告警不阻断删除。
  - 协议提示更新：明确“用户要求提交代码/创建 PR/MR 时可走 git 提交流程”，并补充 `gh/glab` token 自动注入与禁用交互式 `auth login` 的约束。
  - 依赖与镜像更新：`aegra-cli/aegra-api` 升级至 `0.7.4`，`Dockerfile.agent` 预装 `github-cli` 与 `glab`；删除调试产物 `graphs/build_app_agent_v2/test-2.json`。
- 2026-03-04（build_app_agent_v2 工具链与沙箱增强）：
  - `build_app_agent_v2` 新增 `update_plan` 工具（在 `PatchFilesystemMiddleware` 注册），支持计划步骤校验与状态回写，避免提示词要求与可用工具不一致导致 `update_plan is not a valid tool`。
  - 修复 `ToolCallGuardMiddleware` 在 `apply_patch` 场景下的 diff 元数据采集：相对路径统一归一到 `/workspace/...` 后再读取，确保 `additional_kwargs.file_diff`/`tool_file_diffs` 可用于前端渲染。
  - 前端 `openwebpx-ui` 增加 `apply_patch` diff 回退解析：当后端未返回 `file_diff` 时，可从 `ai.tool_calls[].args.patch_content` 解析文件路径、增删行与 old/new 文本并渲染差异视图。
  - Web 沙箱默认镜像由 `node:20-bookworm` 切换为 `sandbox-agent:latest`（`middleware/docker.py`），并重建镜像。
  - `deployments/docker/Dockerfile.agent` 增强：预装常用终端工具（含 `ripgrep`、`fd`、`jq`、`git`、`python3`、`node`、`pnpm`、`yarn`、`patch` 等），避免运行期 `rg: not found`。
- 2026-03-03（用户认证增强：数据库持久化 + LDAP 登录）：
  - 用户认证从文件存储升级为“数据库优先”，新增 `auth_users` 表（迁移：`alembic/versions/20260303110000_add_auth_users_table.py`），支持本地账号信息持久化。
  - `/auth/register` 与 `/auth/login` 认证链路已异步化并接入数据库；数据库不可用时默认回退文件存储（可通过 `AUTH_FILE_FALLBACK_ENABLED=false` 关闭回退）。
  - 增加 LDAP 登录分支（`AUTH_LDAP_ENABLED=true` 时启用）：本地认证失败后尝试 LDAP bind，成功后自动 upsert 用户到 `auth_users`（`auth_source=ldap`）。
  - LDAP 关键配置：`AUTH_LDAP_SERVER_URI`、`AUTH_LDAP_BIND_DN_TEMPLATE`（需包含 `{username}` 占位符），可选 `AUTH_LDAP_DEFAULT_ROLE`、`AUTH_LDAP_DEFAULT_TEAM_ID`。
  - 新增回归测试：`tests/test_auth_core.py`，覆盖“注册写库路径”和“LDAP 登录成功后回写数据库”。
- 2026-03-02（代码质量审查 webhook 自动同步）：
  - 仓库级代码审查配置保存时，后端会自动尝试创建/更新对应 GitHub/GitLab webhook（幂等：优先查询已有 hook）。
  - 自动同步失败不阻断配置保存，接口返回 `webhook_sync` 与 `manual_setup` 指引，前端可引导用户手工配置。
  - webhook 地址解析优先级：`OPENWEBPX_CODE_REVIEW_WEBHOOK_URL` > `OPENWEBPX_PUBLIC_BASE_URL + /integrations/code-review/webhook` > 请求基地址推导。
  - webhook 密钥策略：优先 `GITHUB_WEBHOOK_SECRET / GITLAB_WEBHOOK_SECRET`，回退 `OPENWEBPX_CODE_REVIEW_WEBHOOK_SECRET`。
  - 新增回归测试：`test_code_review_repo_setting_returns_manual_webhook_fallback`，覆盖自动同步失败的回退路径。
- 2026-03-02（代码质量审查后端能力）：
  - 新增代码审查设置接口：`/integrations/code-review/settings`、`/integrations/code-review/settings/global`、`/integrations/code-review/settings/repositories`。
  - 新增代码审查 webhook 入口：`/integrations/code-review/webhook`，支持 GitHub/GitLab 的 PR/Push 事件触发自动审查任务。
  - 执行链路：Webhook 解析事件并匹配用户配置后，复用现有 SCM 授权与 Run 创建流程，自动创建线程并运行审查 Agent（默认 `build_app_agent_v2`）。
  - 新增表迁移：`code_review_profiles`、`code_review_repo_settings`（见 `alembic/versions/20260302190000_add_code_review_settings_tables.py`）。
  - 新增回归测试：`test_code_review_settings_routes_smoke`、`test_code_review_webhook_dispatches_enabled_targets`。
- 2026-03-01（SCM 连接中心兼容修复）：
  - 修复 `/integrations/scm/connections` 在读取历史 `scm_tokens.github_auth_mode` 值（如 `oauth`）时触发 `400: GitHub auth_mode 仅支持 github_app` 的问题。
  - 处理策略：连接列表读取场景对历史值执行兼容降级（统一视为 `github_app`），不影响授权读取与刷新主流程。
  - 新增回归测试：`test_scm_connections_route_tolerates_legacy_github_auth_mode`，覆盖历史脏数据下连接列表接口可用性。
