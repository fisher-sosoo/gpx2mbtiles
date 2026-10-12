# 任务管理

## Purpose

服务端下载瓦片是长时间运行的作业。本章规定任务的生命周期、
并发控制、状态持久化与资源清理，保证服务重启或页面关闭都不丢账。

## Requirements

### Requirement: 任务账本持久化

系统 SHALL 把任务状态持久化到 SQLite，服务重启后不丢失。

#### Scenario: 服务重启后恢复账本

- **WHEN** 服务重启
- **THEN** 已完成的任务 SHALL 仍可在历史列表中查询与下载
- **AND** 运行中的任务 SHALL 被重置为排队状态

### Requirement: 并发任务上限

系统 SHALL 限制同时运行的任务数，避免耗尽服务器资源。

#### Scenario: 达到并发上限

- **WHEN** 运行中的任务数已达 `MAX_RUNNING_TASKS`
- **THEN** 系统 SHALL 拒绝新任务并返回 429
- **AND** SHALL 给出可读说明

### Requirement: 任务超时自动终止

系统 SHALL 终止运行超过时限的任务。

#### Scenario: 超过任务时限

- **WHEN** 任务运行超过 `TASK_TIMEOUT_SECONDS`（默认 3600 秒）
- **THEN** 系统 SHALL 终止该任务
- **AND** SHALL 把状态标记为失败并记录原因

### Requirement: 任务取消

系统 SHALL 允许用户主动取消运行中的任务。

#### Scenario: 用户取消

- **WHEN** 用户对运行中的任务发起取消
- **THEN** 系统 SHALL 停止下载
- **AND** SHALL 清理该任务的临时文件
- **AND** SHALL 把状态标记为已取消

### Requirement: 成品过期与清理

系统 SHALL 清理过期成品与失败任务的临时文件，但保留成功成品供长期下载。

#### Scenario: 成品过期

- **WHEN** 成品文件超过 `FILE_EXPIRY_SECONDS`（默认 3 天）
- **THEN** 系统 SHALL 删除该成品
- **AND** SHALL 在状态中标明文件已不可用

#### Scenario: 清理失败任务

- **WHEN** 任务失败或被取消
- **THEN** 系统 SHALL 清理其临时文件
- **AND** SHALL NOT 影响其它任务的成品

### Requirement: 磁盘空间保护

系统 SHALL 在磁盘剩余空间不足时拒绝新建任务。

#### Scenario: 磁盘空间不足

- **WHEN** 可用空间低于 `DISK_MIN_FREE_BYTES`
- **THEN** 系统 SHALL 拒绝提交新任务并说明原因

### Requirement: 任务状态查询

系统 SHALL 提供任务进度查询，包含总瓦片数与已完成数。

#### Scenario: 查询进度

- **WHEN** 前端轮询任务状态
- **THEN** 系统 SHALL 返回状态、总瓦片数、已下载数、失败数、封禁计数
- **AND** 完成时 SHALL 返回下载链接与文件名

#### Scenario: 页面关闭后继续

- **WHEN** 用户关闭页面或手机锁屏
- **THEN** 服务端 SHALL 继续执行任务
- **AND** 用户返回时 SHALL 能按任务 ID 恢复查看进度
