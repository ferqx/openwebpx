# 开发指南

## 1. 技术栈说明
- **前端框架**: React 19 (使用了 React Compiler)。
- **样式**: Tailwind CSS 4。
- **构建工具**: Vite 7。
- **Linting**: ESLint (Flat Config) + TypeScript ESLint。

## 2. 组件使用规范 (Shadcn UI)
项目已封装 50+ 基础 UI 组件 (位于 `src/components/ui`)：
- **固定选项**: 使用 `Select`。
- **可搜索选项**: 优先使用 `Combobox` (或 `Command` + `Popover`)。
- **表单输入**: `Input` / `Textarea` / `Field`。
- **弹层**: `Dialog` (阻断式交互), `Popover` (轻量补充), `DropdownMenu` (菜单动作)。

## 3. 本地自测与冒烟检查 (Smoke Tests)
在提交代码前，建议运行以下脚本验证关键功能：

### SCM 连接检查
```bash
pnpm smoke:scm-connections --provider github
```

### 线程取消检查
```bash
pnpm smoke:thread-cancel --thread-id <thread_id>
```

### 端到端 (E2E) 测试
基于 Playwright，验证核心页面渲染、登录重定向及基础交互。
```bash
# 运行所有 E2E 测试
pnpm test:e2e
# 可视化调试
pnpm test:e2e:ui
```

## 4. 样式与布局准则
- 优先使用组件默认样式，避免深度覆盖。
- `className` 仅用于布局 (Flex/Grid/Gap) 和间距控制。
- 禁止在页面内重复实现组件已有的基础功能。
