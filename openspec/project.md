# 项目上下文

## 这是什么

`gpx2mbtiles` 是个人自用的 GPX 工具集，由两部分组成：

1. **离线地图生成**（服务端）：上传 GPX 轨迹 → 计算缓冲区内的瓦片清单 →
   并发下载 → 打包成 GeoPackage(.gpkg) 或 MBTiles(.mbtiles) →
   导入 Avenza Maps / Guru Maps 做离线导航。**行前准备用。**
2. **轨迹回放与分析**（纯前端）：PC 端叠加多条 GPX/KML/KMZ、配色、标注、出图。
   **行程结束后做分析分享用。**

## 运行环境

| 项 | 值 |
|---|---|
| 服务器 | 阿里云 ECS（墙内），Alibaba Cloud Linux 3，2 核 / 1.8G / 40G |
| 公网入口 | `http://59.110.15.156`（Caddy 反代 :80） |
| SSH | `root@59.110.15.156 -p 22022` |
| 应用目录 | `/opt/gpx2mbtiles`（git 仓库） |
| 数据目录 | `/opt/gpx2mbtiles/data`（SQLite 账本 + 成品 + 瓦片缓存） |
| 出口代理 | mihomo `127.0.0.1:7893`，容器内用 `host.docker.internal:7893` |

**关键约束：服务器在墙内，访问 Windy / Docker Hub / GitHub 必须走 mihomo 代理。**
只有受限地址走代理，Web 服务本身不走。

## 技术栈

- 后端：FastAPI + uvicorn + aiohttp，任务账本 SQLite 持久化
- 前端：原生 JS（无构建步骤），Leaflet 1.9.4
- 部署：Docker Compose，镜像基于 python:3.12-slim，非 root（uid 10001）
- 反向代理：Caddy v2（`/etc/caddy/Caddyfile`）
- CI/CD：GitHub Actions，推 `v*` tag 触发，构建失败自动回滚

## 目录结构

```
app/
  main.py             FastAPI 入口 + 路由
  config.py           环境变量配置（全部可配）
  gpx_processor.py    GPX 解析 + 瓦片清单计算
  gpkg_builder.py     GeoPackage 1.2 写入（EPSG:3857 金字塔）
  mbtiles_builder.py  MBTiles 1.0 写入（含 TMS 行号翻转）
  tile_downloader.py  并发下载 / 限流 / 重试 / 封禁检测
  tile_cache.py       瓦片代理的磁盘缓存（LRU 淘汰）
  task_manager.py     任务账本（SQLite）/ 生命周期 / 清理
web/
  index.html          生成器页（手机端）→ 由 Caddy 反代到 /gpx/
  player.html         回放分析页（PC 端）→ /gpx/player.html
  portal.html         服务门户 → Caddy file_server 直接提供
deploy/               部署用配置（Caddyfile 等）
docs/DEPLOY.md        云部署完整记录
tests/                单元 + 端到端 + 前端回归
```

## 已有能力（对应 openspec/specs/）

| 能力 | 说明 |
|---|---|
| `offline-map-generation` | GPX → 瓦片 → .gpkg/.mbtiles |
| `task-management` | 任务账本、并发上限、超时、清理 |
| `tile-providers` | Windy / OpenTopoMap 图层与取瓦片策略 |
| `tile-proxy-cache` | 瓦片代理 + 磁盘缓存（解决浏览器 CORS） |
| `track-playback` | 回放页：多格式导入、图层、标注、导出 |
| `service-portal` | 门户主页与路径分流 |
| `deployment` | Caddy / 代理 / 自愈 / CI 自动部署 |

## 关键设计决策与踩过的坑

这些是**真实发生过的问题**，改代码前务必先读：

1. **Windy 不能浏览器直连。** 其响应头同时带
   `access-control-allow-credentials: true` 与 `access-control-allow-origin: *`，
   违反 CORS 规范，Chrome 判 `ERR_BLOCKED_BY_ORB`，底图整片空白。
   → 必须走服务端代理（`tile-proxy-cache`）。

2. **限速只应作用于"服务器 → 上游"。**
   前端请求的是本站，不该被限速。曾错误地把前端也做了 900ms/张排队，
   导致命中磁盘缓存的请求被白白拖慢。现已移除。

3. **服务器上不要留未提交改动。** 会导致 CI 的 `git checkout` 失败、
   整个部署中断（曾连续失败三次）。CI 现在会先丢弃已跟踪文件的改动。

4. **tag 冲突会让 `git fetch --tags` 返回非零并中断部署。**
   CI 已改为 `--force --prune`，并在 fetch 前清理远端已不存在的本地 tag。

5. **瓦片缓存是只读缓存**，可安全淘汰；成品文件（.gpkg/.mbtiles）是交付物，
   两者生命周期不同，不可混淆。

## 合规红线

**仅限个人自用。** Windy 服务条款禁止批量爬取瓦片；已启用限流与请求间隔、
部署在海外节点（对瓦片源而言）、不得对外提供服务。
