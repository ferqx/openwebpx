# Sandbox 线程卡死恢复与取消

本文档记录 2026-03-01 新增的线程级取消接口，用于处理“线程卡住且前端拿不到 run_id 无法取消”的场景。

## 1. 适用问题
- 线程状态长期停留在 `busy`。
- 已知 `thread_id`，但无法拿到当前活跃 `run_id`。
- bootstrap 任务仍在后台挂起，导致线程无法恢复。

## 2. 新增接口
- 路径：`POST /sandbox/threads/{thread_id}/cancel`
- 鉴权：与其他 sandbox 接口一致，要求登录用户且仅可操作自己的线程。
- 参数：
  - `action`（query，可选）：`cancel` 或 `interrupt`，默认 `cancel`。

## 3. 行为说明
- 自动取消该线程下状态为 `pending` / `running` 的 run（无需前端提供 run_id）。
- 若 bootstrap 后台任务存在且未结束，会一并取消。
- 将命中的 run 状态统一写回为 `interrupted`。
- 将线程状态回收为 `idle`，避免线程长时间“假 busy”。
- 若 bootstrap 状态为运行中，会写入取消日志并将状态切回 `idle`。

## 4. 返回字段（核心）
- `cancelled_run_ids`: 实际命中的 run_id 列表。
- `cancelled_run_count`: 命中数量。
- `cancel_signal_failures`: 发送取消信号失败的 run_id（状态仍会被回收为 `interrupted`）。
- `bootstrap_task_cancelled`: 是否取消了 bootstrap 异步任务。
- `thread_status`: 回收后的线程状态（预期为 `idle`）。

## 5. 示例
```bash
curl -X POST "http://localhost:8000/sandbox/threads/th-123/cancel?action=interrupt" \
  -H "Authorization: Bearer <token>"
```

## 6. 已知日志噪声（2026-03-01）
- 取消或结束 run 后，偶发会出现：
  - `Attempted to put event ... into finished broker for run ...`
- 该告警通常是“已结束 run 的晚到事件”引起，不影响最终取消结果。
- 项目已在启动路径安装过滤器，仅抑制这条特定告警，其他 broker 告警仍保留。
