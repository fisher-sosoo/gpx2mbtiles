# Spec Delta

## MODIFIED Requirements

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

#### Scenario: Garmin 活动长图入口

- **WHEN** 用户查看门户页
- **THEN** 系统 SHALL 提供进入 Garmin 活动长图页（`/gpx/garmin.html`）的入口卡片
- **AND** 该卡片的说明 SHALL 写明用途：从 Garmin 拉取活动，生成含心率、步频与温度分段的竖版长图
