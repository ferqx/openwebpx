# 代码审查模块 (Code Review)

## 简介
代码审查模块（主要实现在 `app/routers/code_review.py`）是 OpenWebPX 实现 CI/CD 环节自动化的核心组件。该模块通过接收 SCM 平台的 Webhook 通知，自动触发 Agent 对 Pull Request (PR) 或 Merge Request (MR) 的增量代码进行审查，并将审查建议以行级评论的形式回馈给开发者。

## 功能详情
- **Webhook 触发机制**:
  - 支持 GitHub `pull_request` 和 `push` 事件。
  - 支持 GitLab `Merge Request Hook` 和 `Push Hook` 事件。
  - 支持 Webhook 签名校验（`x-hub-signature-256`, `x-gitlab-token`），保证来源可靠。
- **配置管理 (Profiles)**:
  - 用户可以为特定仓库或全局开启/关闭自动审查（`auto_review_enabled`）。
  - 支持按不同的事件触发模式（`pr_open` 或 `push`）进行个性化配置。
- **差异解析与增量审查**:
  - 精确解析 `diff` 变更，仅对新增或修改的代码行进行审查，避免干扰存量代码。
  - 自动提取“可评论行号”，确保 AI 生成的评论能精准锚定在 SCM 界面的对应行。
- **异步任务编排**:
  - 采用基于 LangGraph 的异步 `run` 机制。
  - 审查任务执行完成后，自动触发回调并将结果回传至 SCM 平台。

## 技术实现
- **Webhook 处理器**: 通过 `_resolve_webhook_event_context` 统一封装不同平台的 Payload 格式，抽象为标准的 `WebhookEventContext`。
- **幂等性控制**: 使用 `code_review_webhook_deliveries` 表对 Webhook 进行去重（`delivery_key`），防止同一事件因网络重试导致多次重复审查。
- **行级评论生成**: Agent 输出结构化的 JSON 格式评论（`review-comments-json`），由 `_publish_review_comments_after_run` 解析并调用 SCM API 进行发布。
- **数据结构**:
  - `code_review_profiles`: 存储用户全局审查偏好。
  - `code_review_repo_settings`: 存储特定仓库的覆盖配置。

## 性能/质量指标
- **准确性**: AI 评论仅限定在 diff 中的 `+` 行，有效降低由于行号偏移导致的评论错位风险。
- **并发性**: 支持多用户并发 Webhook 投递，异步任务完全解耦，不阻塞 Webhook 响应。
- **可靠性**: 具备完善的发布状态记录（`review_comment_publish`），便于在元数据中追溯评论发布是否成功。

## 维护建议
- **公网暴露**: 确保 `OPENWEBPX_PUBLIC_BASE_URL` 配置正确，否则 SCM 平台将无法正常回调 Webhook。
- **Secret 密钥管理**: 建议为 GitHub 和 GitLab 分别设置专有的 Webhook Secret 以增强安全性。
- **限流控制**: 若单仓库 PR 更新频率极高，建议在 SCM 端合理设置触发条件（如仅在 Open 或 Synchronize 时触发）。
