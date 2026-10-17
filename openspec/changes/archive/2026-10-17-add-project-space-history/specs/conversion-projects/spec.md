# Spec Delta

## Purpose

把每一次轨迹转换作为一个项目保存下来：原件、产物与摘要都留在服务端，
可以随时回看、用新参数重转、或删除。它是后续补点、行前指南、对话修正的载体。

## ADDED Requirements

### Requirement: 转换落成项目

系统 SHALL 把每次成功的转换保存为一个项目，并返回其标识。

#### Scenario: 转换成功

- **WHEN** 用户提交一次转换且解析成功
- **THEN** 系统 SHALL 在服务端保存该项目的原件、产物 GPX 与摘要
- **AND** 响应中 SHALL 包含项目标识
- **AND** 保存失败 SHALL NOT 影响已经完成的转换结果返回

#### Scenario: 转换失败

- **WHEN** 输入无法解析
- **THEN** 系统 SHALL NOT 创建项目
- **AND** SHALL 返回可读的中文错误

### Requirement: 历史列表

系统 SHALL 提供按时间倒序的项目列表，支持分页。

#### Scenario: 列出历史

- **WHEN** 用户请求历史
- **THEN** 系统 SHALL 返回总数与当页条目
- **AND** 每条 SHALL 包含名称、时间、点数、航点数、里程、是否用过 AI

#### Scenario: 分页边界

- **WHEN** 请求的条数超过上限或偏移为负
- **THEN** 系统 SHALL 收敛到合法范围，不得报错

### Requirement: 项目详情与取回

系统 SHALL 允许按标识取回项目的元数据、摘要与产物。

#### Scenario: 打开项目

- **WHEN** 用户打开一个存在的项目
- **THEN** 系统 SHALL 返回元数据、摘要与 GPX 文本
- **AND** SHALL 标明原件与产物是否仍然可用

#### Scenario: 项目不存在

- **WHEN** 请求不存在的项目
- **THEN** 系统 SHALL 返回 404

#### Scenario: 产物已被清理

- **WHEN** 项目存在但产物文件不在
- **THEN** 系统 SHALL 明确告知已被清理，而不是返回空内容冒充成功

### Requirement: 重新转换

系统 SHALL 允许用保存的原件按新参数重新转换。

#### Scenario: 改参数重转

- **WHEN** 用户对某个历史项目发起重转并可指定轨迹名或是否启用 AI
- **THEN** 系统 SHALL 用保存的原件重新转换
- **AND** SHALL 生成一个新项目并保留原项目，便于对比
- **AND** 新项目 SHALL 记录它来自哪个项目

#### Scenario: 原件缺失

- **WHEN** 原件已被清理
- **THEN** 系统 SHALL 拒绝重转并说明原因

### Requirement: 删除项目

系统 SHALL 允许删除项目，并同时清理其文件。

#### Scenario: 删除

- **WHEN** 用户删除一个存在的项目
- **THEN** 系统 SHALL 移除账本记录与整个项目目录
- **AND** 再次删除同一项目 SHALL 返回 404

### Requirement: 保留策略

系统 SHALL 按条数与保留天数自动淘汰旧项目。

#### Scenario: 超出条数

- **WHEN** 项目数超过配置上限
- **THEN** 系统 SHALL 删除最旧的，直到不超过上限
- **AND** SHALL NOT 删除最新的项目

#### Scenario: 超出保留期

- **WHEN** 项目创建时间早于保留天数
- **THEN** 系统 SHALL 删除它

#### Scenario: 可关闭

- **WHEN** 上限或保留天数被配置为 0
- **THEN** 系统 SHALL 视为不限制，不执行对应淘汰

### Requirement: 历史界面

系统 SHALL 在转换页提供历史项目区块。

#### Scenario: 展示与操作

- **WHEN** 用户打开转换页
- **THEN** 页面 SHALL 列出最近的项目及摘要信息
- **AND** 每个项目 SHALL 提供打开、重转、下载、删除四个操作
- **AND** 删除 SHALL 要求二次确认
- **AND** 当前正在查看的项目 SHALL 被高亮
