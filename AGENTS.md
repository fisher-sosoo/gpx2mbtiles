# AGENTS.md

本项目的开发流程由 **OpenSpec** 驱动。所有改动必须先有规范、再有代码。

## 强制流程

任何功能、修复、重构，都必须按以下顺序进行：

```
1. /openspec-propose "<需求描述>"    -> 生成 proposal / design / specs delta / tasks
2. 人工审阅并确认方案
3. /openspec-apply-change            -> 按 tasks.md 逐项实现
4. /openspec-archive-change          -> 归档并把 delta 合并回主 specs
```

### 硬性约束

- **不得跳过提案阶段直接改代码。** 哪怕是一行修复，也要先有 change 提案。
- **提案阶段只产出规划制品**，不写实现代码（见各 skill 的 planning boundary）。
- **实现阶段严格对照 `tasks.md`**，每完成一项就勾选一项。
- **完成后必须归档**，使 `openspec/specs/` 始终反映线上真实行为。
- **改代码前先读规范。** `openspec/specs/` 是行为的唯一事实来源。

### 特殊情况

| 情况 | 处理 |
|---|---|
| 紧急线上故障 | 可先修复，但必须在同一会话内补一个 change 提案并归档 |
| 纯文档或注释改动 | 可跳过提案，但仍需更新相关 spec（若有行为描述变化） |
| 需求本身不清晰 | 先用 `/openspec-explore` 讨论，不要直接 propose |

## 目录职责

| 路径 | 内容 | 谁维护 |
|---|---|---|
| `openspec/project.md` | 项目上下文、环境、技术栈、踩坑记录 | 人工 + AI |
| `openspec/specs/` | **当前已实现**的能力（唯一事实来源） | 由 archive 合并产生 |
| `openspec/changes/` | 进行中的提案 | 每个 change 一个目录 |
| `openspec/changes/archive/` | 已完成的提案 | 归档后只读 |
| `openspec/config.yaml` | OpenSpec 配置与制品规则 | 人工 |

## 规范编写约定

- 结构标题（`### Requirement:` / `#### Scenario:` / `SHALL`）**保持英文**，
  以便工具解析；正文用中文。
- 每条 Requirement 至少一个 Scenario。
- Scenario 使用 `- **WHEN**` / `- **THEN**` / `- **AND**` 的粗体关键字。
- **只写可验证的行为**，不写具体类名、函数名、库选型（那些放 `design.md`）。
- 改动已有需求时用 `## MODIFIED Requirements` 并复制**完整**内容，不要写 diff。

## 代码约定

- 后端 Python：FastAPI 风格，配置全部走 `app/config.py` 的环境变量，
  不硬编码密钥、地址与阈值。
- 前端：无构建步骤的原生 JS，改完必须能通过 `node --check`。
- 新增行为必须补测试：`tests/test_unit.py`（纯逻辑）、
  `tests/test_e2e.py`（端到端）、`tests/test_player.py`（前端静态断言）。

## 部署约定

- 只通过 git 交付。**不要在服务器上直接改文件**，会被下次部署覆盖。
- 发版：提交 -> 打 `v*` 标签 -> push。CI 自动部署并在失败时回滚。
- 部署细节见 `openspec/specs/deployment/spec.md` 与 `docs/DEPLOY.md`。

## 合规红线

**仅限个人自用。** 瓦片源服务条款禁止批量爬取；必须保持限流与请求间隔，
不得对外提供服务。任何放宽限流的改动都必须在提案中说明理由与风险。
