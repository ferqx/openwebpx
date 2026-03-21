# 测试与质量保障体系

本项目建立了多维度的测试体系，旨在确保 AI 协作链路的稳定性和 UI 交互的正确性。

## 1. 测试层级

### 单元测试 (`test/lib/`, `test/hooks/utils.test.ts`)
- **目标**: 验证纯逻辑函数、数据处理函数。
- **工具**: Node.js 内置 Test Runner + `tsx`。
- **重点**:
  - `scm.test.ts`: 验证 OAuth 回调处理、Provider 解析。
  - `thread-chat-utils.test.ts`: 验证消息规格化、Token 统计。

### Hooks 测试 (`test/hooks/*.test.ts`)
- **目标**: 验证自定义 Hooks 的生命周期、副作用与状态变化。
- **工具**: React Hooks Testing Library 风格的自定义实现。
- **重点**:
  - `use-thread-chat.test.ts`: 验证消息提交与流式状态更新。
  - `use-portal-scm-connections.test.ts`: 验证授权中心的探测流程。

### 端到端测试 (E2E) (`e2e/tests/`)
- **目标**: 模拟用户真实交互流程。
- **工具**: Playwright。
- **重点**:
  - `smoke.spec.ts`: 验证核心页面访问、登录与导航。
  - `thread-chat.spec.ts`: 验证从门户发起任务到进入详情页的完整链路。
  - `portal.spec.ts`: 验证任务列表的搜索与删除功能。

## 2. 测试执行命令

### 逻辑与 Hooks 测试
```bash
# 运行所有 Hooks 测试
pnpm test:hooks
# 运行所有 Lib 逻辑测试
pnpm test:lib
```

### E2E 交互测试
```bash
# 运行所有 E2E 测试
pnpm test:e2e
# 运行特定项目的测试
pnpm test:e2e -- --project=chromium
```

## 3. 质量指标与防回归
- **状态转换验证**: 重点测试任务状态从 `starting` 到 `running` 再到 `completed` 的转换正确性。
- **错误边界**: 验证 SCM 授权失败、网络中断时的 UI 降级表现。
- **数据一致性**: 确保门户列表状态与详情页实时会话状态保持一致。
