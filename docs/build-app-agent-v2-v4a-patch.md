# Build App Agent V2：V4A 补丁机制说明

本文档记录 `build_app_agent_v2` 在 2026-03-01 引入的结构化补丁机制，目标是避免同一文件连续微调（thrashing），提高一次性修改成功率。

## 1. 适用范围
- 图 ID：`build_app_agent_v2`
- 主要实现文件：
  - `graphs/build_app_agent_v2/agent.py`
  - `graphs/build_app_agent_v2/prompts.py`
  - `graphs/build_app_agent_v2/guard_middleware.py`
  - `graphs/build_app_agent_v2/v4a_filesystem_middleware.py`

## 2. 核心行为
- 写入工具从 `edit_file` 转为 `apply_patch`（V4A 格式）。
- `apply_patch` 支持 `dry_run`：仅校验补丁可匹配性，不落盘。
- `apply_patch` 返回结构化结果（JSON 字符串）：`ok / error_code / message / details / retryable`。
- 写入前新增 `submit_edit_plan` 计划门禁（Plan-then-Act）。
- 同一文件相关改动要求在一次 `apply_patch` 中合并提交。
- 默认门禁（可通过环境变量覆盖）：
  - 单轮同一文件最多写入 1 次
  - 单次运行同一文件最多写入 2 次（初次 + 修复）
- 目录探索限流（减少低效 `ls` 循环）：
  - 限制 `ls` 总调用次数
  - 限制同一路径的重复 `ls` 次数
  - 限制同一目录前缀（子树）下的连续 `ls` 深挖次数（防止 `src -> src/a -> src/a/b` 连环遍历）
  - 超限后引导改用 `read_file` / `grep` / `glob`
- 工具能力升级（降低工具调用次数）：
  - 新增 `submit_edit_plan`：写入前提交完整计划（`plan_summary` + `target_files`）。
  - 新增 `list_components`：组件库清单场景优先工具（默认扫描 `*/index.ts`）。
  - 新增 `read_files`：多文件上下文批量读取，替代连环 `read_file`。
  - 新增 `list_resources`：统一资源发现入口（返回 resource URI）。
  - 新增 `get_implementation`：按符号定位实现候选并返回 `symbol://` 资源 URI。
  - 新增 `find_callers`：按符号定位调用方并返回 `callers://` 资源 URI。
  - 新增 `read_resource`：按 URI/绝对路径读取资源内容（文件资源优先）。
  - `read_resource` 扩展支持：`symbol://...`、`callers://...`（除 `file://` 外）。
  - `read_file` 调整为单文件补充读取，已知多文件场景优先 `read_files`。
- `glob` 防卡策略（避免工具阶段卡死）：
  - 禁止在根路径 `/` 上执行 `glob`
  - 拦截过宽模式：`*`、`*.*`、`**`、`**/*`、`**/*.*`
  - 限制 `glob` 总调用次数与同路径重复调用次数
  - `list_resources` 复用同一 discovery 预算与模式拦截（按 `scope/pattern` 映射）
  - 超限后引导改用 `read_file` / `grep`
- 响应降噪策略（减少冗余“过程播报”）：
  - 系统提示词增加“工具阶段默认静默 + 最终答复短格式”约束。
- 图执行架构升级：
  - `build_app_agent_v2` 由单 `create_agent` 迁移为显式 `StateGraph` 两阶段：
    - `plan` 节点（只读工具集，移除 `apply_patch/write_file/execute`）
    - `act` 节点（完整工具集，执行写入与验证）
  - 实现 Plan/Act 物理隔离，不再仅依赖提示词约束。
- 运行态可观测性增强：
  - `/sandbox/threads/{thread_id}/runtime` 直接返回 `tool_guard_summary`。
  - 优先透传中间件写入的摘要；若 checkpoint 仍是旧格式，则自动从 legacy guard counters 回填统一结构。
- 前端资源 API（BFF）：
  - `GET /sandbox/threads/{thread_id}/resources`：按 `scope/pattern` 列表资源，返回 `file://` URI。
  - `GET /sandbox/threads/{thread_id}/resources/read`：按 URI/绝对路径读取单个资源内容。
  - 接口沿用与 guard 一致的 discovery 约束：禁止 root scope 与过宽 pattern。

相关环境变量：
- `BUILD_APP_AGENT_V2_MAX_GLOB_CALLS_TOTAL`（默认 `4`）
- `BUILD_APP_AGENT_V2_MAX_GLOB_CALLS_PER_PATH_TOTAL`（默认 `2`）
- `BUILD_APP_AGENT_V2_MAX_LS_CALLS_TOTAL`（默认 `4`）
- `BUILD_APP_AGENT_V2_MAX_LS_CALLS_PER_PATH_TOTAL`（默认 `2`）
- `BUILD_APP_AGENT_V2_MAX_LS_CALLS_PER_ROOT_TOTAL`（默认 `3`，同一目录前缀子树遍历上限）
- `BUILD_APP_AGENT_V2_ENABLE_COMPACT_RESPONSE`（默认 `true`，开启提示词层简洁输出约束）
- `BUILD_APP_AGENT_V2_ENABLE_DISCOVERY_GUARD`（默认 `false`；关闭 `ls/glob` 拦截，改为提示词+工具约束优先）
- `BUILD_APP_AGENT_V2_REQUIRE_PLAN_BEFORE_WRITE`（默认 `true`；强制 `submit_edit_plan -> apply_patch`）

## 3. V4A 格式要求
单次 `patch_content` 可包含多个文件段：

```text
*** Update File: /absolute/path
@@ scope-or-label
 context_before
-old_line
+new_line
 context_after
```

支持操作：
- `*** Add File: /absolute/path`
- `*** Update File: /absolute/path`
- `*** Delete File: /absolute/path`

约束：
- 同一文件只能出现一个 `*** Update File` 段（多处改动用多个 `@@` hunk）。
- 路径必须为绝对路径。
- 解析失败、定位失败或命中歧义时，必须显式报错，不静默忽略。
- 补丁提交采用“先校验后提交”流程；提交阶段失败时执行回滚，避免部分文件已写入。

## 4. Insert-only hunk（仅插入）规则
`Update File` 下允许纯插入 hunk（仅 `+`、无 `-`），但必须满足：
- 至少提供一个锚点上下文：`context_before` 或 `context_after`。
- 锚点命中必须唯一；0 命中或多命中均报错。

## 5. 回归测试
测试文件：`tests/test_build_app_agent_v2_v4a_patch.py`

当前覆盖点：
- 多 hunk 更新应用
- 重复文件段拒绝
- insert-only（context_before）成功
- insert-only（context_after）成功
- insert-only 无上下文报错
- `V4AFilesystemMiddleware` 工具替换检查
- guard 对 `apply_patch` 的文件路径提取
- `glob` root 路径拦截
- `glob` 过宽模式拦截
- `glob` 同路径重复调用拦截
- `glob` 总调用次数超限拦截
- `list_resources` 的 scope/pattern 预算映射与拦截
- 新 AST 资源工具：`get_implementation` / `find_callers`
- `read_resource` 读取 `symbol://` 扩展 URI
- `ls` 子树连环遍历拦截
- compact prompt 开关行为
- 写入前计划门禁：无计划写入拦截、计划文件集校验
- 新工具注入：`read_files` / `list_components`
- 新工具注入：`list_resources` / `read_resource`
- `apply_patch` dry-run 不落盘
- `apply_patch` 提交中途失败回滚（避免部分提交）
