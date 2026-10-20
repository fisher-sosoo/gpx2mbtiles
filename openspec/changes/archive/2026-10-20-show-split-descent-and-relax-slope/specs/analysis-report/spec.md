# Spec Delta

## MODIFIED Requirements

### Requirement: 坡度构成

系统 SHALL 按坡度把行程里程分成爬升、平路与下降三部分，并给出各自比例。

#### Scenario: 分类规则

- **WHEN** 轨迹含海拔
- **THEN** 系统 SHALL 以约 100m 的滑动窗口计算坡度
- **AND** 坡度大于 +5% 的距离 SHALL 计入爬升，小于 -5% 的计入下降，其余计入平路

#### Scenario: 比例展示

- **WHEN** 显示坡度构成
- **THEN** SHALL 给出三部分的百分比与公里数
- **AND** SHALL 用一条分段色条表示三者的相对长度

#### Scenario: 无海拔时省略

- **WHEN** 轨迹不含海拔
- **THEN** 系统 SHALL 不显示该区块
- **AND** 版面 SHALL NOT 留下空白

### Requirement: 自适应分段表

系统 SHALL 按累计里程分段，并根据总距离调整步长，使分段不超过 10 段。

#### Scenario: 分段步长

- **WHEN** 生成分段
- **THEN** 系统 SHALL 从 1 公里起按整数倍递增步长，直到总段数不超过 10
- **AND** 段边界 SHALL 按轨迹插值取点
- **AND** 表头 SHALL 注明本图使用的每段长度

#### Scenario: 末段不足一步长

- **WHEN** 末段距离不足所选步长
- **THEN** 该段 SHALL 单独成行并标注实际距离

#### Scenario: 每段指标

- **WHEN** 列出某一段
- **THEN** SHALL 显示分段序号、距离、用时、配速与均速
- **AND** SHALL 分别给出该段的爬升与下降
- **AND** 爬升以「↑」开头用红色，下降以「↓」开头用绿色

#### Scenario: 快慢高亮

- **WHEN** 分段完成
- **THEN** 最快的段与最慢的段 SHALL 用不同底色标识

#### Scenario: 缺失列隐藏

- **WHEN** 轨迹不含心率或步频数据
- **THEN** 对应列 SHALL 整列不出现
