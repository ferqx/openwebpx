# 认证与授权模块 (Auth)

## 简介
OpenWebPX 的认证与授权模块位于 `app/auth/` 目录下，旨在提供灵活、安全且可插拔的用户身份验证服务。该模块原生支持多种认证驱动，允许开发者根据企业基础设施（如独立部署或集成现有系统）选择最合适的身份验证方式，同时提供细粒度的基于角色的访问控制（RBAC）。

## 功能详情
- **多驱动支持**:
  - **本地/DB**: 基于 SQLAlchemy 的数据库持久化存储，支持密码的加盐哈希存储。
  - **文件回退 (File Fallback)**: 在数据库不可用或纯本地运行模式下，自动降级为读取 JSON 文件（`data/auth_users.json`）进行身份验证。
  - **LDAP**: 原生集成 `ldap3`，支持对接企业级 Active Directory 或 OpenLDAP 服务。
  - **JWT**: 提供签发和解析 JWT (JSON Web Token) 的完整生命周期管理。
  - **OAuth (SCM)**: 深度集成 SCM (GitHub/GitLab) OAuth 授权，用于仓库访问（详情见 SCM 模块）。
  - **Firebase**: 架构设计上预留兼容插槽（见 `README.md` 及设计文档），可通过自定义路由扩展。
- **角色与权限 (RBAC)**: 内置 `admin`, `premium`, `developer`, `reviewer`, `free` 等标准角色，并根据角色动态解析读写权限。
- **LangGraph 集成**: 实现了 `langgraph_sdk.Auth` 协议（`aegra_auth.py`），对线程创建、搜索和助手管理等核心 API 提供细粒度拦截与鉴权。

## 技术实现
- **核心组件**: `app/auth/core.py` 包含了底层的密码加密（`pbkdf2_sha256` 算法，260,000 次迭代）、JWT 令牌签发（默认 `HS256`）、以及数据库和 LDAP 的读写操作。
- **路由层**: `app/routers/auth.py` 暴露了 `/auth/login`, `/auth/register`, `/auth/me`, `/auth/logout` 等 RESTful API，并采用 `HttpOnly` Cookie (`aegra_access_token`) 存储令牌以防范 XSS 攻击。
- **持久化逻辑**:
  - 使用 SQLAlchemy 执行原生 SQL (如 `AUTH_USER_UPSERT_SQL`) 保证性能，包含 `ON CONFLICT DO UPDATE` 应对分布式并发写入。
  - 核心表 `auth_users` 记录 `identity`, `password_hash`, `auth_source`, `role`, `team_id` 等字段。

## 性能/质量指标
- **安全性**:
  - 密码采用高强度 `pbkdf2_sha256` 算法进行哈希处理。
  - 敏感操作使用环境级 `AUTH_JWT_SECRET` 进行签名。
- **可用性**: 数据库故障时具备自动降级至内存/文件验证的高可用机制（File Fallback）。

## 维护建议
- **生产环境配置**: 在生产部署时，务必修改默认的 `AUTH_JWT_SECRET`，并考虑通过环境变量配置更复杂的 `AUTH_JWT_ALGORITHM`（如 RS256 或 ECDSA）。
- **LDAP 扩展**: 若企业内 LDAP 层级复杂，可通过修改 `AUTH_LDAP_BIND_DN_TEMPLATE` 适应不同的 Bind DN 规则。
- **清理与轮转**: 定期审查数据库中的非活动用户，并考虑在未来版本中引入 Refresh Token 机制以增强长期会话的安全性。
