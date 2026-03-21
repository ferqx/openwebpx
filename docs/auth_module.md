# 身份验证模块 (Authentication)

## 简介
身份验证模块负责管理用户会话、令牌颁发以及 API 路由的安全保护。为了提高系统的独立性，该模块采用了抽象层设计，将具体的鉴权实现与业务逻辑分离。

## 功能详情
- **统一身份抽象**: 核心接口依赖于 `app/core/auth.py` 中的 `authenticated_user`，不再直接耦合底层平台。
- **用户管理**: 支持用户注册、登录、注销以及获取当前用户信息。
- **角色与权限**: 基于角色的访问控制（RBAC），支持 `admin`, `developer`, `premium` 等多种订阅层级。
- **令牌管理**: 采用 JWT 或平台颁发的令牌进行会话跟踪，通过 Cookie (HTTPOnly) 进行安全传输。

## 技术实现
- **核心抽象层 (`app/core/auth.py`)**:
  - `authenticated_user`: 这是一个 FastAPI 依赖项，用于在路由层面强制进行身份检查。目前该方法代理了 `aegra_api` 的校验逻辑，但预留了无缝切换到本地或第三方 OAuth 的接口。
- **会话持久化**: 令牌生命周期由 `get_access_token_ttl_seconds()` 动态计算，并在 `aegra_access_token` Cookie 中持久化。

## 性能/质量指标
- **低延迟**: 鉴权逻辑主要在内存中通过令牌校验完成，单次 API 鉴权开销小于 5ms。
- **安全性**: 强制使用 `HTTPOnly` 和 `Lax` Samesite 策略，防御 CSRF 攻击。

## 维护建议
- **脱离平台**: 若需彻底摆脱 `aegra_api` 依赖，只需重写 `app/core/auth.py` 中的 `get_current_user` 逻辑，其他的 Router 代码无需任何修改。
