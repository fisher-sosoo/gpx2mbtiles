# GPX-to-MBTiles 云服务

> 云服务器负责瓦片下载与 mbtiles 组装；手机浏览器上传 GPX、查看进度、下载成品 .mbtiles 导入 Avenza / Guru Maps 离线导航。
>
> ⚠️ 仅限个人自用：Windy-Outdoor 服务条款禁止批量爬取瓦片。请务必开启限流与请求间隔、部署在海外节点、不得对外提供服务。

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
    .venv/bin/python -m pytest -v   # 47 个测试，含端到端流程

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
    Dockerfile            容器镜像（python:3.12-slim，非 root）
    compose.yaml          一键部署：端口 8000 + ./data 数据卷
    .dockerignore         构建排除（venv/data/tests 等）
    tests/                单元 + 端到端测试（内置假瓦片服务器）
    scripts/              开发用脚本：真实GPX分析、冒烟、重启恢复验证
    samples/              测试用真实 GPX（雨崩徒步 29km）
