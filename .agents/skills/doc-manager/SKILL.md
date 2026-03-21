---
name: doc-manager
description: 全栈文档管理与 Agent 协议守护者。负责维护 AGENTS.md, CLAUDE.md, docs/ (backend/web/changelogs/)。确保前后端变更同步，并核对全栈开发约束。
---

# 全栈 doc-manager 技能

本技能专门用于维护 OpenWebPX Monorepo 的全栈文档体系与开发协议。

## 1. 触发场景
- **全栈特性开发后**: 必须更新 `docs/changelogs/YYYY-MM-DD.md`，包含后端 API 变动与前端接入逻辑。
- **API 契约变更后**: 必须更新 `docs/api-contract/` 并核对前端 Types 稳定性。
- **架构演进**: 维护 `docs/architecture.md`，确保全栈调用图准确。

## 2. 核心工作流

### A. 全栈变更日志 (Full-Stack Changelog)
1. **收集信息**: 汇总本次任务的 Backend (app/, graphs/) 与 Frontend (web/) 的所有改动。
2. **更新日志**: 在 `docs/changelogs/YYYY-MM-DD.md` 中按“功能模块”记录全栈影响。
3. **核对协议**: 确认改动符合 `AGENTS.md` 中的全栈 Mandates。

### B. 架构与契约维护 (Contract & Architecture)
1. **API 校验**: 若修改了后端路由，必须同步检查并更新前端 `web/src/types/api/`。
2. **逻辑下沉**: 检查后端逻辑是否已合理下沉至 `app/services`，前端组件是否违反拆分阈值 (500/300)。

### C. 协议核对 (Mandates & Anti-Patterns)
1. **禁令核对**: 严禁 `any`，严禁硬编码，严禁空态闪烁。
2. **真源核对**: SCM 状态必须以后端 connections 接口为准。

## 3. 禁令与反模式
- **禁止单一视角**: 严禁在全栈功能交付时仅记录单端日志。
- **禁止空态闪烁**: 异步加载期间严禁在 UI 展示“无数据”。
- **禁止逻辑孤岛**: 严禁创建不被根目录 `AGENTS.md` 索引的新文档文件。
