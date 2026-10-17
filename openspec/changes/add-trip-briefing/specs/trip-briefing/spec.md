# Spec Delta

## Purpose

把轨迹几何、地名点与天气预报合成一份出发前可读的指南：关键节点按里程排列、
天气窗口、风险提示与易错点，并可保存到手机备用。

## ADDED Requirements

### Requirement: 天气查询

系统 SHALL 依据轨迹中心位置与海拔查询逐日天气预报。

#### Scenario: 取预报

- **WHEN** 用户生成指南
- **THEN** 系统 SHALL 按轨迹中心经纬度查询逐日预报
- **AND** SHALL 按轨迹海拔中位数请求，使温度贴近实际体感
- **AND** SHALL 返回日期、天气、温度区间、降水量与概率、风速

#### Scenario: 查询失败

- **WHEN** 天气服务不可用
- **THEN** 系统 SHALL 继续生成不含天气的指南
- **AND** SHALL NOT 因天气失败而整体报错

### Requirement: 日期范围

系统 SHALL 支持指定单日出发或多日区间。

#### Scenario: 单日

- **WHEN** 用户只填出发日期
- **THEN** 指南 SHALL 只覆盖该日

#### Scenario: 多日区间

- **WHEN** 用户填写起止日期
- **THEN** 指南 SHALL 覆盖该区间内的每一天

#### Scenario: 未指定

- **WHEN** 用户未填写日期
- **THEN** 系统 SHALL 取未来 7 天

### Requirement: 指南内容

系统 SHALL 生成包含路线概况、关键节点、天气、风险与易错点的指南。

#### Scenario: 路线概况

- **WHEN** 生成指南
- **THEN** SHALL 给出路线名、总里程、运动类型、日期与段数
- **AND** 有山峰数据时 SHALL 指出最高可见峰

#### Scenario: 关键节点

- **WHEN** 项目已有地名点
- **THEN** 指南 SHALL 按里程升序列出关键节点
- **AND** 同名节点 SHALL 只出现一次
- **AND** 每条 SHALL 含里程、名称、类型与海拔

#### Scenario: 风险提示

- **WHEN** 存在高海拔垭口、过河点、长距离或恶劣天气
- **THEN** 指南 SHALL 给出对应风险说明
- **AND** 天气风险 SHALL 指向风险最多的那天
- **AND** SHALL 列出其余需留意的日期

#### Scenario: 易错点

- **WHEN** 存在发卡弯、营地或水点
- **THEN** 指南 SHALL 提示转向密集处、可用营地与补水点

### Requirement: AI 叙述

系统 SHALL 在有模型密钥时生成针对性的风险分析，无密钥时仍给出完整指南。

#### Scenario: 有密钥

- **WHEN** 用户选择使用 AI 且已配置密钥
- **THEN** 系统 SHALL 把已算出的事实交给模型写成分析
- **AND** SHALL 要求模型只依据给定事实、不编造地名与路况

#### Scenario: 无密钥

- **WHEN** 未配置密钥
- **THEN** 系统 SHALL 仍生成结构化指南
- **AND** SHALL 说明分析部分未生成

#### Scenario: 模型失败

- **WHEN** 模型超时或报错
- **THEN** 系统 SHALL 保留结构化指南并记录原因

### Requirement: 保存与复用

系统 SHALL 允许把指南保存为文本，并在再次打开项目时复用已生成的结果。

#### Scenario: 导出文本

- **WHEN** 指南已生成
- **THEN** 页面 SHALL 能复制全文或下载为 Markdown
- **AND** 文本 SHALL 含各章节与表格

#### Scenario: 再次打开

- **WHEN** 重新打开该项目
- **THEN** 系统 SHALL 返回已生成的指南，不重复查询天气
