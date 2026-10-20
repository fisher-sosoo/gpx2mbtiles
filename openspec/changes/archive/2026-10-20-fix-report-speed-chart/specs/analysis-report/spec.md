# Spec Delta

## REMOVED Requirements

### Requirement: 配速与海拔曲线

**Reason**: 该区块改按速度（km/h）呈现，纵轴不再使用配速（min/km），
原先的「配速曲线」场景与新的单位约定冲突。

**Migration**: 改看新增的「速度与海拔曲线」；总览里的「平均配速」与
分段表的「配速」列保持不变，不受影响。

## ADDED Requirements

### Requirement: 速度与海拔曲线

系统 SHALL 用曲线呈现行进速度与海拔随行程的变化，速度以 km/h 表示。

#### Scenario: 速度曲线

- **WHEN** 轨迹含时间戳
- **THEN** 系统 SHALL 绘制速度曲线，纵轴单位为 km/h
- **AND** 纵轴 SHALL 越高表示速度越快
- **AND** SHALL 剔除 GPS 抖动造成的瞬时尖峰
- **AND** 曲线 SHALL NOT 超出绘图区、遮挡坐标刻度

#### Scenario: 海拔剖面

- **WHEN** 轨迹含海拔
- **THEN** 系统 SHALL 按里程绘制海拔剖面
- **AND** SHALL 标出最高点与最低点

#### Scenario: 数据不足

- **WHEN** 数据点过少，或全程数值没有变化
- **THEN** 系统 SHALL 不绘制该图表
- **AND** 版面 SHALL NOT 留下空白区块
