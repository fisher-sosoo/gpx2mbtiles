# 离线地图生成

## Purpose

把 GPX 轨迹转换成可导入离线导航 App 的底图包，供行前准备使用。
服务端负责计算轨迹缓冲区内的全部瓦片、并发下载并组装成单一文件交付。

## Requirements

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

### Requirement: 瓦片清单计算

系统 SHALL 依据缓冲区距离与缩放范围，计算覆盖轨迹的全部 XYZ 瓦片并去重。

#### Scenario: 按缓冲区扩展范围

- **WHEN** 用户指定缓冲区距离（默认 2500 米）
- **THEN** 系统 SHALL 把轨迹按该距离向外扩展后再计算瓦片
- **AND** SHALL 对结果去重

#### Scenario: 按缩放范围计算

- **WHEN** 用户指定 min-zoom 与 max-zoom
- **THEN** 系统 SHALL 计算该范围内每一级的瓦片
- **AND** SHALL 拒绝 min-zoom 大于 max-zoom 的输入

### Requirement: 瓦片数量预估

系统 SHALL 在不创建任务的前提下预估瓦片数量，供前端二次确认。

#### Scenario: 提交前预估

- **WHEN** 前端调用预估接口并上传 GPX 与参数
- **THEN** 系统 SHALL 返回预计瓦片数、轨迹点数、单任务上限
- **AND** SHALL 标明是否超过上限
- **AND** SHALL NOT 产生任何任务或下载

### Requirement: 超限二次确认

系统 SHALL 在瓦片数超过单任务上限时要求显式确认后才放行。

#### Scenario: 超过上限

- **WHEN** 预估瓦片数超过 `MAX_TILES_PER_TASK`
- **THEN** 系统 SHALL 拒绝提交，除非请求中带有 `allow_oversize`
- **AND** 前端 SHALL 在放行前向用户二次确认

### Requirement: 两种输出格式

系统 SHALL 支持 GeoPackage 与 MBTiles 两种成品格式。

#### Scenario: 生成 GeoPackage

- **WHEN** 输出格式为 `gpkg`
- **THEN** 系统 SHALL 生成符合 GeoPackage 1.2 的文件
- **AND** SHALL 包含 `gpkg_contents`、`gpkg_spatial_ref_sys`（EPSG:3857）、
  `gpkg_tile_matrix` 金字塔与 `tiles` 表

#### Scenario: 生成 MBTiles

- **WHEN** 输出格式为 `mbtiles`
- **THEN** 系统 SHALL 生成符合 MBTiles 1.0 的文件
- **AND** SHALL 包含 `tiles` 表、唯一索引与 `metadata`
  （name/format/bounds/minzoom/maxzoom）
- **AND** SHALL 正确处理 XYZ 与 TMS 的行号翻转

### Requirement: 下载限流与封禁保护

系统 SHALL 限制对瓦片源的请求速率，并在被拒绝时中止任务。

#### Scenario: 控制请求速率

- **WHEN** 下载瓦片
- **THEN** 系统 SHALL 遵守 `MAX_CONCURRENCY`（默认 8）与
  `REQUEST_INTERVAL_MS`（默认 100）
- **AND** SHALL 对失败请求按指数退避重试

#### Scenario: 检测到封禁

- **WHEN** 瓦片源持续返回 403/429 且达到判定阈值
- **THEN** 系统 SHALL 终止任务并记录原因
- **AND** SHALL NOT 继续冲击上游

### Requirement: 自定义文件名

系统 SHALL 允许用户指定成品文件名，并在缺失时回退到轨迹名。

#### Scenario: 指定文件名

- **WHEN** 用户填写自定义文件名
- **THEN** 成品 SHALL 使用该名称（追加图层后缀）
- **AND** SHALL 过滤掉路径分隔符等非法字符

### Requirement: 转换入口

系统 SHALL 提供把 KML 转换成 GPX 的页面入口，便于在导入 App 前先整理命名。

#### Scenario: 页面入口

- **WHEN** 用户打开生成器页、回放页或服务门户
- **THEN** 每个页面 SHALL 提供进入命名转换页的链接
- **AND** 链接 SHALL 使用 `/gpx/` 前缀，与现有页内跳转规则一致

#### Scenario: 与生成流程衔接

- **WHEN** 用户在转换页拿到 GPX
- **THEN** 该文件 SHALL 可直接用于生成离线地图与回放，无需再次手工整理
