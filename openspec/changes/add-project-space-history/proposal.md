# Proposal · 转换项目空间与历史管理

## Why

现在的 `/api/convert` 是**无状态**的：转换完把 GPX 丢给浏览器，服务端什么都不留。
刷新页面就没了，想「换个参数再试一次」必须重新上传；想回看三天前的转换结果也没有入口。

后续几个方向（OSM 补点、行前指南、多轮对话）都需要一个**持久化的载体**：
POI 结果存哪、AI 原始返回存哪、行前指南挂在哪。没有项目空间，这些功能都得各自造存储。

## What Changes

- **每次转换落一个项目**：`data/projects/<id>/` 下存原件、产物 GPX、摘要、元数据。
- **SQLite 账本**：`projects.db` 记索引，支持列表、分页、按时间倒序。
- **可重入**：打开历史项目回看 GPX 与航点表；用保存的原件改参数重转（生成新项目，旧的保留）。
- **可删除**：删项目同时清目录。
- **自动淘汰**：默认保留 30 天或最近 200 个，超出按最久未用清理。
- **页面入口**：转换页新增「历史项目」区块，列出最近 30 个，带打开/重转/下载/删除。

## Capabilities

### New Capabilities

- `conversion-projects`：把每次转换作为可回看、可重转、可删除的项目空间来管理。

### Modified Capabilities

- `track-conversion`：`/api/convert` 除返回 GPX 外，同时落项目并返回 `project_id`。

## Impact

- 新增：`app/project_store.py`、`data/projects/`、`data/projects.db`。
- 修改：`app/main.py`（转换落盘 + 5 个项目接口）、`app/config.py`（保留策略）、
  `web/convert.html`（历史区块）、`tests/conftest.py`、测试文件。
- 依赖：无新增（复用标准库 sqlite3）。
- 兼容性：`/api/convert` 响应新增字段，属向后兼容的新增。
- 磁盘：单项目通常几十 KB，200 个约数 MB；与瓦片缓存分开淘汰。
