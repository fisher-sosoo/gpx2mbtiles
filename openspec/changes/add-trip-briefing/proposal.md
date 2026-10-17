# Proposal · 行前指南（文字 + 天气）

## Why

现在一条轨迹能给出：转向点、垭口/牛场/山峰等地名、海拔剖面。
但这些是**零件**——出发前真正想知道的是「这条路难在哪、什么时候走、要小心什么」。

把零件合成一份**行前指南**：关键节点按里程排列、天气窗口、风险与易错点。
国产手表/手机的离线地图能告诉你「你在哪」，但不会告诉你「这个垭口下午容易起雾」。

## What Changes

- **天气预报**：接入 Open-Meteo（免费、无需 key），按轨迹中心与海拔取逐日预报。
- **可指定日期**：支持**单日**或**多日区间**；不填则取未来 7 天。
- **结构化指南**：路线概况、关键节点、天气窗口、风险提示、易错点。
- **AI 叙述**：有密钥时让模型把结构化数据写成可读的分析；无密钥时用规则模板，
  保证功能不依赖 AI。
- **可保存**：生成 Markdown 文本，页面可一键复制/下载，方便存到手机。
- **出图**：本轮先做文字；PNG 后续用前端 canvas 做（镜像没装 Pillow，不打算为它加依赖）。

## Capabilities

### New Capabilities

- `trip-briefing`：把轨迹、地名点与天气合成一份出发前可读的指南。

### Modified Capabilities

- `conversion-projects`：项目新增指南产物与生成状态。

## Impact

- 新增：`app/weather.py`、`app/trip_briefing.py`、`GET/POST /api/projects/{id}/guide`、`guide.json`。
- 修改：`app/config.py`、`web/convert.html`、测试。
- 依赖：无新增（urllib）。
- 合规：天气接口为公共免费服务，必须缓存并限流。
