# Spec Delta

## MODIFIED Requirements

### Requirement: GPX 轨迹解析

系统 SHALL 解析上传的轨迹文件并提取轨迹点，用于计算瓦片覆盖范围。

#### Scenario: 解析标准 GPX

- **WHEN** 用户上传包含 `<trkpt>` 的 GPX 文件
- **THEN** 系统提取全部轨迹点的经纬度
- **AND** 轨迹名取自 `<trk>` 的 `<name>`，缺失时回退到文件名

#### Scenario: 支持多种点元素

- **WHEN** GPX 中使用 `trkpt`、`rtept` 或 `wpt`
- **THEN** 系统 SHALL 全部识别

#### Scenario: 直接接受 KML 与 KMZ

- **WHEN** 用户上传 .kml 或 .kmz 文件
- **THEN** 系统 SHALL 与转换服务使用同一套点提取逻辑，取出其中的轨迹点
- **AND** SHALL 以提取结果参与瓦片清单计算与预估
- **AND** 轨迹名 SHALL 优先取文件内可识别的地名，最终回退到文件名

#### Scenario: 拒绝无效输入

- **WHEN** 文件不是合法 XML、或不是可识别的轨迹格式、或不含任何轨迹点
- **THEN** 系统 SHALL 拒绝并返回可读的中文错误说明
- **AND** SHALL NOT 创建任务

## ADDED Requirements

### Requirement: 转换入口

系统 SHALL 提供把 KML 转换成 GPX 的页面入口，便于在导入 App 前先整理命名。

#### Scenario: 页面入口

- **WHEN** 用户打开生成器页、回放页或服务门户
- **THEN** 每个页面 SHALL 提供进入命名转换页的链接
- **AND** 链接 SHALL 使用 `/gpx/` 前缀，与现有页内跳转规则一致

#### Scenario: 与生成流程衔接

- **WHEN** 用户在转换页拿到 GPX
- **THEN** 该文件 SHALL 可直接用于生成离线地图与回放，无需再次手工整理
