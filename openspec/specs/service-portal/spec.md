# 服务门户

## Purpose

服务器上运行多个服务（GPX 工具、游戏等）。门户提供统一入口，
并由反向代理按路径分流，避免各服务争抢根路径。

## Requirements

### Requirement: 统一入口

系统 SHALL 在根路径提供门户页，展示各服务的入口卡片。

#### Scenario: 访问根路径

- **WHEN** 用户访问 `/`
- **THEN** 系统 SHALL 返回门户页
- **AND** SHALL 列出所有可用服务及其说明

#### Scenario: 分析长图入口

- **WHEN** 用户查看门户页
- **THEN** 系统 SHALL 提供进入分析长图页（`/gpx/report.html`）的入口卡片
- **AND** 该卡片的说明 SHALL 写明用途：导入 GPX 生成带统计与 1km 分段的竖版长图

### Requirement: 路径分流

系统 SHALL 按路径把请求分流到对应服务。

#### Scenario: GPX 工具的路径

- **WHEN** 用户访问 `/gpx/*`
- **THEN** 系统 SHALL 反代到应用容器并剥离 `/gpx` 前缀
- **AND** SHALL 同时反代 `/api/*`（前端以根路径调用接口）

#### Scenario: 不便分流的服务

- **WHEN** 某服务的前端使用根路径绝对引用且不支持基路径
- **THEN** SHALL 保持其独立端口直达，不强行做路径反代
- **AND** 门户 SHALL 以完整地址链接到它

### Requirement: 静态资源缓存策略

系统 SHALL 对门户与前端资源设置合理的缓存策略。

#### Scenario: HTML 不缓存

- **WHEN** 返回 HTML 页面
- **THEN** 系统 SHALL 设置不缓存，保证发布后立即生效

#### Scenario: 静态资源长缓存

- **WHEN** 返回带指纹或不变的静态资源
- **THEN** 系统 SHALL 允许较长缓存

### Requirement: 传输压缩

系统 SHALL 对文本类响应启用压缩。

#### Scenario: 客户端支持压缩

- **WHEN** 请求头表明支持 zstd 或 gzip
- **THEN** 系统 SHALL 对文本响应启用压缩
