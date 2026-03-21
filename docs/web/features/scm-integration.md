# SCM 集成与授权

## 1. 支持的 SCM 提供商
- **GitHub**: 使用 GitHub App 模式进行授权。
- **GitLab**: 使用 GitLab OAuth2 模式。
- **GitLab Enterprise**: 支持私有部署的 GitLab，需提供 Base URL。

## 2. 授权流程 (OAuth)
1. 门户面板发起“连接 SCM”。
2. 前端请求后端 `GET /integrations/scm/authorize`。
3. 后端重定向用户至 SCM 提供商授权页。
4. 授权成功后，跳转回 `/oauth/scm/callback`。
5. 前端在回调页提交 `code` 和 `state` 给后端，获取 Access Token。
6. 后端持久化 Access Token，授权成功。

## 3. 连接中心 (Connections Center)
- **真源原则**: 授权状态由后端接口 `/integrations/scm/connections` 返回，前端不使用本地存储存储授权标志。
- **探测模式**: 优先探测已知授权来源。若后端未授权，则提示用户连接。

## 4. 仓库拉取与分支选择
- 授权成功后，后端可以拉取用户有权限的仓库列表。
- 选择仓库后，前端实时加载远程分支供用户选择。
- 仓库名和分支名将作为 `metadata` 存入 `thread`，用于后续环境拉取代码。
