# SCM 授权排障手册（后端）

更新时间：2026-03-06

## 1. 目标
- 记录 SCM（GitHub App / GitLab OAuth2）授权链路的高频故障、根因和修复步骤。
- 帮助后续 AI/开发者快速定位“授权丢失”“连接接口报错”“重启后失效”等问题，避免重复踩坑。

## 2. 常见故障与根因

### 2.1 `/integrations/scm/connections` 返回 400
- 典型报错：
  - `GitHub auth_mode 仅支持 github_app`
- 根因：
  - 历史 `scm_tokens` 行中 `github_auth_mode` 存在旧值（例如 `oauth`）。
  - 连接列表读取时走严格校验触发 `HTTP 400`。
- 当前修复策略：
  - 连接列表场景对历史值兼容降级，统一按 `github_app` 处理（不再抛 400）。

### 2.2 服务重启后授权丢失
- 典型表现：
  - 授权后可拉仓库，重启后提示重新授权。
- 根因：
  - `scm_tokens` 表不存在（迁移未执行）。
  - 数据库非持久（例如临时 SQLite 或容器临时卷）。
  - 仅写入了进程内缓存，未正确持久化到 DB。
- 检查方向：
  - 迁移版本是否已升级到包含 `scm_tokens` 的版本。
  - 实际运行时 DB URL 是否与预期持久库一致。

### 2.3 OAuth 回调阶段失败
- 典型报错：
  - `OAuth state 无效或已过期`
  - `The code passed is incorrect or expired.`
- 根因：
  - 回调重复提交同一组 `state+code`。
  - authorize/callback 的 `redirect_uri` 或 `origin` 不一致。
- 当前策略：
  - 回调页提交去重。
  - 服务端校验 `redirect_uri` 与 `origin` 一致性。

### 2.4 GitLab 授权 URL 报错
- 典型报错：
  - `The redirect URI included is not valid.`
  - `The requested scope is invalid, unknown, or malformed.`
- 根因：
  - GitLab 应用配置的 redirect URI 与前端实际值不完全一致。
  - scope 配置不兼容。
- 当前策略：
  - `redirect_uri` 固定为前端 origin 回调地址。
  - scope 默认不强制，显式配置才下发。

### 2.5 Docker 沙箱内 SCM 环境变量看似已注入，但 `gh/glab/git` 运行异常
- 典型表现：
  - 线程 state 中已有 `repo_auth_context` / `repo_git_identity`，但容器内执行 `gh`、`glab`、`git config user.name` 结果不符合预期。
  - 复用旧容器后，GitHub/GitLab CLI 行为和首次拉仓库后的行为不一致。
  - `glab mr create` 返回 `401 Unauthorized`，但手工 `curl -H "Authorization: Bearer $GITLAB_TOKEN"` 可以成功访问 GitLab API。
- 本次确认的根因：
  - 旧容器复用时，会重新 bootstrap `/etc/profile.d/openwebpx-scm.sh`，但此前“仓库已同步成功”的短路路径没有再次刷新 git 身份与 token，导致 state 和容器 shell 实际值脱节。
  - bootstrap 脚本早期版本使用 `unset SCM_TOKEN/GH_TOKEN/...`，会在 `bash -lc` 启动时清空 Docker exec 注入进来的环境变量。
  - `glab mr create` 对 GitLab OAuth token 的行为不稳定；同一 token 直接通过 `Authorization: Bearer` 调 GitLab REST API 可以正常创建 MR。
- 当前修复策略：
  - `DockerMiddleware` 复用已同步仓库的容器时，仍会重新解析 token 并刷新容器内 git runtime 环境。
  - bootstrap 脚本改为保留 Docker exec 注入值，不再 `unset` SCM 变量。
  - `DockerBackend.execute` 与 sandbox policy 双层拦截 `glab mr create`，统一引导 GitLab 走 REST API。
  - GitLab 创建 MR 的稳定做法统一为：`Authorization: Bearer $GITLAB_TOKEN` + `POST /api/v4/projects/:id/merge_requests`；企业版或较老实例优先用数字 project id 和 `--data-urlencode`。

