# Design

## Context

- 前端是**无构建步骤的原生 JS**，`web/` 由 `app/main.py` 的 StaticFiles 以 `/` 与 `/gpx`
  双前缀提供；新增页面不需要改 Caddy。
- 既有分析长图页 `web/report.html` 是单文件内联 JS：解析 GPX、算派生序列、canvas 出图，
  纯函数集中在 `/* PURE_START */ … /* PURE_END */` 之间，`tests/test_player.py` 用正则抽出这段
  在 node 里跑断言。**这段锚点是本变更得以"共用而不改动"的前提。**
- 分段表当前 6 列，画布固定宽 1080；再加心率/步频/温度三列会挤成一团。
- 后端已有统一的接口鉴权依赖 `require_api_key`（`AUTH_TOKEN` 为空时放行），
  前端已有 `apiFetch` 封装（带 `X-API-Key`，401 时弹窗输入）。
- 容器以非 root 用户 `appuser`（uid 10001）运行，`DATA_DIR=/app/data` 是唯一持久卷；
  Dockerfile 只 `COPY app` 与 `COPY web`。

## Goals / Non-Goals

**Goals:**

- 一次点击完成「选活动 → 拉数据 → 出图」，不再经过手工导出。
- 分段统计从「运动量」扩展到「身体反应」：心率、步频、温度各成一组。
- 旧页零行为变化，且两个页面的共享纯函数不会悄悄分叉。

**Non-Goals:**

- 不做心率区间（Z1–Z5）、训练负荷、恢复建议——这些要先定最大心率口径，另开变更。
- 不做服务端渲染长图，不引入 Pillow。
- 不做活动列表的分页浏览、批量导出、定时同步。
- 不改回放页（`player.html`），本变更里它仍不显示心率。

## Decisions

### 1. 直接依赖 `garminconnect` 库，而不是把 garmin_mcp 跑起来

- 需要的只有三个动作：登录、列活动、下载活动文件。`python-garminconnect` 直接提供，
  且它替我们处理了 garth 的 OAuth1→OAuth2 刷新、区域站点（`is_cn`）与常见反爬头。
