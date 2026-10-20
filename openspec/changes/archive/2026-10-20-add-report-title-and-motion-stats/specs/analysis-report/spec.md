# Spec Delta

## ADDED Requirements

### Requirement: 坡度构成

系统 SHALL 按坡度把行程里程分成爬升、平路与下降三部分，并给出各自比例。

#### Scenario: 分类规则

- **WHEN** 轨迹含海拔
- **THEN** 系统 SHALL 以约 100m 的滑动窗口计算坡度
- **AND** 坡度大于 +3% 的距离 SHALL 计入爬升，小于 -3% 的计入下降，其余计入平路

#### Scenario: 比例展示

- **WHEN** 显示坡度构成
- **THEN** SHALL 给出三部分的百分比与公里数
- **AND** SHALL 用一条分段色条表示三者的相对长度

#### Scenario: 无海拔时省略

- **WHEN** 轨迹不含海拔
- **THEN** 系统 SHALL 不显示该区块
- **AND** 版面 SHALL NOT 留下空白

## MODIFIED Requirements

### Requirement: 长图版面

系统 SHALL 把分析结果渲染成一张宽度固定、高度随内容变化的竖版长图。

#### Scenario: 版面顺序

- **WHEN** 长图生成
- **THEN** 自上而下 SHALL 依次为：轨迹图 → 总览数据 → 坡度构成 → 速度曲线 → 海拔剖面 → 分段表
- **AND** 图底 SHALL 标明底图来源与生成时间

#### Scenario: 轨迹图区块

- **WHEN** 渲染轨迹图
- **THEN** 系统 SHALL 自动框选整条轨迹并在四周留出边距
- **AND** 该区块的宽高比 SHALL 固定，不随轨迹形状变化

#### Scenario: 预览与下载

- **WHEN** 长图生成完成
- **THEN** 页面 SHALL 显示等比缩小的预览
- **AND** 用户下载时 SHALL 得到原始尺寸的 PNG

#### Scenario: 超出画布上限

- **WHEN** 目标画布尺寸超出浏览器允许的上限
- **THEN** 系统 SHALL 降低输出倍率并提示用户
- **AND** SHALL NOT 静默失败或输出空白图

#### Scenario: 图头信息

- **WHEN** 长图出图
- **THEN** 图头 SHALL 显示标题与「开始 → 结束」时间
- **AND** 标题 SHALL 优先使用用户填写的名称，未填写时回退到轨迹名
- **AND** SHALL NOT 显示轨迹点数
- **AND** SHALL NOT 出现第三方 App 的品牌、用户名或其它身份标识

#### Scenario: 自定义标题

- **WHEN** 用户在页面填写标题名称
- **THEN** 出图与下载文件名 SHALL 使用该名称
- **AND** 清空后 SHALL 回退到轨迹名

### Requirement: 总览数据

系统 SHALL 在长图中给出本次行程的关键指标。

#### Scenario: 基本指标

- **WHEN** 长图生成
- **THEN** SHALL 显示里程、总耗时、运动时间、静止时间、均速、
  累计爬升、累计下降与最高海拔

#### Scenario: 运动与静止时间

- **WHEN** 轨迹含时间戳
- **THEN** 系统 SHALL 按移动速度阈值把耗时拆成运动时间与静止时间
- **AND** 两者之和 SHALL 等于总耗时

#### Scenario: 缺少海拔

- **WHEN** 轨迹不含海拔
- **THEN** 系统 SHALL 隐藏累计爬升、累计下降与最高/最低海拔
- **AND** 其余指标 SHALL 照常显示

#### Scenario: 缺少时间戳

- **WHEN** 轨迹不含时间戳
- **THEN** 系统 SHALL 隐藏总耗时、运动时间、静止时间与均速
- **AND** SHALL 明确提示缺少时间信息
