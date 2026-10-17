# GPX 工具：离线地图生成 + 轨迹回放

> 四个页面，一套服务（统一入口 `/` 门户）：
> - **📦 生成离线地图**（`/gpx/`）：手机上传 GPX（也可直接传 KML / KMZ）→ 云服务器下载瓦片 → 生成 .gpkg / .mbtiles 导入 Avenza / Guru Maps 离线导航。**行前准备用。**
> - **🏷️ KML → GPX 命名转换**（`/gpx/convert.html`）：两步路等 App 导出的 KML 里航点和轨迹都没有名字，这里自动按「已走里程 + 累计耗时」命名航点、按「地点 + 日期 + 运动类型」命名轨迹，可选 AI 推测命名。**导入只认 GPX 的 App 前用。**
> - **🎬 轨迹回放与分析**（`/gpx/player.html`）：PC 端导入多条 GPX / KML / KMZ 叠加在地图上，配色、标注、做截图。**行程结束后做分析分享用，纯前端零服务器开销。**
> - **🧭 服务门户**（`/`）：各服务统一入口。
>
> ⚠️ 仅限个人自用：Windy-Outdoor 服务条款禁止批量爬取瓦片。请务必开启限流与请求间隔、部署在海外节点、不得对外提供服务。

> 📦 **云部署指南**（阿里云 ECS · 代理 · 自愈 · 安全加固 · GitHub Actions 自动部署）：见 [docs/DEPLOY.md](docs/DEPLOY.md)
> 🗺️ **Garmin 地图转换手册**（.img → BaseCamp .gmap）：见 [docs/GARMIN_IMGPACK.md](docs/GARMIN_IMGPACK.md)

---

## 开发流程：OpenSpec 驱动

