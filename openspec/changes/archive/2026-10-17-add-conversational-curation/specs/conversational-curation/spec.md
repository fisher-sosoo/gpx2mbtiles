# Spec Delta

## Purpose

让用户用自然语言多轮修正项目里的地名点：删掉不要的、按类型只留一类、给某个点改名，
并可恢复到原始结果。模型只能提出受限操作，由服务端校验后执行。

## ADDED Requirements

### Requirement: 对话式修正

系统 SHALL 接受自然语言指令来修正项目的地名点，并保留多轮上下文。

#### Scenario: 发起一轮对话

- **WHEN** 用户在项目页发送一条指令
- **THEN** 系统 SHALL 把「当前地名点状态 + 对话历史 + 新指令」交给模型
- **AND** SHALL 只执行模型给出的受限操作
- **AND** SHALL 返回一句话说明与本次执行/被拒的操作

#### Scenario: 多轮承接

- **WHEN** 用户接着说「再删掉刚才那两个」
- **THEN** 系统 SHALL 把此前的对话历史一并提供给模型
- **AND** SHALL 保留在对话记录中，下次打开可见

#### Scenario: 没有地名点

- **WHEN** 项目还没有做补点
- **THEN** 系统 SHALL 拒绝对话并提示先补点

#### Scenario: 未配置密钥

- **WHEN** 未配置模型密钥
- **THEN** 系统 SHALL 返回可读提示，不得静默失败

### Requirement: 受限操作

系统 SHALL 只接受固定的操作集合，任何越界操作一律丢弃并记录。

#### Scenario: 支持的操作

- **WHEN** 模型输出删除某点、按类型保留、改名、恢复全部之一
- **THEN** 系统 SHALL 执行

#### Scenario: 越界与不存在的目标

- **WHEN** 模型给出未知操作、或引用了不存在的名称与类型
- **THEN** 系统 SHALL 丢弃该操作并在被拒列表中说明
- **AND** SHALL NOT 改动任何数据

#### Scenario: 模型返回不可解析

- **WHEN** 模型回复不是可解析的 JSON
- **THEN** 系统 SHALL 保持数据不变
- **AND** SHALL 把原回复作为说明文本返回

### Requirement: 可恢复

系统 SHALL 在首次修正前保留原始补点结果，允许一键恢复。

#### Scenario: 恢复

- **WHEN** 用户要求恢复
- **THEN** 系统 SHALL 恢复到筛选前的完整结果
- **AND** SHALL NOT 因之前的修改而丢失原始数据

#### Scenario: 不污染调用方数据

- **WHEN** 执行任何操作
- **THEN** 系统 SHALL 基于副本计算
- **AND** SHALL NOT 直接修改传入的原始列表
