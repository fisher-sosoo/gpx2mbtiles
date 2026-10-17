# Spec Delta

## ADDED Requirements

### Requirement: 地图出图交接

系统 SHALL 允许把项目里「含地名点的 GTrack」交给回放页，用于地图查看与 PNG 出图。

#### Scenario: 一键交接

- **WHEN** 用户在项目页点击「在地图上查看并出图」
- **THEN** 页面 SHALL 取得该项目**含地名点**的 GPX
- **AND** SHALL 把内容与文件名暂存到浏览器会话存储
- **AND** SHALL 跳转到回放页

#### Scenario: 回放页接收

- **WHEN** 回放页加载且会话存储里存在交接数据
- **THEN** 系统 SHALL 自动按 GPX 导入该轨迹
- **AND** 其中的地名点 SHALL 作为路径点标记显示
- **AND** SHALL 清除交接数据，避免下次打开重复导入

#### Scenario: 保持纯前端

- **WHEN** 回放页接收交接数据
- **THEN** 系统 SHALL NOT 新增任何服务端接口调用
- **AND** SHALL 仅通过浏览器会话存储传递

#### Scenario: 存储不可用

- **WHEN** 浏览器存储已满或被禁用
- **THEN** 系统 SHALL 给出可读提示，不得静默失败

#### Scenario: 出图

- **WHEN** 轨迹已在回放页显示
- **THEN** 用户 SHALL 能用回放页既有的 PNG 导出获得带底图与标记的图片
- **AND** 支持多倍率输出
