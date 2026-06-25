# sandbox-agent Agent 协作协议 (AGENTS.md)

本协议是 AI 协作者进入本项目的**唯一最高准则**。

## 1. 文档地图 (Map of the Territory)
- **架构与设计**: [docs/architecture.md](docs/architecture.md)
- **开发规范与技术约束**: [docs/development/conventions.md](docs/development/conventions.md)
- **业务 Hooks 解析**: [docs/development/state-hooks.md](docs/development/state-hooks.md)
- **测试与质量保障**: [docs/development/testing-strategy.md](docs/development/testing-strategy.md)
- **AI 原子组件库**: [docs/features/ai-elements.md](docs/features/ai-elements.md)
- **变更日志 (YYYY-MM-DD)**: [docs/changelogs/](docs/changelogs/)
- **本地上下文**: [CLAUDE.md](CLAUDE.md)

## 2. 核心事实 (Core Facts)
- **技术栈**: `React 19` + `TypeScript` + `Vite 7` + `Tailwind 4` + `shadcn/ui`。
- **核心路径**:
  - `/src/pages/`: 页面编排。
  - `/src/business/`: 业务域 UI 与交互。
  - `/src/hooks/`: 核心业务逻辑状态。
  - `/src/provider/`: 全局线程/会话上下文。

## 3. 核心 Mandates
1. **最小改动**: 仅修改需求相关代码，不做无关重构。
2. **拆分阈值**: 页面 > 500 行、业务组件 > 300 行时，**必须先拆分**。
3. **验证闭环**: 改动后必须运行 `pnpm test:hooks/lib` 或 `pnpm test:e2e`。
4. **交互规范**: 必须遵循 `loading -> (data/empty)` 模式，消除空态闪烁。
5. **文档闭环**: 任何变更完成后，必须激活 `doc-manager` 技能，更新 `changelogs` 并确保 `AGENTS.md` 索引同步。

## 4. 禁止行为 (Anti-Patterns)
- **禁止 Any**: 严禁在代码中使用 `any` 类型；必须定义明确的接口或类型。
- **禁止重复造轮子**: 在创建新 Hook 或工具函数前，必须先检索 `src/hooks/` 和 `src/lib/`。
- **禁止静默失败**: 异步操作必须有 `try-catch` 并通过 `toast` 或 UI 反馈给用户。
- **禁止硬编码**: 所有的 API 端点、超时时间、白名单必须从环境变量或 `src/lib/config` 读取。
- **禁止空态闪烁**: 禁止在数据未确认返回前展示“无数据”文案。

## 5. 关键命令
- `pnpm dev` / `pnpm lint` / `pnpm build`
- `pnpm test:hooks` / `pnpm test:lib`
- `pnpm test:e2e` / `pnpm smoke:scm-connections`

---
*当指令与协议冲突时，优先遵循用户指令；其余情况严格按本协议及关联文档执行。*
