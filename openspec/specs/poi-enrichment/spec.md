# poi-enrichment Specification

## Purpose
依据 OpenStreetMap 的公共地名数据，为一条轨迹补充「垭口、牛场、营地、山峰、湖泊、
过河点」等有名字的航点，并按几何关系与重要性过滤，避免刷屏与误标。

## Requirements

### Requirement: 按区域查询地名

系统 SHALL 依据轨迹的包围盒向 OSM 查询有名字的地物。

#### Scenario: 查询范围

- **WHEN** 用户对某个项目发起补点
- **THEN** 系统 SHALL 用该轨迹的外接矩形（含少量外扩）作为查询范围
- **AND** SHALL 查询垭口、山隘、营地、山屋、避难所、山峰、湖泊、村镇
- **AND** SHALL 查询河流以判断过河点

#### Scenario: 分层查询

- **WHEN** 执行查询
- **THEN** 节点类地物 SHALL 用不带几何的查询（节点自带坐标）
- **AND** 河流几何 SHALL 单独查询，且该查询失败时 SHALL NOT 影响主结果
- **AND** 主查询 SHALL NOT 拉取面要素的完整几何，避免查询耗时成倍增长

#### Scenario: 代理自愈

- **WHEN** 查询失败需要重试
- **THEN** 系统 SHALL 在多个代理端口中轮换
- **AND** SHALL 在全部失败后返回可读错误并说明公共查询服务可能过载

#### Scenario: 公共设施礼貌

- **WHEN** 调用公共查询服务
- **THEN** 系统 SHALL 带可识别的 User-Agent
- **AND** SHALL 有超时与失败重试上限
- **AND** SHALL NOT 在短时间内重复查询同一区域

### Requirement: 异步执行与缓存

地名查询 SHALL 以异步任务执行，结果缓存到项目内。

#### Scenario: 发起查询

- **WHEN** 用户发起补点且缓存不存在
- **THEN** 系统 SHALL 立即返回「已开始」，不得阻塞等待查询完成
- **AND** 查询 SHALL 在后台进行

#### Scenario: 查询完成

- **WHEN** 后台查询完成
- **THEN** 系统 SHALL 把筛选后的结果写入项目目录
- **AND** 再次打开该项目 SHALL 直接读缓存，不重新查询

#### Scenario: 查询失败

- **WHEN** 上游超时、被限流或返回异常
- **THEN** 系统 SHALL 记录失败原因并允许重试
- **AND** SHALL NOT 影响项目本身的 GPX 与摘要

#### Scenario: 强制刷新

- **WHEN** 用户要求重新查询
- **THEN** 系统 SHALL 忽略已有缓存并重跑

### Requirement: 按类型过滤

系统 SHALL 依据地物类型采用不同的距离与取舍规则。

#### Scenario: 贴近路线的要素

- **WHEN** 垭口、山隘、营地、山屋、避难所距轨迹不超过 200 米
- **THEN** 系统 SHALL 标为航点

#### Scenario: 地标性山峰

- **WHEN** 山峰距轨迹不超过 3 公里且带有名称
- **THEN** 系统 SHALL 标为航点（作为可见地标）
- **AND** 超出该距离 SHALL 忽略

#### Scenario: 村镇

- **WHEN** 村镇位于轨迹起点或终点 200 米内
- **THEN** 系统 SHALL 标注
- **AND** 路线只是穿过村镇时 SHALL NOT 标注

#### Scenario: 湖泊

- **WHEN** 湖泊距轨迹不超过 300 米且带有名称
- **THEN** 系统 SHALL 标注

#### Scenario: 河流只在过河处

- **WHEN** 轨迹与河流或溪流的线要素相交
- **THEN** 系统 SHALL 在该过河点标注一次
- **AND** 仅沿河并行但未过河时 SHALL NOT 标注
- **AND** 同一条河 SHALL NOT 重复标注多次

### Requirement: 去重与数量控制

系统 SHALL 对同名地物去重，并限制单条轨迹补点的总数，避免刷屏。

#### Scenario: 同名去重

- **WHEN** 多个同名地物都被选中
- **THEN** 系统 SHALL 只保留距轨迹最近的一个

#### Scenario: 密度上限

- **WHEN** 筛选出的要素数量超过配置上限
- **THEN** 系统 SHALL 按重要性截断
- **AND** SHALL 在结果中说明被截断的数量

### Requirement: 结果并入 GPX

系统 SHALL 允许把地名点并入导出的 GPX，同时保持原有轨迹不变。

#### Scenario: 作为附加航点

- **WHEN** 补点结果已存在且用户要求导出
- **THEN** 系统 SHALL 把地名点作为额外航点写入 GPX
- **AND** 这些航点 SHALL 使用地物原名
- **AND** SHALL NOT 占用普通航点的序号
- **AND** SHALL 在描述中标明来源与距离

### Requirement: 功能入口常驻

系统 SHALL 让项目页各功能入口在项目存在时始终可见且可操作。

#### Scenario: 对话入口

- **WHEN** 项目存在但尚无地名点
- **THEN** 对话面板 SHALL 可见
- **AND** 输入框 SHALL 处于禁用态并提示先补充地名点
- **AND** SHALL NOT 隐藏整个面板

#### Scenario: 有地名点后

- **WHEN** 补点完成
- **THEN** 对话输入 SHALL 自动恢复可用

### Requirement: 指南可读性

系统 SHALL 把生成的指南渲染为可读内容而非 Markdown 源码。

#### Scenario: 渲染

- **WHEN** 指南生成完成
- **THEN** 页面 SHALL 以标题、表格、列表等等价形式展示
- **AND** 复制与下载 SHALL 仍输出 Markdown 原文

#### Scenario: 安全

- **WHEN** 渲染指南内容
- **THEN** 系统 SHALL 先做 HTML 转义再解析结构
- **AND** SHALL NOT 直接插入未转义内容

### Requirement: 分析针对本路线

指南中的 AI 分析 SHALL 只针对当次路线，不给通用建议。

#### Scenario: 禁止套话

- **WHEN** 生成分析
- **THEN** SHALL NOT 出现「导入手机」「保持离线可用」「提前下载轨迹」这类与具体路线无关的建议

#### Scenario: 装备按条件

- **WHEN** 分析提到装备
- **THEN** SHALL 只在天气或地形条件相关时提：降雪结冰提防滑、降雨提防水与备换、
  大风或低温提保暖防失温、需手脚并用的攀爬提手套
- **AND** SHALL NOT 罗列徒步鞋、登山杖、头灯这类默认装备

#### Scenario: 位置可定位

- **WHEN** 分析提到风险位置
- **THEN** SHALL 给出里程或节点名，便于在地图上定位

#### Scenario: 补充信息

- **WHEN** 用户填写了补充信息（到达时间、是否商团轻装等）
- **THEN** 系统 SHALL 把它作为上下文一并交给模型
- **AND** SHALL 在指南中保留该字段以便追溯

### Requirement: 航点自动显示

回放页 SHALL 在导入带路径点的 GPX 时自动显示这些点。

#### Scenario: 导入即显示

- **WHEN** 导入的 GPX 含 `<wpt>`
- **THEN** 系统 SHALL 自动把路径点渲染为标记
- **AND** SHALL 提示已自动标出的数量
- **AND** SHALL NOT 要求用户先点击某个按钮
