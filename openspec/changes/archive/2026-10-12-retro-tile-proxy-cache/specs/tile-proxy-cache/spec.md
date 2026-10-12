# 瓦片代理与缓存（变更增量）

本 change 对应的能力 `tile-proxy-cache` 已在 `openspec/specs/` 中建立。
此处记录本次补记所引入/调整的需求。

## ADDED Requirements

### Requirement: 缓存容量与磁盘保护默认值

系统 SHALL 为瓦片缓存设置容量上限与磁盘剩余空间保护阈值。

#### Scenario: 默认容量

- **WHEN** 未显式配置
- **THEN** 缓存总容量上限 SHALL 为 8 GB
- **AND** 磁盘剩余空间保护阈值 SHALL 为 3 GB

#### Scenario: 空间不足时停止写入

- **WHEN** 磁盘可用空间低于保护阈值
- **THEN** 系统 SHALL 停止写入新缓存
- **AND** SHALL 继续正常提供已有缓存的读取

### Requirement: 前端不得对本站瓦片请求限速

限速 SHALL 只作用于服务端与上游之间，前端 SHALL NOT 对请求本站瓦片的
行为施加人为节流。

#### Scenario: 浏览器请求瓦片

- **WHEN** 浏览器通过地图库请求本站的瓦片代理
- **THEN** 并发 SHALL 交由浏览器自行控制
- **AND** SHALL NOT 在前端逐个排队或插入固定间隔

#### Scenario: 命中缓存时的表现

- **WHEN** 请求命中服务端缓存
- **THEN** 返回速度 SHALL 只受本机与网络限制
- **AND** SHALL NOT 受上游限速参数影响

#### Scenario: 失败重试仍然保留

- **WHEN** 服务端因重启或上游限流返回 502/503
- **THEN** 前端 SHALL 带退避地重试有限次数
- **AND** 该重试 SHALL NOT 改变正常情况下的加载速率

## MODIFIED Requirements

### Requirement: 服务端代取瓦片

系统 SHALL 提供同源的瓦片代理端点，且只代理被显式列入白名单的图层；
浏览器可直连的图层由浏览器自行获取，不经服务端转发。

#### Scenario: 请求瓦片

- **WHEN** 前端请求 `/api/tile/{layer}/{z}/{x}/{y}`
- **THEN** 系统 SHALL 返回该瓦片的图片内容
- **AND** SHALL 使用同源地址返回，使浏览器的同源策略不会拦截

#### Scenario: 图层白名单

- **WHEN** 请求的图层不在 `TILE_PROXY_LAYERS` 中
- **THEN** 系统 SHALL 拒绝并返回 404

#### Scenario: 坐标越界

- **WHEN** z/x/y 超出该缩放级别的合法范围
- **THEN** 系统 SHALL 拒绝并返回 400

#### Scenario: 白名单的取舍

- **WHEN** 某图层在浏览器端可正常直连
- **THEN** SHALL NOT 将其纳入白名单，以免白白消耗服务器带宽 ← (was: 未限定白名单范围)
