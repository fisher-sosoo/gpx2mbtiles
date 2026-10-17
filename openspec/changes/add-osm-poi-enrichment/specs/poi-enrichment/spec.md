# Spec Delta

## Purpose

依据 OpenStreetMap 的公共地名数据，为一条轨迹补充「垭口、牛场、营地、山峰、湖泊、
过河点」等有名字的航点，并按几何关系与重要性过滤，避免刷屏与误标。

## ADDED Requirements

### Requirement: 按区域查询地名

系统 SHALL 依据轨迹的包围盒向 OSM 查询有名字的地物。

#### Scenario: 查询范围

- **WHEN** 用户对某个项目发起补点
- **THEN** 系统 SHALL 用该轨迹的外接矩形（含少量外扩）作为查询范围
- **AND** SHALL 查询垭口、山隘、营地、山屋、避难所、山峰、湖泊、河流、村镇

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

#### Scenario: 同名去重

- **WHEN** 多个同名地物都被选中
- **THEN** 系统 SHALL 只保留距轨迹最近的一个

#### Scenario: 密度上限

- **WHEN** 筛选出的要素数量超过配置上限
- **THEN** 系统 SHALL 按重要性截断
- **AND** SHALL 在结果中说明被截断的数量

### Requirement: 结果并入 GPX

#### Scenario: 作为附加航点

- **WHEN** 补点结果已存在且用户要求导出
- **THEN** 系统 SHALL 把地名点作为额外航点写入 GPX
- **AND** 这些航点 SHALL 使用地物原名
- **AND** SHALL NOT 占用普通航点的序号
- **AND** SHALL 在描述中标明来源与距离
