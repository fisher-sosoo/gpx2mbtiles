# 部署与运维

## Purpose

规定服务器上的服务编排、反向代理、受限网络下的出口代理、服务自愈，
以及由版本标签触发的自动部署与失败回滚流程。

服务器为单台个人自用节点，同时承载多个服务且网络受限，因此部署方案必须
在「无人值守也能恢复」与「出错时不会把线上打挂」之间取得平衡：
容器与代理随主机自启，部署失败自动回退到上一个成功版本，
且部署流程本身要能容忍部署机上的历史残留。

## Requirements

### Requirement: 容器化运行

应用 SHALL 以容器方式运行，并随主机启动自动拉起。

#### Scenario: 容器配置

- **WHEN** 启动应用容器
- **THEN** SHALL 以非 root 用户运行
- **AND** SHALL 只监听回环地址，由反向代理对外
- **AND** SHALL 挂载数据目录以持久化账本与成品
- **AND** SHALL 具备重启策略

#### Scenario: 健康检查

- **WHEN** 检查容器状态
- **THEN** 系统 SHALL 提供免鉴权的健康检查接口

### Requirement: 反向代理

系统 SHALL 通过反向代理对外提供服务。

#### Scenario: 对外端口

- **WHEN** 用户访问站点
- **THEN** SHALL 通过反向代理的统一端口进入
- **AND** 应用端口 SHALL NOT 直接暴露在公网

### Requirement: 受限网络下的代理

服务器访问上游受限资源 SHALL 经由本地代理。

#### Scenario: 需要代理的流量

- **WHEN** 访问瓦片源、容器镜像仓库或代码托管
- **THEN** SHALL 经由本地代理出口
- **AND** Web 服务本身的对外流量 SHALL NOT 经过该代理

### Requirement: 自动部署

系统 SHALL 支持由版本标签触发的自动部署，并在失败时自动回滚。

#### Scenario: 推送版本标签

- **WHEN** 推送 `v*` 形式的标签
- **THEN** 系统 SHALL 在服务器上拉取该版本、重建并重启容器
- **AND** SHALL 在健康检查通过后记录为成功版本

#### Scenario: 部署失败回滚

- **WHEN** 构建或健康检查失败
- **THEN** 系统 SHALL 自动回退到上一个成功版本并重新部署
- **AND** SHALL 在回滚后仍然不健康时明确报告需人工介入

#### Scenario: 部署机存在本地改动

- **WHEN** 服务器工作区存在未提交的改动
- **THEN** 部署流程 SHALL 先丢弃已跟踪文件的改动再检出目标版本
- **AND** SHALL NOT 因为该改动导致部署中断

#### Scenario: 标签冲突

- **WHEN** 服务器上存在与远端同名但指向不同的标签
- **THEN** 拉取 SHALL 使用强制覆盖，不得因此中断部署
- **AND** SHALL 在检出前校验目标版本确实存在

### Requirement: 服务自愈

系统 SHALL 在主机重启后自动恢复全部服务。

#### Scenario: 主机重启

- **WHEN** 服务器重启
- **THEN** 反向代理、代理服务、容器 SHALL 全部自动拉起
- **AND** 已完成的任务记录 SHALL 仍然可查

### Requirement: 访问控制

系统 SHALL 支持为写操作配置访问令牌。

#### Scenario: 配置了令牌

- **WHEN** 设置了访问令牌
- **THEN** 接口 SHALL 要求通过请求头或查询参数提供正确令牌
- **AND** 健康检查 SHALL 保持免鉴权

#### Scenario: 未配置令牌

- **WHEN** 未设置访问令牌
- **THEN** 系统 SHALL 放行全部请求
- **AND** 文档 SHALL 提示生产环境建议设置
