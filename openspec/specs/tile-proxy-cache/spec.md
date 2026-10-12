# 瓦片代理与缓存

## Purpose

浏览器无法直连部分瓦片源（响应头违反 CORS 规范），需要由服务端代取。
同时瓦片是重复访问率极高的资源，落盘缓存可显著减少上游流量与限流风险。

## Requirements

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

### Requirement: 浏览器缓存友好

代理响应 SHALL 携带可长期缓存的头，使重复访问不产生任何网络请求。

#### Scenario: 重复请求同一瓦片

- **WHEN** 浏览器再次请求同一 `(layer,z,x,y)`
- **THEN** 系统 SHALL 返回 `Cache-Control: public, max-age=..., immutable`
- **AND** SHALL 返回基于内容计算的强 `ETag`
- **AND** 浏览器 SHALL 直接使用本地缓存，不发起网络请求

#### Scenario: ETag 稳定性

- **WHEN** 同一瓦片被多次回源
- **THEN** ETag SHALL 只取决于内容，不随回源时间变化
- **AND** 否则会使浏览器缓存无谓失效

### Requirement: 磁盘缓存

系统 SHALL 把回源取得的瓦片落盘，后续请求直接命中磁盘。

#### Scenario: 命中缓存

- **WHEN** 请求的瓦片已在磁盘
- **THEN** 系统 SHALL 直接返回磁盘内容，SHALL NOT 访问上游
- **AND** SHALL 在响应中标明命中状态

#### Scenario: 未命中回源

- **WHEN** 请求的瓦片不在磁盘
- **THEN** 系统 SHALL 回源获取、写入磁盘并返回
- **AND** SHALL 在响应中标明未命中

#### Scenario: 原子写入

- **WHEN** 写入瓦片到磁盘
- **THEN** 系统 SHALL 先写临时文件再原子替换
- **AND** SHALL NOT 让并发读取看到半截文件

### Requirement: 缓存容量与淘汰

系统 SHALL 限制缓存总容量，超限时按最久未用淘汰。

#### Scenario: 超过容量上限

- **WHEN** 缓存总量超过 `TILE_CACHE_MAX_BYTES`
- **THEN** 系统 SHALL 按最后访问时间从旧到新删除
- **AND** SHALL 删至上限的 85% 后停止
- **AND** SHALL 清理因此产生的空目录

#### Scenario: 淘汰不影响交付物

- **WHEN** 执行淘汰
- **THEN** SHALL 只删除瓦片缓存
- **AND** SHALL NOT 触碰任务成品文件

#### Scenario: 单张瓦片过大

- **WHEN** 单张瓦片超过 `TILE_CACHE_MAX_TILE_BYTES`
- **THEN** 系统 SHALL NOT 缓存该瓦片

### Requirement: 磁盘空间保护

系统 SHALL 在剩余空间不足时停止写入缓存。

#### Scenario: 剩余空间不足

- **WHEN** 可用空间低于 `DISK_MIN_FREE_BYTES`
- **THEN** 系统 SHALL 停止写入新缓存
- **AND** SHALL 继续正常提供已有缓存的读取

### Requirement: 上游限流反馈

系统 SHALL 在上游拒绝服务时向前端返回可区分的错误。

#### Scenario: 上游返回 403 或 429

- **WHEN** 上游对回源请求返回封禁类状态码
- **THEN** 系统 SHALL 返回 503 并说明是上游限流
- **AND** SHALL NOT 返回一个空白图片冒充成功

### Requirement: 缓存用量可观测

系统 SHALL 提供缓存用量的查询接口。

#### Scenario: 查询用量

- **WHEN** 请求缓存统计
- **THEN** 系统 SHALL 返回已用字节数、文件数、容量上限与启用的图层

#### Scenario: 手动清理

- **WHEN** 已鉴权的用户触发清理
- **THEN** 系统 SHALL 立即执行一次淘汰并返回结果

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
