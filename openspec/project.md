# 项目上下文

## 这是什么

`gpx2mbtiles` 是个人自用的 GPX 工具集，由两部分组成：

1. **离线地图生成**（服务端）：上传 GPX（或 KML/KMZ）→ 计算缓冲区内的瓦片清单 →
   并发下载 → 打包成 GeoPackage(.gpkg) 或 MBTiles(.mbtiles) →
   导入 Avenza Maps / Guru Maps 做离线导航。**行前准备用。**
2. **轨迹回放与分析**（纯前端）：PC 端叠加多条 GPX/KML/KMZ、配色、标注、出图。
   **行程结束后做分析分享用。**
3. **KML → GPX 命名转换**（服务端）：两步路等 App 导出的 KML 丢掉名称后，
   按「已走里程 + 累计耗时」重命名航点、按「地点 + 日期 + 类型」重命名轨迹，
   可选 AI 推测命名。**导入只认 GPX 的 App 前用。**

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
  kml_processor.py    KML/KMZ → 中间结构（轨迹/航点/扩展字段）
  kml_naming.py       命名规则：沿轨迹里程/耗时、轨迹名、去重
  gpx_writer.py       GPX 1.1 输出
  gpx_converter.py    转换流程编排（解析→定位→命名→输出）
  ai_naming.py        可选的 AI 推测命名（调用失败自动回退）
  task_manager.py     任务账本（SQLite）/ 生命周期 / 清理
web/
  index.html          生成器页（手机端）→ 由 Caddy 反代到 /gpx/
  convert.html        KML → GPX 命名转换页
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
| `track-conversion` | KML/KMZ → GPX，航点与轨迹重命名（含可选 AI 命名） |
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
6. **Garmin .img 转 .gmap 有若干硬坑**（详见 docs/GARMIN_IMGPACK.md）：
   - GMapTool 图形版和 cGPSmapper 都**产不出** .gmap，它们只做 MapSource 注册表挂载；
   - IMG 的 FAT 表位置不固定，子文件名是**定长** 8+3 字节，扇区结束符要按无符号 0xFFFF 判断；
   - BaseCamp 显示的名称来自 **TDB**，不是 Info.xml，两者要一致；
   - 空壳 TYP（小于 1 KB、无要素定义）会让 BaseCamp 判定安装存在问题；
   - **同 FID 的多个包只认一个**，多地图共存前必须核对 FID 互不重复。
7. **两步路 KML 的时间有三个字段，别相减错了。** `<gx:Track>` 的 `<when>` 是 UTC；
   标注点 `description` 里的「时间：10:43:05」是 UTC+8 本地钟点；
   `ExtendedData.Time` 是同一时刻的毫秒 epoch。换算累计耗时要先把本地钟点
   按 +8 还原成 UTC 再相减，直接相减会整整差 8 小时。
8. **标注点没有 `<name>` 是常态。** 真实样例里轨迹名是「轨迹片段1」、
   30 个标注点全部无名，只有坐标、海拔、时间和附件 id 可用。名称只能自己算。

## 合规红线

**仅限个人自用。** Windy 服务条款禁止批量爬取瓦片；已启用限流与请求间隔、
部署在海外节点（对瓦片源而言）、不得对外提供服务。