- 备选：把 [garmin_mcp](https://github.com/Taxuspt/garmin_mcp) 当 sidecar，通过 MCP 协议调用。
  否决理由：MCP 是给 LLM 客户端用的，这里等于自己实现一个 MCP 客户端 + 多一个进程，
  只为复用两个函数；而且它的工具输出是给人看的字符串，还要再解析一遍。
- 备选：自己用 `garth` 拼 HTTP。否决：重复造轮子，登录态处理是最容易出错的部分。

### 2. 默认只存令牌；自动续期是显式开关

- `app/garmin_auth.py`（`python -m app.garmin_auth`）做一次交互式登录，
  令牌写到 `GARMINTOKENS` 指向的目录（默认 `/app/garmin_tokens`），由 compose 挂载到宿主
  `./garmin_tokens`。运行时只读取并刷新。
- 默认不改这条路：令牌刷新由 garth 自动完成，一年内不需要人工干预。
- **可选**：设 `GARMIN_AUTO_RELOGIN=1` 且给出 `GARMIN_EMAIL`/`GARMIN_PASSWORD` 时，
  令牌失效会自动重登一次并覆盖令牌。密码只在进程环境里，不写盘、不进日志；
  重试有 5 分钟冷却，避免密码错了把账号刷进风控。
- 代价必须说清楚：开启后服务器上就持有一份长期凭据，容器被攻破 = 账号被接管。
  默认关闭，需要长间隔免维护时才开。
- 令牌目录**不放进 `DATA_DIR`**：`data/` 是给下载文件用的，任何把它整体暴露的改动都会
  顺带泄露账号。该目录写进 `.gitignore`。

### 3. 数据源用原始 FIT，不用 GPX/TCX

| 格式 | 心率 | 步频 | 温度 | 备注 |
|---|---|---|---|---|
| GPX | 有则带 | 有则带 | 有则带 | 取决于导出方式，本仓库样例一个字段都没有 |
| TCX | ✅ | ✅ | ❌ | 标准里没有温度 |
| **FIT（原始）** | ✅ | ✅ | ✅ | 记录里位置与生理同属一条 message，天然对齐 |

- 温度是本变更的新增维度，只有 FIT 能保证拿到，所以不做"GPX 优先"的折中。
  **但 FIT 只是必要条件，不是充分条件**：实测账号里那条徒步活动的 session 里
  `avg_temperature` 就是 `None`，record 里只有 `hr/cad/position/altitude`，
  说明设备本身没有温度传感器。所以温度列必须按实际数据隐藏，不能默认画出来。
- 实测还发现：`download_activity(ORIGINAL)` 返回的是 **zip**（`PK\x03\x04`），
  不是裸 FIT，解析前要剥一层。这条写进实现，避免下次又被"Invalid .FIT File Header"绊住。
- 备选：Garmin 的 `activityDetails` JSON。字段名随接口版本漂移，且不保证含温度。

### 4. 归一化成一种轨迹 JSON

```json
{ "id": 1234567890, "name": "上雨崩-冰湖", "start": "2025-12-10T08:49:05+08:00",
  "points": [ { "t": 1765327745, "lat": 28.3996, "lng": 98.7748,
                "ele": 3232.8, "hr": 121, "cad": 78, "temp": 9 } ] }
```

- `t` 为秒级时间戳；`hr`/`cad`/`temp` 缺测一律 `null`，不用 0 或 -1 代替。
- 前端只认这一种结构，FIT 的细节留在后端，页面不引入 FIT 解析库。

### 5. 缓存：一次拉取，永久可用

- `DATA_DIR/garmin/<id>.fit`（原件）+ `<id>.json`（归一化结果）。
- 活动记录上传后不变，所以缓存**永不自动失效**；只有显式 `?refresh=1` 才覆盖。
- 代价是磁盘随活动数线性增长（单条约 1–3 MB）。设 `GARMIN_CACHE_MAX_MB`（默认 512），
  超出时按最近使用时间淘汰；不做后台定时任务。

### 6. 时间对齐按记录，不按下标

- FIT 的一条 `record` 同时含位置与心率/步频/温度，直接成对读，不需要 join。
- 只有个别字段缺失时补 `null`，**绝不**用相邻点或数组下标凑——那会把心率错配到别的坡上。
- 时间统一按 UTC 存储，展示时用活动自带的本地时区。

### 7. 心率 0 = 缺测

- 胸带脱落会记 0。解析时直接置 `null`，于是所有统计（均值/最高/分段）天然不受污染。
- 这条规则写在解析层而不是渲染层，避免每个消费方各修一遍。

### 8. 温度是设备温度，不是气温

- FIT 的 `temperature` 来自设备内部传感器，受体温与暴晒影响，通常高于真实气温。
- 图上标签写「设备温度」，只用来看**相对变化**（垭口 vs 谷底），不做气温换算，
  也不与 `app/weather.py` 的预报温度混在一张图里比较。

### 9. 前端：新页 + 共享内核 + 防漂移测试（C 方案）

- 新页 `web/garmin.html`，自带页面逻辑；渲染的纯函数来自 `web/report-core.js`。
- 旧页 `web/report.html` **一个字节都不改**，它的内联纯函数段原样保留。
- `tests/test_garmin_page.py` 做两件事：新页必须通过 `node --check`；
  把旧页 `PURE_START…PURE_END` 与 `report-core.js` 的同名段做「去空白后逐行比对」，
  不一致即失败。
- 为了让比对永远成立，**新增的生理聚合（`enrichSplits`）写在新页自己的脚本里**，
  不进共享内核；共享内核只保留与旧页完全一致的几何/统计/色带函数。
- 备选：直接改旧页让它引用共享文件。否决：用户明确要求旧页不动，且会牵动 4 个既有测试。

### 10. 两张表（C 方案）

- 运动表：`距离 | 用时 | 配速 | 升降`；生理表：`心率(均/最高) | 步频 | 温度`。
- 两张表列宽、行高、表头样式与旧页一致，表间留 24px；分段序号与边界完全对齐。
- 备选：9 列一张表（横向挤压，字号被迫缩小）、合成列 `142·84·9°`（信息密度高但不好读）。

### 11. 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/garmin/status` | 是否已授权、令牌目录、最近一次刷新结果 |
| GET | `/api/garmin/activities?days=30` | 活动列表（名称/日期/距离/耗时） |
| GET | `/api/garmin/activity/{id}` | 归一化轨迹 JSON；`?refresh=1` 强制重拉 |

三个接口都挂 `require_api_key`。

### 12. 失败关闭：没设 `AUTH_TOKEN` 就不提供 Garmin 接口

- 既有 `require_api_key` 在 `AUTH_TOKEN` 为空时**放行**——对瓦片无所谓，但这个接口能读
  一个人的完整运动健康记录。
- 因此 `/api/garmin/*` 额外加一条：`AUTH_TOKEN` 为空时直接返回 403 并说明原因，
  不跟随"空即放行"的默认。

### 13. 限流：进程内节流，不做队列

- 同一时刻只允许一个拉取任务，两次拉取之间至少间隔 1 秒；
  并发请求直接返回 429 + 可读提示。目的只是别把 Garmin 惹毛，不需要任务系统。

## Risks / Trade-offs

- [令牌泄露等于账号被读] → 只调用只读接口；令牌目录独立挂载、不进 `data/`、不进 git；
  `/api/garmin/*` 强制鉴权（决策 12）。
- [令牌约一年过期，需要人工重授权] → `/api/garmin/status` 明确报告状态；
  列表与取数接口在刷新失败时返回"请重新执行预授权"，而不是 500 或超时。
- [Garmin 私有接口变动] → 解析失败时降级为「只有位置/海拔/时间」照常出图，
  不整页报错；原始 `.fit` 留在缓存里，解析器修好后可重解析而不必重拉。
- [设备温度不是气温] → 标签明确写「设备温度」，不做换算与混比（决策 8）。
- [不同设备字段不同] → 缺字段降级成缺列，与旧页的降级规则一致。
- [两份渲染代码漂移] → 防漂移测试（决策 9）把它变成红灯而不是静默分歧。
- [磁盘增长] → `GARMIN_CACHE_MAX_MB` + 按最近使用淘汰。

## Migration Plan

1. `requirements.txt` 增加 `garminconnect`、`fitparse`，重建镜像。
2. `docker-compose.yml` 增加 `./garmin_tokens:/app/garmin_tokens` 挂载与
   `GARMINTOKENS=/app/garmin_tokens`；`.gitignore` 加上该目录。
3. `.env` 设好 `AUTH_TOKEN`（不设则 Garmin 接口 403）。
4. `docker exec -it gpx2mbtiles python -m app.garmin_auth` 完成一次授权（含 MFA）。
5. 打开 `/gpx/garmin.html` 验证列表 → 出图。
6. 回滚：删掉页面与三个路由即可；旧页与瓦片链路完全独立，令牌目录可直接删除。

## Open Questions

- 心率区间（Z1–Z5）需要最大心率来源（年龄公式 / 实测 / 手动配置），本变更不做，
  但两表结构预留了加列的余地。
- 是否把生理摘要喂给行前指南（`app/trip_briefing.py`）——那是行前功能，与事后分析是两回事，
  另行讨论。
