# Spec Delta

## MODIFIED Requirements

### Requirement: 转向识别

系统 SHALL 依据轨迹几何计算每个位置的转向角度，用于命名与行前分析。

#### Scenario: 转角计算

- **WHEN** 需要某位置的转向
- **THEN** 系统 SHALL 取该位置前后各一段固定距离的航向，用「离开航向 − 进入航向」得到转角
- **AND** 转角 SHALL 归一化到 -180°~180°，负值表示左转、正值表示右转
- **AND** 前后距离不足或两点重合时 SHALL 视为无有效转向

#### Scenario: 长基线净方向

- **WHEN** 计算转向
- **THEN** 系统 SHALL 使用**长基线**（前后各约 120 米）而非短基线
- **AND** SHALL NOT 因局部绕行（绕石头、避树根）产生转向标记

#### Scenario: 噪声抑制

- **WHEN** 轨迹存在 GPS 抖动
- **THEN** 航向 SHALL 基于两点间的弦（跨越若干点）计算，不得直接用相邻两点
- **AND** 转角绝对值小于阈值时 SHALL 视为「直行」而非一次转向

#### Scenario: 显著性筛选

- **WHEN** 生成航点命名与行前分析用的转向
- **THEN** 系统 SHALL 只保留幅度达到显著阈值（约 60°）的转向
- **AND** SHALL 把短距离内同方向的多次转向合并为一次，只保留幅度最大者
- **AND** SHALL 丢弃短距离内方向相反且幅度相近的成对转向（表示在找路而非路线决策）
- **AND** 未通过筛选的位置 SHALL 不携带转向描述

#### Scenario: 发卡弯标记

- **WHEN** 转角绝对值超过发卡弯阈值
- **THEN** 系统 SHALL 标记为发卡弯
- **AND** 该标记 SHALL 在提供给模型的上下文中单独体现

#### Scenario: 摘要暴露

- **WHEN** 转换完成
- **THEN** 摘要中每个航点 SHALL 包含其转向信息（方向与度数，或「直行」）
- **AND** 页面 SHALL 能展示该字段

## ADDED Requirements

### Requirement: 功能区块可达

系统 SHALL 保证转换页各功能区块的入口在项目存在时始终可被点击。

#### Scenario: 项目存在时入口可见

- **WHEN** 用户完成一次转换或打开一个历史项目
- **THEN** 地名补点、行前指南、对话修正的**入口控件** SHALL 可见
- **AND** 仅其「结果区域」按数据有无决定是否显示

#### Scenario: 无项目时隐藏

- **WHEN** 尚未转换或当前项目被删除
- **THEN** 这些区块 SHALL 隐藏

#### Scenario: 禁止入口自锁

- **WHEN** 实现区块显隐
- **THEN** 触发按钮 SHALL NOT 被放在自身控制显隐的容器内
- **AND** 该约束 SHALL 有静态回归测试守护
