# Spec Delta

## ADDED Requirements

### Requirement: 岔路口查询

系统 SHALL 用轨迹周边路网判断转折位置是否存在路口。

#### Scenario: 查询范围

- **WHEN** 项目需要路口判断
- **THEN** 系统 SHALL 用轨迹外接矩形（含少量外扩）查询路网线要素
- **AND** SHALL 只查询道路类要素，不查询面要素与无关标签
- **AND** SHALL 带可识别的 User-Agent 与超时

#### Scenario: 独立于地名查询

- **WHEN** 执行路口查询
- **THEN** 该查询 SHALL 与地名查询相互独立
- **AND** 任一失败 SHALL NOT 影响另一个
- **AND** 结果 SHALL 可缓存，避免重复请求同一区域

#### Scenario: 失败降级

- **WHEN** 路口查询失败
- **THEN** 系统 SHALL 继续生成结果
- **AND** 转向 SHALL 退回纯几何判断
- **AND** SHALL 在结果中透出降级原因，便于排查

### Requirement: 岔路判定

系统 SHALL 从路网几何中判定轨迹上的路口位置。

#### Scenario: 判定条件

- **WHEN** 轨迹上某位置附近同时存在**两条及以上不同**的道路
- **THEN** 该位置 SHALL 判定为岔路口
- **AND** 同一个路口的相邻采样点 SHALL 合并为一处
- **AND** 记录该路口交汇的道路条数

#### Scenario: 单条路不算路口

- **WHEN** 轨迹附近只有一条道路
- **THEN** 该位置 SHALL NOT 判定为岔路口

#### Scenario: 里程化

- **WHEN** 判定出岔路口
- **THEN** 系统 SHALL 给出其沿轨迹的里程
- **AND** 地点名 SHALL 在可用时一并给出

### Requirement: 路口转向

系统 SHALL 区分「路口转向」与「地形转向」。

#### Scenario: 路口转向

- **WHEN** 一个显著转向落在已判定的岔路口附近
- **THEN** 该转向 SHALL 标记为路口转向
- **AND** 描述中 SHALL 体现交汇道路数量或可选方向
- **AND** 在地图上 SHALL 用与地形转向不同的样式标出

#### Scenario: 地形转向

- **WHEN** 一个显著转向附近没有岔路
- **THEN** 该转向 SHALL 标记为地形转向
- **AND** SHALL NOT 被当作主要决策点提示

#### Scenario: 提示优先级

- **WHEN** 生成文字提示或模型上下文
- **THEN** 路口转向 SHALL 优先于地形转向
- **AND** 地形转向大量存在时 SHALL 只保留最显著的若干处
