# Docker 沙盒运行时与调试接口使用指南

本文档说明你当前这版 Web 开发智能体（`build_app_agent`）如何使用 Docker 沙盒自动运行代码、自动诊断错误，以及如何通过自定义 API 拉取运行时信息做调试。

## 1. 功能总览

你现在已有的核心能力：

- 代码生成后自动检测 `package.json` 并尝试启动服务
- 自动识别包管理器（`npm/pnpm/yarn`）和常见框架（`vite/next/nuxt/cra/astro`）
- 自动探测端口映射与 HTTP 可达性
- 自动抽取日志错误并注入给 Agent（用于自愈）
- 提供运行时调试接口：
  - `GET /custom/sandbox/threads/{thread_id}/runtime`
  - `GET /custom/sandbox/threads/{thread_id}/debug`

---

## 2. 关键代码位置

- Agent 配置：`graphs/build_app_agent/agent.py`
- Docker 生命周期与诊断逻辑：`middleware/docker.py`
- 自定义调试 API：`app/main.py`
- E2E 测试：`tests/e2e/test_custom_routes/test_sandbox_debug_e2e.py`

---

## 3. 运行前准备

### 3.1 配置项确认

确保 `aegra.json` 中包含：

```json
{
  "graphs": {
    "build_app_agent": "./graphs/build_app_agent/agent.py:agent"
  },
  "http": {
    "app": "./app/main.py:app",
    "enable_custom_route_auth": true
  }
}
```

### 3.2 启动服务

```bash
docker compose up postgres -d
uv run uvicorn src.agent_server.main:app --reload
```

如果你是 Docker 方式跑 Aegra，也可用项目现有 compose 启动。

---

## 4. Agent 自动运行机制说明

`DockerMiddleware` 每轮关键流程（见 `middleware/docker.py`）：

1. 复用线程绑定容器（不存在则创建）
2. 检查是否 Node 项目（`package.json`）
3. 选择包管理器并安装依赖（若 `node_modules` 缺失）
4. 选择启动脚本（`dev > start > preview`）
5. 按框架拼接启动参数（例如 Next 用 `--hostname`，Vite 用 `--host`）
6. 后台启动服务并写入：
   - PID: `/tmp/agent-web.pid`
   - 日志: `/tmp/agent-web.log`
7. 检查进程存活、端口映射、HTTP 探测结果
8. 若有错误，生成 Runtime Diagnostics 注入给 Agent

---

## 5. Runtime 接口使用

### 5.1 获取单线程运行时状态

`GET /custom/sandbox/threads/{thread_id}/runtime`

常用 Query 参数：

- `log_lines`: 返回日志行数（20-500）
- `errors_only`: 是否只返回错误行
- `include_container_details`: 是否返回容器安全信息
- `include_state_values`: 是否包含完整 LangGraph state

示例：

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/custom/sandbox/threads/<thread_id>/runtime?log_lines=80&errors_only=false&include_container_details=true"
```

关键返回字段：

- `service_status`: 中间件结构化运行状态
- `runtime_excerpt`: 日志摘要（便于 UI 展示）
- `container_details`: 容器安全信息（可选）
- `last_diagnostic_fingerprint`: 当前诊断指纹（用于去重）

---

## 6. Debug 聚合接口使用

### 6.1 一次性获取线程调试数据包

`GET /custom/sandbox/threads/{thread_id}/debug`

常用 Query 参数：

- `runs_limit`: 最近 runs 数（1-20）
- `events_limit`: 每个 run 最近事件数（1-50）
- `log_lines`: 日志行数（20-500）
- `errors_only`: 仅返回错误日志摘要
- `include_container_details`: 包含容器安全信息

示例：

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/custom/sandbox/threads/<thread_id>/debug?runs_limit=5&events_limit=10&errors_only=true"
```

返回结构包含：

- `thread`: 线程元信息
- `runtime`: 当前运行态（与 `/runtime` 对齐）
- `runs`: 最近 run + 事件错误摘要
- `summary`: 汇总统计（错误 run 数、是否存在 runtime 诊断等）

---

## 7. 前端/平台对接建议

建议前端调试面板调用顺序：

1. 轮询 `/runtime` 显示实时状态卡片（服务存活、端口、HTTP 探测）
2. 打开“故障详情”时调用 `/debug` 展示最近 run/events
3. 若 `summary.has_runtime_diagnostic=true`，高亮提示“Agent 正在自修复”

推荐状态优先级：

- `startup_error` 存在 -> 高优先级错误
- `service_running=false` -> 服务未启动
- `preview_probes` 全部 `error:*` -> 预览不可达
- `error_lines` 非空 -> 运行期异常

---

## 8. E2E 验证方式

新增测试文件：

- `tests/e2e/test_custom_routes/test_sandbox_debug_e2e.py`

执行：

```bash
uv run pytest tests/e2e/test_custom_routes/test_sandbox_debug_e2e.py -v
```

说明：

- 未设置 `E2E_AUTH_TOKEN` 时，认证链路用例会 `skip`
- 如果网关对 `/openapi.json` 临时返回 5xx，该用例会 `skip`（避免环境误报）

认证全链路验证：

```bash
E2E_AUTH_TOKEN="<你的token>" \
uv run pytest tests/e2e/test_custom_routes/test_sandbox_debug_e2e.py -v
```

---

## 9. 常见问题排查

### 9.1 接口返回 401

- 检查 `aegra.json` 是否启用 `enable_custom_route_auth`
- 使用正确 Bearer Token 调用 `/custom/*` 接口

### 9.2 `service_running=false`

- 查看 `/runtime` 的 `runtime_excerpt`
- 重点看 `startup_error` 与 `error_lines`
- 检查项目是否有可执行脚本（`dev/start/preview`）

### 9.3 端口有映射但预览打不开

- 查看 `preview_probes` 是否全部 `error:*`
- 检查框架参数是否正确（例如 Next 是否绑定 `0.0.0.0`）

### 9.4 调试信息缺失

- 确认 thread 已绑定 `graph_id`
- 确认该 thread 曾触发过 run

---

## 10. 变更建议（后续可选）

- 给 `/debug` 增加 `status_filter`（仅看 error/timeout run）
- 给 `/runtime` 增加健康分级字段（`healthy/warning/error`）
- 在 UI 加“自动修复轨迹”时间线（基于 `last_diagnostic_fingerprint` 变化）
