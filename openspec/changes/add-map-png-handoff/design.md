# Design

## Context

回放页已具备：OpenTopoMap 底图、轨迹渲染、路径点标记、PNG 导出（1×/2×/3×，
自己按地理坐标绘制到 canvas，不依赖 html2canvas）。转换页没有地图。

## Goals / Non-Goals

**Goals:**

- 用最小改动让用户拿到「地图 + 路线 + 地名点」的 PNG。
- 不破坏回放页「纯前端、不调 /api」的既有约定（有测试守着）。

**Non-Goals:**

- 不在转换页引入 Leaflet 重造地图。
- 不做服务端渲染（镜像没装 Pillow，不打算加）。

## Decisions

### D1 · 交接而不是重造

把「含地名点的 GPX」交给回放页，直接复用已有地图与出图逻辑。
在转换页重建一套，既有维护成本又会和回放页产生视觉不一致。

### D2 · 用 sessionStorage，不新增接口调用

回放页有一条硬约束：不得调用 `/api/`（除瓦片代理）。若让它去 fetch
`/api/projects/{id}/export`，就破了这条约定。

改由**转换页**（本来就在调 `/api/`）取好 GPX，写进 sessionStorage，
回放页只读会话存储。数据留在本机，不产生新请求，约束不破。

**替代方案**：URL 传参 —— 否决，GPX 动辄几百 KB，URL 放不下。

### D3 · 接到即清

`pickUpHandoff` 读完立刻 `removeItem`，否则用户下次正常打开回放页会被
重复导入一次。

### D4 · storage 写失败要提示

内联 SVG/大轨迹可能撑满配额。写入失败必须提示，不能让用户点了没反应。

## Risks / Trade-offs

- **[sessionStorage 配额]** → 单项目 GPX 通常几十到几百 KB，配额一般 5MB；
  超出时明确报错。
- **[旧浏览器没有 File 构造器]** → 退化提示手动导入，不影响页面其余功能。
