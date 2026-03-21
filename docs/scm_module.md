# SCM 集成模块 (SCM)

## 简介
SCM 集成模块（位于 `app/services/scm/` 及 `app/routers/scm.py`）负责管理与 GitHub 和 GitLab 等代码托管平台的深度集成。该模块不仅处理 OAuth 授权和令牌生命周期，还提供了抽象的 API 接口，用于仓库内容同步、用户信息获取以及 PR/MR 的自动化交互。

## 功能详情
- **多平台支持**:
  - **GitHub**: 支持通过 GitHub App 或 个人访问令牌 (PAT) 进行连接。
  - **GitLab**: 支持 GitLab 公网版及企业私有化部署 (GitLab Enterprise Edition)。
- **Token 安全存储**:
  - 采用 AES-256 对存储在数据库（`scm_tokens` 表）中的 `access_token` 进行加密。
  - 支持 `refresh_token` 的自动刷新机制，确保连接长效。
- **OAuth 流程管理**: 全自动处理从 `authorize` 到 `callback` 交换令牌的 OAuth 2.0 完整流程。
- **PR/MR 自动化交互**: 提供工具接口（见 `app/services/scm/repository.py`），支持 Agent 在审查代码后自动回填行级评论。

## 技术实现
- **加密核心**: `app/services/scm/crypto.py` 使用 `cryptography.fernet` 对敏感凭据进行静态加密。
- **服务类**: `ScmOAuthService` (在 `oauth.py`) 定义了针对不同平台的 `exchange_token` 和 `refresh_token` 逻辑。
- **令牌解析**: 通过路由层的 `_resolve_scm_access_token` 依赖注入，自动为每个请求上下文提取并解密当前用户的 SCM 令牌。
- **Git 操作上下文**: 将解密后的令牌动态注入 Docker 容器的环境变量（如 `GITHUB_TOKEN`, `GLAB_TOKEN`），使容器内能无缝执行 `git push` 等权限操作。

## 性能/质量指标
- **安全性**: 所有 SCM 令牌在数据库中均不以明文形式存在，解密过程仅发生在内存中且瞬时完成。
- **兼容性**: 完美适配 GitHub REST API v3 和 GitLab API v4。
- **鲁棒性**: 具备自动 Token 刷新逻辑，有效减少因令牌过期导致的自动化流程中断。

## 维护建议
- **证书配置**: 对于私有化部署的 GitLab，务必确保证书可信任，或在环境变量中妥善配置 `GITLAB_BASE_URL`。
- **加密盐值**: 初始部署时请确保 `SCM_TOKEN_ENCRYPTION_KEY` 的随机性，并定期备份密钥。
- **API 限速监控**: 大规模并发执行代码审查时，请关注 SCM 平台的 API Rate Limit 指标。
