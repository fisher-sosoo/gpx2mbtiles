# 瓦片源与图层

## Purpose

规定可用的底图图层、取瓦片方式与访问策略。

服务器部署在受限网络环境中，无法直连上游瓦片源，因此所有瓦片请求都必须
经由本地代理出口；同时上游对非浏览器流量与高频请求较为敏感，需要统一的
请求伪装与节流策略。本章界定「哪些图层可用」「如何取瓦片」「如何不被拒绝」，
以及必须遵守的个人自用合规边界。

## Requirements

### Requirement: 图层注册表

系统 SHALL 通过配置注册可用图层，并允许前端按 key 选择。

#### Scenario: 列出可用图层

- **WHEN** 前端请求生成任务
- **THEN** 系统 SHALL 只接受注册表中存在的 `tile_layer` 值
- **AND** SHALL 拒绝未知图层并列出支持项

#### Scenario: 内置图层

- **WHEN** 使用默认配置
- **THEN** 系统 SHALL 提供 Windy 户外与 OpenTopoMap 地形图两个图层
- **AND** SHALL 各自携带 URL 模板、UA、Referer 与最大缩放级别

### Requirement: 上游访问必须走代理

系统 SHALL 通过可配置代理访问瓦片源，因为服务器网络无法直连。

#### Scenario: 配置代理

- **WHEN** 设置了 `TILE_PROXY`
- **THEN** 所有瓦片请求 SHALL 经由该代理
- **AND** 未设置时 SHALL 回退到 `HTTPS_PROXY` / `HTTP_PROXY` 环境变量

### Requirement: 请求伪装

系统 SHALL 为瓦片请求设置浏览器风格的 UA 与 Referer，
避免被上游按非浏览器流量拒绝。

#### Scenario: 发送请求头

- **WHEN** 请求瓦片
- **THEN** 系统 SHALL 携带配置的 `TILE_USER_AGENT` 与 `TILE_REFERER`

### Requirement: 子域名轮询

系统 SHALL 支持含 `{s}` 占位符的 URL 模板，按子域名轮询分散请求。

#### Scenario: 模板含子域占位符

- **WHEN** 图层模板包含 `{s}` 且配置了子域名列表
- **THEN** 系统 SHALL 依次轮询各子域名

### Requirement: 个人自用合规约束

系统 SHALL 只面向个人自用，不得对外提供瓦片批量抓取服务。

#### Scenario: 遵守上游条款

- **WHEN** 部署本服务
- **THEN** 必须启用限流与请求间隔
- **AND** 必须部署在对瓦片源可达的节点
- **AND** SHALL NOT 对外提供服务
