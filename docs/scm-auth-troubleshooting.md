# SCM 授权排障手册（后端）

更新时间：2026-03-01

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

## 3. 标准排障顺序（后端）
1. 检查 `/integrations/scm/connections` 返回码与响应体。
2. 若 400 且含 `auth_mode`，优先怀疑历史 `github_auth_mode` 脏值。
3. 检查 `scm_tokens` 表是否存在、是否有对应用户数据。
4. 检查服务实际 DB 连接是否为持久化存储。
5. 检查 OAuth authorize 与 callback 的 `redirect_uri`、`origin` 一致性。
6. 再看上游平台（GitHub/GitLab）是否已经撤销授权。

## 4. 运维/修复动作建议
- 应用迁移：
  - `python scripts/migrate.py upgrade`
- 查看当前迁移版本：
  - `python scripts/migrate.py current`
- 回归测试：
  - `uv run pytest tests/test_custom_routes_smoke.py -k "scm"`
  - `uv run ruff check app/routers/scm.py tests/test_custom_routes_smoke.py`
- 必要时清理特定用户的失效授权：
  - 调用 `DELETE /integrations/scm/connections`（按 provider + base_url 定位）。

## 5. 防回归要求
- 任何 SCM 改动必须至少覆盖：
  - 授权 -> 拉仓库 -> 拉分支
  - 后端重启后授权仍可读取
  - 平台侧撤销授权后接口可识别并返回可操作错误
  - 历史脏数据（含旧 `github_auth_mode`）不应导致连接列表 400

## 6. 前后端契约提示
- GitHub 仅支持 `github_app`。
- 连接中心接口：
  - `GET /integrations/scm/connections`
  - `GET /integrations/scm/connections/validate`
  - `DELETE /integrations/scm/connections`
- 若后端暂不支持连接中心，前端应进入兼容回退模式而非直接报致命错误。
