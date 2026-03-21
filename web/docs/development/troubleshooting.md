# 故障排除 (Troubleshooting)

## 1. SCM 授权与连接问题

### 1.1 `GitHub auth_mode 仅支持 github_app` (400)
- **现象**: 后端连接中心接口返回 400。
- **原因**: 历史数据可能包含 `auth_mode: oauth` 的脏数据。
- **解决**: 后端需做兼容性映射，前端应能识别此错误并降级到探测模式。

### 1.2 `OAuth state 无效或已过期`
- **现象**: 回调页提交后报错。
- **原因**: 通常是由于 React `StrictMode` 导致的 `useEffect` 双重触发，使得同一 `code` 被提交了两次。
- **解决**: 在前端对同一组 `state + code` 做一次性提交拦截，后端需确保证 `redirect_uri` 与 `origin` 逐字符匹配。

### 1.3 重启后端后授权丢失
- **原因**: 后端未真实持久化 `scm_tokens` 到数据库（曾仅在内存中缓存）。
- **解决**: 检查后端数据库持久化逻辑。

## 2. 线程取消与环境恢复

### 2.1 无法取消运行中的任务 (Stop 按钮无效)
- **原因**: 旧逻辑依赖 `run_id` 才能取消，如果 `run_id` 未生成或前端丢失则无法取消。
- **解决**: 项目已升级为“优先 thread 级取消”，前端通过 `POST /sandbox/threads/{thread_id}/cancel` 触发。

### 2.2 工具调用阶段复制按钮位置错误
- **解决**: 在 `getCopyMetaList` 中已限制复制目标仅限 `assistant` 的最终消息。

## 3. 页面渲染与空态

### 3.1 页面加载时闪烁“无数据”
- **准则**: 异步加载期间严禁展示“空态”。应先展示 Loading/骨架屏，待接口明确返回空列表后再展示 Empty 态。

## 4. 排障排查顺序 (AI 排障建议)
1. 检查后端接口 `/integrations/scm/connections` 是否 200。
2. 检查后端 `scm_tokens` 是否持久化。
3. 检查授权回调是否重复提交。
4. 检查 GitLab 的 `redirect_uri` 是否与前端 `origin` 完全一致。
