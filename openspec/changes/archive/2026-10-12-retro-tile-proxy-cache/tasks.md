# 任务

## 1. 后端：缓存模块

- [x] 1.1 新增 `app/tile_cache.py`：分片路径、读写、LRU 淘汰、用量统计
- [x] 1.2 原子写入（先 `.tmp` 再 `replace`），避免读到半截文件
- [x] 1.3 磁盘保护：剩余空间低于阈值时停止写入，但保持可读
- [x] 1.4 淘汰后清理空目录
- [x] 1.5 XYZ 坐标合法性校验

## 2. 后端：代理端点

- [x] 2.1 新增 `GET /api/tile/{layer}/{z}/{x}/{y}`
- [x] 2.2 图层白名单，非白名单返回 404；坐标越界返回 400
- [x] 2.3 复用 `TileFetcher`，按图层切换模板与 UA/Referer
- [x] 2.4 上游 403/429 返回 503 并说明，不返回空白图冒充成功
- [x] 2.5 新增 `GET /api/tilecache/stats` 与 `POST /api/tilecache/evict`

## 3. 后端：缓存头

- [x] 3.1 响应带 `Cache-Control: public, max-age=2592000, immutable`
- [x] 3.2 ETag 基于内容哈希（不用 mtime）
- [x] 3.3 响应带 `X-Tile-Cache: HIT/MISS` 便于观测

## 4. 配置

- [x] 4.1 `TILE_CACHE_ENABLED`、`TILE_CACHE_MAX_BYTES`（默认 8GB）
- [x] 4.2 `TILE_CACHE_MAX_TILE_BYTES`（单张上限，默认 5MB）
- [x] 4.3 `TILE_PROXY_LAYERS`（默认 windy）
- [x] 4.4 `DISK_MIN_FREE_BYTES` 提到 3GB

## 5. 前端

- [x] 5.1 Windy 底图指向 `/api/tile/windy/{z}/{x}/{y}`
- [x] 5.2 移除 tiles 图层的 `crossOrigin`（会强制 CORS 模式，放大失败面）
- [x] 5.3 默认底图改为 OpenTopoMap，Windy 保留为可选项并附说明
- [x] 5.4 保留失败重试（`applyTileRetry`），去掉前端限速队列
- [x] 5.5 `keepBuffer` 1 -> 4，减少快速缩放时的瓦片丢弃
- [x] 5.6 显示服务端缓存用量
- [x] 5.7 导出 PNG 改用独立 Image 拉瓦片，不依赖页面元素

## 6. 验证

- [x] 6.1 服务端可拉取 Windy（实测 200 + 有效 PNG）
- [x] 6.2 代理端点首次 MISS、二次 HIT
- [x] 6.3 边界校验：坐标越界 400、非白名单图层 404
- [x] 6.4 浏览器同 URL 二次请求 0 网络请求（immutable 生效）
- [x] 6.5 同一 z 来回平移 6 轮，重复请求 0
- [x] 6.6 前端不再逐张限速：16 张瓦片耗时从约 14 秒降到 1ms
- [x] 6.7 模拟服务端 502，重试后 16/16 全部加载

## 7. 文档

- [x] 7.1 `docs/DEPLOY.md` 记录代理与缓存配置
- [x] 7.2 README 说明 Windy 需经代理
