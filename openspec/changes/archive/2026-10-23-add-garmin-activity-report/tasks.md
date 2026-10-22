# Tasks

## 1. 依赖、配置与挂载

- [x] 1.1 `requirements.txt` 增加 `garminconnect` 与 `fitparse`，执行
      `pip install -r requirements.txt` 后 `python -c "import garminconnect, fitparse"` 通过
- [x] 1.2 `app/config.py` 增加 Garmin 相关设置（开关、令牌目录、默认天数、缓存上限、
      最小拉取间隔），全部走环境变量；验证：`python -c "from app.config import settings; print(settings.garmin_tokens)"`
      能打印且不读硬编码路径
- [x] 1.3 `compose.yaml` 增加 `./garmin_tokens:/app/garmin_tokens` 挂载与 `GARMINTOKENS` 环境变量，
      `.gitignore` 忽略 `garmin_tokens/`；验证：`docker compose config` 输出里能看到该挂载

## 2. 预授权 CLI

- [x] 2.1 新增 `app/garmin_auth.py`：交互式登录（邮箱、密码、MFA），把令牌写入 `GARMINTOKENS`，
      并提供 `--verify` 只校验不登录；验证：容器内 `python -m app.garmin_auth --verify`
      在已授权/未授权两种状态下给出不同且可读的输出
- [x] 2.2 定义统一的授权异常与中文提示（令牌缺失、令牌损坏、刷新失败三种），
      供接口层直接复用；验证：三种异常各有一条单元测试
- [x] 2.3 在 `tests/test_garmin_source.py` 覆盖授权异常路径：空目录、损坏的令牌文件、
      校验成功；验证：`pytest tests/test_garmin_source.py -q` 通过

## 3. 取数与 FIT 解析

- [x] 3.1 活动列表：按天数从 Garmin 取活动并归一化为 `id/name/date/distance/duration`，
      不返回原始响应；验证：单测用固定响应断言四个字段都存在
- [x] 3.2 下载单条活动的原始 FIT 到 `DATA_DIR/garmin/<id>.fit`，命中缓存时不再请求上游；
      验证：单测断言第二次调用不触发下载函数
- [x] 3.3 用 `fitparse` 解析为归一化轨迹 JSON：位置、海拔、时间、心率、步频、温度；
      心率 0 直接置 `null`，缺字段一律 `null`；验证：`python -m json.tool` 检查一份真实活动输出
- [x] 3.4 加入离线 FIT 夹具与单测：点数正确、时间单调递增、心率 0 被剔除、
      无温度时 `temp` 全为 `null`、解析失败时降级为仅位置/海拔/时间且不抛异常
- [x] 3.5 缓存上限与按最近使用淘汰：`GARMIN_CACHE_MAX_MB` 生效；验证：单测用小上限塞入多条活动，
      断言最旧的一条被清掉而最新的一条保留

## 4. 接口与鉴权

- [x] 4.1 新增 `/api/garmin/status`、`/api/garmin/activities`、`/api/garmin/activity/{id}`
      三个路由，全部挂 `require_api_key`；验证：`pytest tests/test_e2e.py -q` 新增用例通过
- [x] 4.2 失败关闭：`AUTH_TOKEN` 为空时三个接口返回 403 并说明原因；验证：清空环境变量后请求，
      断言 403 且响应含「AUTH_TOKEN」
- [x] 4.3 进程内节流：同一时刻只允许一个拉取，两次拉取间隔小于阈值时返回 429；
      验证：单测并发触发两次拉取，第二次拿到 429
- [x] 4.4 端到端用例：未授权 401、正常 200、上游失败返回可读错误且不 500；
      验证：`pytest tests/test_e2e.py -q` 全绿

## 5. 共享渲染内核

- [x] 5.1 新建 `web/report-core.js`，内容与 `web/report.html` 的
      `PURE_START…PURE_END` 段逐字一致；验证：`node --check web/report-core.js` 通过
- [x] 5.2 新增 `tests/test_garmin_page.py` 的防漂移用例：去空白后逐行比对两份纯函数段；
      验证：故意改动 `report-core.js` 一行，测试必须失败（改回后通过）

## 6. 新页面：活动列表与轨迹图

- [x] 6.1 新建 `web/garmin.html`：时间窗选择、活动列表、加载中与错误提示；
      验证：`node --check` 解析内联 JS 通过，浏览器直开与 `/gpx/garmin.html` 均可显示
- [x] 6.2 复用既有的 `apiFetch` 模式（带 `X-API-Key`、401 弹窗输入并记住）；
      验证：设了 `AUTH_TOKEN` 时手输 Key 后列表可正常加载
- [x] 6.3 轨迹图、总览、坡度构成、速度曲线、海拔剖面复用 `report-core.js` 出图；
      验证：与旧页同一活动的出图逐块目视一致（除新增区块）
- [x] 6.4 在 `tests/test_garmin_page.py` 加静态断言：关键元素 ID 存在、只调用
      `/api/garmin/*` 与 `/api/tile/*`、不调用任何生成类接口；验证：`pytest tests/test_garmin_page.py -q`

## 7. 生理分段与两张表

- [x] 7.1 实现 `enrichSplits`：按段聚合平均心率、最高心率、平均步频、平均温度，
      缺测段留空而不是 0；验证：node 驱动断言 0 值不参与均值、整段缺测时该段为 `null`
- [x] 7.2 渲染两张表：运动表（距离/用时/配速/升降）+ 生理表（心率均与最高/步频/温度），
      分段序号与边界对齐；验证：与 7.1 的断言数据逐行比对
- [x] 7.3 总览区增加平均心率、最高心率、平均步频与温度区间，温度标签写明「设备温度」；
      验证：静态断言标签文案存在
- [x] 7.4 降级：全程无心率/步频/温度时隐藏生理表与生理总览，其余区块照常；
      验证：用无生理字段的夹具出图，断言生理表未渲染且版面不留空白

## 8. 门户入口与文档

- [x] 8.1 `web/portal.html` 增加「Garmin 活动长图」卡片，链接 `/gpx/garmin.html`，
      说明写明含心率、步频与温度分段；验证：浏览器点开卡片可直达新页
- [x] 8.2 `tests/test_player.py` 断言门户含该入口，`tests/test_e2e.py` 断言
      `GET /garmin.html` 返回 200；验证：`pytest tests/test_player.py tests/test_e2e.py -q` 通过
- [x] 8.3 `README.md` 补：能力清单、预授权步骤（含 `docker exec` 命令）、
      `AUTH_TOKEN` 必须设置的原因、温度口径说明；验证：照文档从零执行一遍能跑到出图

## 9. 真实数据验收

- [x] 9.1 用一条真实徒步活动出图，把心率、步频、温度的总览值与 Garmin 网页端同一活动对照，
      偏差在 ±1 以内（取整误差）
- [x] 9.2 温度核对：结论是该设备不记录温度（FIT record 无 temperature，session 的
      avg/max_temperature 为 None），温度列按降级隐藏；已把该结论写进 README 与 design.md，
      换带传感器的设备后自动出现，无需改代码
- [ ] 9.3 全量回归：`pytest tests/ -q` 全绿，且 `web/report.html` 未出现在 diff 中

## Workflow follow-up

- 归档前确认 `openspec/specs/garmin-activity-report/spec.md` 与
  `openspec/specs/service-portal/spec.md` 的 delta 已合并，然后再归档本 change。