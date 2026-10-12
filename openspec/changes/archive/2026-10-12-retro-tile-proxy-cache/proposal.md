# 瓦片代理与磁盘缓存（补记）

## Why

浏览器直连 Windy 瓦片会整片空白。排查后确认根因不在本项目代码：

Windy 的瓦片响应同时带这两个头：

```
access-control-allow-credentials: true
access-control-allow-origin: *
```

按 CORS 规范，通配符源不允许携带凭据，两者不能并存。
Chrome 因此把响应判为不可用，报 `ERR_BLOCKED_BY_ORB`。

实测对照（同一会话、同一网络）：

| 瓦片源 | 浏览器结果 |
|---|---|
| OpenTopoMap | OK |
| OpenStreetMap | OK |
| Windy | `ERR_BLOCKED_BY_ORB` |

用命令行请求同样的 URL 能拿到 200 + 有效 PNG，因为它不做 CORS 校验 ——
这正是此前反复误判为"限流"的原因。

## What Changes

**[底图默认值]**
- From: 默认 Windy
- To: 默认 OpenTopoMap；Windy 保留为可选项
- Reason: Windy 在浏览器端不可用，且 OpenTopoMap 是地形图，更适合徒步分析
- Impact: 非破坏性；用户仍可手动切换

**[瓦片获取方式]**
- From: 浏览器直连上游瓦片源
- To: Windy 经本服务端代理 `/api/tile/windy/{z}/{x}/{y}`；OTM/OSM 仍直连
- Reason: 绕开 CORS 限制，同时获得服务端缓存
- Impact: 新增接口；服务端需承受瓦片流量，但缓存后可显著降低上游请求

**[缓存]**
- From: 无
- To: 磁盘缓存 + LRU 淘汰（上限 8GB）+ 浏览器 immutable 缓存
- Reason: 瓦片重复访问率高，缓存可省流量并降低被上游封禁的风险
- Impact: 新增磁盘占用，设上限与磁盘保护阈值

**[前端限速]**
- From: 前端对每个瓦片请求排队限速（900ms/张）
- To: 前端不限速，限速只保留在服务端与上游之间
- Reason: 浏览器请求的是本站，命中缓存时根本不回源，前端限速纯属拖慢
- Impact: 加载显著变快；上游保护由服务端统一负责

## 影响范围

- 新增：`app/tile_cache.py`、`/api/tile/...`、`/api/tilecache/stats`
- 修改：`app/config.py`、`app/main.py`、`web/player.html`
- 新增依赖：无（复用既有 aiohttp）

## 超出范围

- 不为 OTM/OSM 做代理（它们浏览器端可用，直连即可）
- 不做瓦片预生成或离线打包
