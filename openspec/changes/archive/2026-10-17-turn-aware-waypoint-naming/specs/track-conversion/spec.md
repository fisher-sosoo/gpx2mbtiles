# Spec Delta

## MODIFIED Requirements

### Requirement: 航点位置换算

系统 SHALL 为每个航点在轨迹上定位，算出「已走里程」与「累计耗时」，用于航点命名。

#### Scenario: 航点落在轨迹上

- **WHEN** 航点与轨迹的某个位置重合或贴近
- **THEN** 系统 SHALL 取该处沿轨迹从起点算起的累计里程
- **AND** 累计里程 SHALL 从轨迹起点开始逐段累加，对同一轨迹单调不减

#### Scenario: 定位方式

- **WHEN** 航点与轨迹顶点重合
- **THEN** 系统 SHALL 定位到该顶点，里程取其累计值
- **AND** 不重合时 SHALL 取最近位置，里程按到该位置的插值计算

#### Scenario: 累计耗时

- **WHEN** 航点带有时间且轨迹有时间
- **THEN** 累计耗时 SHALL 为「航点时间 − 轨迹起点时间」
- **AND** 结果 SHALL NOT 为负；航点时间缺失或早于起点时 SHALL 改用该定位处在轨迹上的耗时

#### Scenario: 无轨迹

- **WHEN** 文件里没有可用轨迹，只有航点
- **THEN** 系统 SHALL 退化为「相邻航点首尾连线的累计里程」
- **AND** SHALL 在摘要中标注该退化

## ADDED Requirements

### Requirement: 转向识别

系统 SHALL 依据轨迹几何计算每个位置的转向角度，用于命名与行前分析。

#### Scenario: 转角计算

- **WHEN** 需要某位置的转向
- **THEN** 系统 SHALL 取该位置前后各一段固定距离的航向，用「离开航向 − 进入航向」得到转角
- **AND** 转角 SHALL 归一化到 -180°~180°，负值表示左转、正值表示右转
- **AND** 前后距离不足或两点重合时 SHALL 视为无有效转向

#### Scenario: 噪声抑制

- **WHEN** 轨迹存在 GPS 抖动
- **THEN** 航向 SHALL 基于两点间的弦（跨越若干点）计算，不得直接用相邻两点
- **AND** 转角绝对值小于阈值时 SHALL 视为「直行」而非一次转向

#### Scenario: 发卡弯标记

- **WHEN** 转角绝对值超过发卡弯阈值
- **THEN** 系统 SHALL 标记为发卡弯
- **AND** 该标记 SHALL 在提供给模型的上下文中单独体现

#### Scenario: 摘要暴露

- **WHEN** 转换完成
- **THEN** 摘要中每个航点 SHALL 包含其转向信息（方向与度数，或「直行」）
- **AND** 页面 SHALL 能展示该字段

### Requirement: AI 转向感知

系统 SHALL 在调用模型时提供转向上下文，使航点名称能反映路口特征。

#### Scenario: 提示词包含转向

- **WHEN** 开启了 AI 命名
- **THEN** 提供给模型的航点表格 SHALL 包含转向列
- **AND** SHALL NOT 因缺少转向信息而失败（无转向时留空）

#### Scenario: 命名侧重转向

- **WHEN** 某航点处存在明显转向
- **THEN** 提示词 SHALL 要求模型优先描述转向与路口特征
- **AND** 示例 SHALL 引导使用「右转切上山脊」「左转下沟」「发卡弯」这类表述

#### Scenario: 无 AI 时不受影响

- **WHEN** 未开启 AI 命名
- **THEN** 航点名称 SHALL 与改动前完全一致
- **AND** 转向信息 SHALL 仅体现在摘要与描述中
