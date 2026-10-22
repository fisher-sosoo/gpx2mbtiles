# Proposal

## Why

徒步回来最想看的是「这次身体到底付出了多少」：哪一段心率顶到了阈值、哪一段步频掉下来、
山脊和垭口的温差有多大。这些佳明都有，但它只肯让用户手动导出成文件——而导出的 GPX
往往连心率都不带（本仓库样例就是纯 `lat/lon/ele/time`），更不会有温度。
现有分析长图页 `/gpx/report.html` 是纯前端导入 GPX，所以这条链路永远拿不到完整的生理数据。

把账号一次性授权到服务器上，点一条活动就自动拉原始 FIT、解析、出图，可以省掉
「登录网页 → 导出 → 找文件 → 拖进来」这四步；也是第一次让心率/步频/温度真正进入分段分析。

## What Changes

- 新增独立页面 `web/garmin.html`（经 `/gpx/garmin.html` 访问）：列出最近 N 天的活动，
  点一条即生成长图。**现有 `/gpx/report.html` 的行为、外观与测试全部不变**。
- 新增后端 Garmin 通道：一次性预授权拿 OAuth token，运行时只做 refresh；
  按需拉取单条活动的原始 FIT 并落盘缓存，重复查看不再请求上游。
- 新增 FIT 解析：把心率、步频、温度与位置/海拔/时间一起归一化成轨迹 JSON。
- 长图的生理分析采用两张表（C 方案），代替把 9 列挤进一张宽表：
  - **运动表**：距离 | 用时 | 配速 | 升降
  - **生理表**：心率（均/最高）| 步频 | 温度
- 总览区增加平均心率、最高心率、平均步频与温度区间。
- 新增 `web/report-core.js`，只被新页面引用；旧页的内联副本保持原样，
  并用「防漂移」测试比对两处纯函数段，不一致即失败。
- 门户新增「Garmin 活动长图」入口卡片。

## Capabilities

### New Capabilities

- `garmin-activity-report`: 从 Garmin Connect 按需拉取单条活动、解析 FIT 生理数据、
  在浏览器生成长图（两表结构），以及与既有本地 GPX 出图页的共存约束。

### Modified Capabilities

- `service-portal`: 「统一入口」需要新增 Garmin 活动长图入口卡片。

## Impact

- 新增代码：`web/garmin.html`、`web/report-core.js`、`app/garmin_source.py`
  （授权检查 / 活动列表 / FIT 下载与解析）、`scripts/garmin_auth.py`（预授权 CLI）。
- 新增测试：`tests/test_garmin_source.py`（纯逻辑，用离线 FIT 夹具）、
  `tests/test_garmin_page.py`（页面静态断言与共享内核一致性）。
- 修改：`app/main.py`（`/api/garmin/*` 路由）、`app/config.py`（token 目录、默认天数）、
  `requirements.txt`、`compose.yaml`（挂载 token 目录）、`web/portal.html`、
  `.env.example`、`README.md`、`tests/test_player.py`（门户入口断言）。
- 不改：`web/report.html` 的任何渲染与解析逻辑；瓦片代理与限流策略。
- 依赖：新增 `garminconnect` 与 `fitparse` 两个 Python 包。
- 安全与合规：账号 token 等价于该 Garmin 账号的读写权限，实现里只调用只读接口；
  `/api/garmin/*` 与既有接口一样受 `AUTH_TOKEN` 约束；只支持逐条查看，
  不提供批量导出或对外服务。
