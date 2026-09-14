# 过程进度显示增强 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 让图片识别等待期间持续显示具体阶段和等待时间。

**Architecture:** 沿用现有 SSE，在 agent 的耗时节点发送公开 status 事件；前端在处理记录中加时间戳和动态等待计时。保持 API 返回结构不变，不展示原始 thinking。

**Tech Stack:** Python、FastAPI、SSE、原生 JavaScript、pytest。

## Global Constraints

- 只显示可验证的程序阶段，不显示模型隐性推理内容。
- 保持现有 API 响应结构和会话逻辑兼容。

### Task 1: 后端过程事件

**Files:** Modify `app/agent.py`; Test `tests/test_progress.py`.

- [ ] 增加关键节点 status 事件。
- [ ] 测试事件顺序和阶段字段。

### Task 2: 前端计时日志

**Files:** Modify `app/static/app.js`, `app/static/styles.css`.

- [ ] 日志显示相对时间。
- [ ] 识别期间每秒更新等待提示，完成或错误时清理。

### Task 3: 验证、提交与发布

- [ ] 运行 `python -m pytest -q`。
- [ ] 提交并推送当前分支。
- [ ] 运行 `python scripts/deploy_remote.py`，检查远程 `/api/health`。