## 3. 标准排障顺序（后端）
1. 检查 `/integrations/scm/connections` 返回码与响应体。
2. 若 400 且含 `auth_mode`，优先怀疑历史 `github_auth_mode` 脏值。
3. 检查 `scm_tokens` 表是否存在、是否有对应用户数据。
4. 检查服务实际 DB 连接是否为持久化存储。
5. 检查 OAuth authorize 与 callback 的 `redirect_uri`、`origin` 一致性。
6. 再看上游平台（GitHub/GitLab）是否已经撤销授权。
7. 若问题只在 Docker 沙箱里出现，按 3.1 节执行容器内复现与定位。

### 3.1 Docker 沙箱内变量注入问题的复用排障方案
1. 先确认 thread state 中是否存在 `repo_auth_context` 与 `repo_git_identity`。
2. 在容器内直接验证 token 和用户信息，不要先假设是 OAuth 失效：
   - `curl -s -H "Authorization: Bearer $GITLAB_TOKEN" "https://gitlab.com/api/v4/user"`
   - 若返回用户 JSON，说明 token 已注入且有效。
3. 对 GitLab 不要优先用 `glab mr create` 验证授权，直接用 REST API：
   - `curl --fail -X POST "https://<gitlab-host>/api/v4/projects/<numeric-id>/merge_requests" -H "Authorization: Bearer $GITLAB_TOKEN" --data-urlencode "source_branch=..." --data-urlencode "target_branch=..." --data-urlencode "title=..."`
4. 若手工 `curl` 可成功，而 `glab mr create` 失败，不再继续追查注入链路，直接判定为 `glab` + OAuth token 路径不稳定。
5. 若容器复用场景怀疑 shell 初始化有问题，优先运行真实 Docker 集成测试：
   - `OPENWEBPX_RUN_DOCKER_INTEGRATION=1 uv run pytest tests/test_docker_backend.py -k real_container`
6. 若测试失败，再检查：
   - `/etc/profile.d/openwebpx-scm.sh` 是否仍保留 exec 注入变量
   - `DockerMiddleware._maybe_sync_thread_repository` 的已同步短路路径是否执行了 runtime env refresh
   - `DockerBackend.execute` 是否仍通过 `bash -lc` 运行命令

## 4. 运维/修复动作建议
- 应用迁移：
  - `python scripts/migrate.py upgrade`
- 查看当前迁移版本：
  - `python scripts/migrate.py current`
- 回归测试：
  - `uv run pytest tests/test_custom_routes_smoke.py -k "scm"`
  - `uv run ruff check app/routers/scm.py tests/test_custom_routes_smoke.py`
  - Docker SCM 注入链路：
    - `uv run pytest tests/test_docker_backend.py tests/test_docker_middleware.py`
    - 需要真实容器端到端验证时：`OPENWEBPX_RUN_DOCKER_INTEGRATION=1 uv run pytest tests/test_docker_backend.py -k real_container`
- 必要时清理特定用户的失效授权：
  - 调用 `DELETE /integrations/scm/connections`（按 provider + base_url 定位）。

## 5. 防回归要求
- 任何 SCM 改动必须至少覆盖：
  - 授权 -> 拉仓库 -> 拉分支
  - 后端重启后授权仍可读取
  - 平台侧撤销授权后接口可识别并返回可操作错误
  - 历史脏数据（含旧 `github_auth_mode`）不应导致连接列表 400
  - 复用旧 Docker 容器后，`repo_auth_context` / `repo_git_identity` 仍能刷新到容器 shell 环境
  - `bash -lc` 执行路径下 `GH_TOKEN/GITLAB_TOKEN` 不会被 bootstrap 脚本清空
  - GitLab MR 创建默认走 REST API，而不是 `glab mr create`

## 6. 前后端契约提示
- GitHub 仅支持 `github_app`。
- 连接中心接口：
  - `GET /integrations/scm/connections`
  - `GET /integrations/scm/connections/validate`
  - `DELETE /integrations/scm/connections`
- 若后端暂不支持连接中心，前端应进入兼容回退模式而非直接报致命错误。
