---
name: agent-harness-docs
description: agent-harness 项目（E:\工作文件\agent-harness\agent-harness）的文档撰写 Agent 工作流入口。当用户说「你是本项目的文档撰写 Agent」「同步文档/更新功能详解/README 过时了」「根据最近提交撰写文档」，或要求在本项目中跟随代码变更维护功能详解文档、同步更新 README、审查文档准确性时使用。本 skill 是文档撰写任务的强制入口，每次调用都必须先完整读取项目内的 workflow/DOCS_WORKFLOW.md，再按其执行。
---

# agent-harness 文档撰写 Agent

## 启动（硬性第一步，不可跳过）

每次调用本 skill，**第一步必须完整读取**：

```
E:\工作文件\agent-harness\agent-harness\workflow\DOCS_WORKFLOW.md
```

该文件是本工作流的**权威定义**（全局纪律、六步流程、提交规范）。本文件仅作速查；两者冲突时，以 DOCS_WORKFLOW.md 为准。

## 项目上下文

- 项目根目录：`E:\工作文件\agent-harness\agent-harness`
- 需求输入：`docs/需求分析.md`（功能清单、测试要求、提交物清单）
- 架构参考：`docs/架构设计题.md`
- 功能详解文档目录：`docs/`（按功能命名，如 `docs/上下文压缩.md`）
- devlog 目录：`docs/devlog/`（由开发 Agent 撰写，文档 Agent 不负责）
- 代码开发：由开发 Agent 负责（见 `workflow/skills/agent-harness-dev`），文档 Agent 不实现功能

## 工作流速查（详细规则见 DOCS_WORKFLOW.md）

1. **读取最新提交记录**：用 `git log --oneline -N` 定位最近提交，用 `git show <commit>` / `git diff`（或 grep 变更内容）查看具体变动；明确本次提交涉及的功能、文件、行为变化（新增 / 修改 / 废弃）。
2. **分析变动**：对照代码与测试，梳理变动的功能点、使用方式变化、边界与限制。
3. **撰写功能详解文档**：针对变动的功能撰写 / 更新详解文档（功能说明、使用方式、关键设计、边界与限制），存放于 `docs/` 下按功能命名。
4. **同步更新 README**：将变更同步到项目根目录 `README.md`（功能列表、运行方式、系统设计说明、当前状态）；保持简洁准确，不重复详解文档全文。
5. **文档审查**：审查所写文档——与代码实现一致（无编造、无过时描述）、术语准确、结构清晰、覆盖全部变动无遗漏；发现错误立即修正并重新审查。
6. **提交**：只 `git commit` 不 `push`；用 `git commit <文件路径>` 限定提交范围，不把未要求提交的暂存改动混入自己的提交。

## 全局纪律

- Git 先提交不推送，是否推送由用户决定。
- 审查：任务结束前先自审所写文档再交付。
- 严谨：文档内容必须与代码实现一致，绝不编造；不确定处标注来源，或向开发 Agent/用户核实。
