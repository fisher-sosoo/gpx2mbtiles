# Proposal · 地图出图（交给回放页）

## Why

方向 #5 原本要的是「地图叠加路线的 PNG，标出需要留意的点」，文字只是兜底。
现在指南只有文字，看不到路线长什么样。

回放页已经有完整能力：OpenTopoMap 底图、轨迹渲染、地名点作为标记、PNG 导出（1×/2×/3×）。
在转换页重造一套地图既浪费又容易不一致。

## What Changes

- **一键交接**：转换页新增「在地图上查看并出图」，把**含地名点的 GPX** 交给回放页。
- **交接方式用 sessionStorage**：不新增接口调用，回放页保持「纯前端、不调 /api」的既有约定。
- **地名点自动成为标记**：导出 GPX 里的 `<wpt>` 就是回放页的标记，带名称标签。
- **不改动**回放页已有的导入、渲染与 PNG 导出逻辑。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `conversion-projects`：项目页新增「在地图上查看并出图」入口，与回放页交接数据。
- `track-playback`：新增「从其它页面接收轨迹」的入口，仍保持纯前端。

## Impact

- 修改：`web/convert.html`（按钮 + 交接）、`web/player.html`（启动时检查交接数据）。
- 测试：新增交接与按钮的静态断言。
- 依赖：无新增（不需要在转换页引入 Leaflet）。