**本项目强制使用 [OpenSpec](https://github.com/Fission-AI/OpenSpec) 规范驱动开发。**
所有改动必须先有规范、再有代码。

```
1. /openspec-propose "<需求>"   → 生成 proposal / design / specs delta / tasks
2. 审阅确认方案
3. /openspec-apply-change       → 按 tasks.md 实现
4. /openspec-archive-change     → 归档并合并 delta 回主 specs
```

| 路径 | 内容 |
|---|---|
| [openspec/project.md](openspec/project.md) | 项目上下文、环境、技术栈、**踩坑记录** |
| [openspec/specs/](openspec/specs/) | 当前已实现的能力（**行为的事实来源**） |
| [openspec/changes/](openspec/changes/) | 进行中的提案 |
| [openspec/changes/archive/](openspec/changes/archive/) | 已完成提案 |
| [AGENTS.md](AGENTS.md) | 流程硬性约束与代码约定 |

常用命令：

```bash
openspec list --specs          # 列出全部能力
openspec list                  # 列出进行中的提案
openspec validate --all        # 校验全部制品
openspec view                  # 交互式面板
```

**已经开始遵循该流程**：`openspec/changes/archive/2026-10-12-retro-tile-proxy-cache`
记录了瓦片代理与缓存的引入过程（含根因分析与实测结论）。

---

## 航点命名规则

KML 转出的 GPX 里，命名来源按优先级取第一个非空的：

| 优先级 | 来源 | 名称示例 | 说明 |
|---|---|---|---|
| 1 | 文件内 `<name>` | `#07 垭口` | 用户在 App 里手动命名过 |
| 2 | **用户备注** | `#07 左转进小路` | 人写的判断最准，只加序号、不再拼别的 |
| 3 | 所在位置 | `#07 3.07km · 1:08` | 序号 + 沿轨迹已走里程 + 累计耗时 |
| 4 | 照片文件名 | `#07 照片 1201359289` | 没有轨迹可定位时的兜底 |

备注会同时写进三个地方，哪个 App 读哪个字段都能看到：

    <name>#07 左转进小路</name>
    <desc>备注：左转进小路 · 已走 3.07km · 累计 1 小时 8 分 · 海拔 605 m</desc>
    <cmt>左转进小路</cmt>

轨迹名默认 `地点 日期 运动类型`（如 `英德雪山嶂环线 2023-02-18 爬山`），**地点在前**：
App 的列表按名称浏览，日期打头会把所有轨迹挤成同前缀。

### 项目空间（历史）

每次转换都会存成一个项目，落在 `data/projects/<id>/`：

    input.kml        原件（重转用）
    output.gpx       产物
    summary.json     摘要（命名来源、里程、转向）
    meta.json        参数与统计

账本在 `data/projects.db`。转换页底部的「历史项目」可以**打开回看、改参数重转、下载、删除**。
重转会生成新项目并保留旧的，方便对比。

保留策略：默认 **30 天或最近 200 个**，任一超限就淘汰最旧的。
用 `MAX_PROJECTS` / `PROJECT_RETENTION_DAYS` 调整，设为 0 表示不限制。

### 转向感知

命名会带上该处的拐弯情况：直行 / 左转 68° / 右转发卡弯 144°。
几何量用「跨 50m 的弦算航向」抑制 GPS 抖动，50° 以下视为直行，120° 以上算发卡弯。
开启 AI 时，转向会进入提示词，模型据此给出「右转切上山脊」「发卡弯折返」这类描述。

### AI 推测命名（可选，默认关闭）

勾选后调用一次大模型，按海拔剖面与行进节奏给航点起语义名（「碎石陡段」「雪山嶂顶」）。
名称属**推测**，可能与实际地物不符，导入后可在 App 里自行改名。失败自动回退到规则命名。

密钥只走环境变量或本机未入库的 `apikey` 文件，**永远不会写进响应与日志**：

    AI_API_KEY=sk-xxx            # 线上用环境变量
    AI_BASE_URL=https://api.deepseek.com
    AI_MODEL=deepseek-chat
    AI_TIMEOUT_SECONDS=30

`.gitignore` 已包含 `apikey`，禁止提交。

## 底图说明（重要）

回放页默认使用 **OpenTopoMap**（地形图，浏览器可直连）。

**Windy 必须经服务端代理。** 其响应头同时带
`access-control-allow-credentials: true` 与 `access-control-allow-origin: *`，
违反 CORS 规范，Chrome 会判 `ERR_BLOCKED_BY_ORB`，底图整片空白。
代理端点 `/api/tile/windy/{z}/{x}/{y}` 同源返回并带磁盘缓存。

**限速只作用于服务端与上游之间**，前端不做任何节流 ——
浏览器请求的是本站，命中缓存时根本不回源。

---

## 缓存

| 层 | 说明 |
|---|---|
| 浏览器 | `Cache-Control: immutable` + 内容哈希 ETag，同一瓦片零网络请求 |
| 服务端磁盘 | 默认上限 8GB，按最久未用 LRU 淘汰，磁盘剩余低于 3GB 停止写入 |
| 成品文件 | 与瓦片缓存分开存放；成品是交付物，过期才删 |

查看用量：`GET /api/tilecache/stats`

---

## 🎬 轨迹回放与分析（PC 端，纯前端）

行程结束后把多条轨迹丢进地图做分析、标注、出图，用于写文章配图。

**关键性质：完全跑在浏览器里，打开之后不消耗任何服务器资源**——不调用 `/api/*`，瓦片直连 Windy / OpenTopoMap（PC 自备网络即可），解析、渲染、截图全部本地完成。

### 能做什么

| 能力 | 说明 |
|---|---|
| **多文件导入** | 拖拽或点选，一次可导多条；支持 **GPX / KML / KMZ**（KMZ 用浏览器原生 `DecompressionStream` 解压，无需第三方库） |
| **多轨迹叠加** | 同时显示多条轨迹，每条白描边垫底，任何底图上都清晰 |
| 每条轨迹独立控制 | 改颜色（12 色调色板 + 取色器）、重命名、线宽、单独开关显示、名称标签开关、定位、删除 |
| **标记与注释** | 地图上点选或「点图取坐标」加标记，可写名称 + 多行注释，标记可拖动微调；列表里可编辑/定位/删除 |
| 行前工具 | 每 1/5/10 km 里程桩、起终点标记、方向箭头、导出 KML 内嵌路径点，统一由「工具层」管理可一键清除 |
| 底图切换 | Windy 户外 / OpenTopoMap 地形图 / OSM 标准 / 无底图，可调不透明度 |
| **截图分享** | 图例（自动带每条轨迹的颜色、里程、爬升）、地图标题，一键导出 PNG（1×/2×/3×） |
| 导出与备份 | 导出标记 GPX（回灌 Avenza / Guru Maps）、导出/导入方案 JSON（跨设备迁移），改动自动存 localStorage |

**快捷键**：`F` 缩放到全部 · `L` 图例 · `M` 加标记 · `Esc` 取消

### 兼容性

- KMZ 解压依赖 `DecompressionStream('deflate-raw')`：Chrome / Edge 80+、Safari 16.4+ 可用；不支持时会明确提示改用 GPX 或 KML。
- 底图与 `html2canvas` 走 CDN，离线环境下请先切「无底图」。
- 本地缓存有容量上限，轨迹很多很大时建议用「导出方案 JSON」留档。

---

## 📦 离线地图生成（服务端）

云服务器负责瓦片下载与 mbtiles 组装；手机浏览器上传 GPX、查看进度、下载成品 .mbtiles 导入 Avenza / Guru Maps 离线导航。

## 功能

- 手机网页上传 GPX，服务端解析轨迹并计算缓冲区内全部 XYZ 瓦片（去重）
- 默认参数：缓冲区 2500m、min-zoom 8、max-zoom 17、输出 GeoPackage
- 提交前先预估瓦片数；超单任务上限时前端二次确认后可放行（allow_oversize）
- 无轨迹时前端不加载预览底图（惰性初始化）；任务地址带 task ID，刷新不丢进度
- 历史地图列表：完成的地图永久保留，可随时下载或手动删除
- 两种输出格式（默认 GeoPackage，Avenza Maps 推荐底图格式）：
  - GeoPackage 1.2（.gpkg）：gpkg_contents / gpkg_spatial_ref_sys（EPSG:3857）/ gpkg_tile_matrix 金字塔 / tiles 表
  - MBTiles 1.0（.mbtiles）：tiles 表 + 唯一索引 + metadata（name/format/bounds/minzoom/maxzoom）
- 并发下载 + 全局请求间隔限流 + 失败重试（指数退避）+ 403/429 封禁检测自动终止
- 任务取消、60 分钟超时自动终止、并发任务数上限、失败/取消任务的临时文件自动清理（完成成品保留在历史）
- 任务状态 SQLite 持久化，服务重启后任务账本不丢
- 前端轨迹地图预览（Leaflet），进度轮询、错误提示

## 接口

| 接口 | 方法 | 说明 |
|---|---|---|
| /api/submit | POST | 上传 GPX + 参数（buffer_meters / min_zoom / max_zoom / concurrency / interval_ms / output_format / allow_oversize），返回 task_id |
| /api/estimate | POST | 只预估瓦片数不建任务（前端二次确认用） |
| /api/tasks | GET | 历史任务列表（含完成地图） |
| /api/tasks/{task_id} | DELETE | 手动删除任务及成品文件 |
| /api/status/{task_id} | GET | 任务状态：总瓦片、已下载、失败数、状态、下载链接 |
| /api/cancel/{task_id} | POST | 取消任务并清理临时文件 |
| /api/download/{task_id} | GET | 下载成品 .gpkg / .mbtiles |

## 本地开发

    python3 -m venv .venv
    .venv/bin/pip install -r requirements.txt
    cp .env.example .env      # 修改瓦片 URL 模板与代理
    ./run.sh                  # 默认 :8000
    .venv/bin/python -m pytest -v   # 含端到端流程与前端回归测试（回放页需 node 做语法检查）

## 部署（海外节点）

### 方式一：Docker（推荐）

1. 服务器要求：香港/新加坡节点，1 核 2G 起（容器运行内存更省）；国内节点无法访问瓦片源，禁止私自代理。
2. 安装 Docker（含 compose 插件），上传代码：

       git clone <本仓库> && cd gpx2mbtiles
       cp .env.example .env      # 修改 TILE_PROXY / AUTH_TOKEN 等

3. 构建并启动（数据落在 ./data，重启不丢；服务重启自动拉起）：

       docker compose up -d --build

4. 常用命令：

       docker compose logs -f        # 查看日志
       docker compose restart        # 重启服务
       docker compose down           # 停止
       docker compose pull && docker compose up -d   # 升级后重建

5. 反代 + HTTPS 同 systemd 方案（见下），在宿主 nginx/caddy 转发到 127.0.0.1:8000。
6. 镜像已含健康检查（/api/health）、非 root 运行、多阶段缓存。

### 方式二：venv + systemd

1. 服务器要求：香港/新加坡节点，1 核 2G 起；国内节点无法访问瓦片源，禁止私自代理。
2. 上传代码，建 venv 并安装依赖。
3. .env 配置（全部走环境变量，不硬编码）：
   - TILE_URL_TEMPLATE 瓦片模板（默认 Windy 户外图层：https://tiles.windy.com/v1/maptiles/outdoor/256/{z}/{x}/{y}/?lang=en，实测覆盖 z0–z19；v9.0/all 是占位假图不可用）
   - TILE_PROXY 代理地址（如 http://user:pass@host:port，服务端需可用代理访问瓦片源）
   - MAX_CONCURRENCY ≤8、REQUEST_INTERVAL_MS ≥100 —— 防封 IP
   - MAX_RUNNING_TASKS 同时运行任务数上限
   - TASK_TIMEOUT_SECONDS（默认 3600 = 60 分钟）
   - FILE_EXPIRY_SECONDS 成品过期时间（默认 3 天自动删除）
   - AUTH_TOKEN 个人自用建议设置：所有 /api/* 接口要求 X-API-Key 请求头，防匿名滥用
4. systemd 托管：

    [Unit]
    Description=gpx2mbtiles
    After=network.target

    [Service]
    WorkingDirectory=/opt/gpx2mbtiles
    EnvironmentFile=/opt/gpx2mbtiles/.env
    ExecStart=/opt/gpx2mbtiles/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
    Restart=always

    [Install]
    WantedBy=multi-user.target

5. 用 nginx/caddy 反代 + HTTPS（公网 IP 可配免费证书，无需域名）；下载走 HTTPS 才能在 iOS Safari 保存到文件 App。

## 已知限制（对应需求风险清单）

- iOS 锁屏限制：网页无法后台运行，任务期间需保持页面在前台；任务在服务端继续执行，回到页面后进度自动同步（服务端下载不受锁屏影响）。
- IP 封禁风险：限流、间隔、UA 伪装、403/429 自动熔断已内置，但无法 100% 规避。
- 服务器重启：运行中任务丢失（重置为排队状态）；已完成任务可从 SQLite 账本恢复。
- 流量：瓦片下载与 mbtiles 下载均消耗云服务器流量，建议开启流量告警。

## 项目结构

    app/
      main.py             FastAPI 入口 + 路由
      config.py           环境变量配置（全部可配）
      gpx_processor.py    GPX 解析 + 瓦片清单计算
      gpkg_builder.py     GeoPackage 1.2 写入（EPSG:3857 金字塔）
      mbtiles_builder.py  MBTiles 1.0 写入（含 TMS 行号翻转）
      tile_downloader.py  并发下载/限流/重试/封禁检测
      task_manager.py     任务账本（SQLite 持久化）/生命周期/清理
    web/index.html        手机前端（上传/预览/进度/下载）
    web/player.html       PC 端轨迹回放与分析（纯前端：多轨迹/KML/KMZ/标注/截图导出）
    Dockerfile            容器镜像（python:3.12-slim，非 root）
    compose.yaml          一键部署：端口 8000 + ./data 数据卷
    .dockerignore         构建排除（venv/data/tests 等）
    tests/                单元 + 端到端测试（内置假瓦片服务器）
    scripts/              开发用脚本：真实GPX分析、冒烟、重启恢复验证
    samples/              测试用真实 GPX（雨崩徒步 29km）
