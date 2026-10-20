# Spec Delta

## REMOVED Requirements

### Requirement: 1km 分段表

**Reason**: 固定 1km 在长距离路线上会排出几十行，长图被表格撑得很长；
改为按总里程自适应步长、最多 10 段。

**Migration**: 改看新增的「自适应分段表」；每段指标、快慢高亮与缺失列隐藏的
行为不变，只是段长不再固定 1km，表头会注明实际步长。

## ADDED Requirements

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
- **THEN** SHALL 显示分段序号、距离、用时、配速、均速与爬升

#### Scenario: 快慢高亮

- **WHEN** 分段完成
- **THEN** 最快的段与最慢的段 SHALL 用不同底色标识

#### Scenario: 缺失列隐藏

- **WHEN** 轨迹不含心率或步频数据
- **THEN** 对应列 SHALL 整列不出现

## MODIFIED Requirements

### Requirement: 底图与速度着色

系统 SHALL 用 Windy 户外底图（半透明）铺底，并按行进速度连续给轨迹着色。

#### Scenario: 底图来源

- **WHEN** 生成轨迹图
- **THEN** 瓦片 SHALL 经本站的 `/api/tile/windy` 代理获取
- **AND** 图上 SHALL 标明底图数据来源

#### Scenario: 底图透明度

- **WHEN** 绘制底图
- **THEN** 底图 SHALL 以约 80% 的不透明度叠在浅色底上
- **AND** 轨迹 SHALL 保持完全不透明，保证在底图上清晰可辨

#### Scenario: 速度色带

- **WHEN** 轨迹含可用时间戳
- **THEN** 轨迹 SHALL 按速度连续渐变着色，档位之间平滑过渡而非逐段跳变
- **AND** SHALL 给出「慢 ↔ 快」两端的数值图例

#### Scenario: 停顿处理

- **WHEN** 某一段的速度接近零（久停或停车）
- **THEN** 该段 SHALL 用中性色绘制
- **AND** SHALL NOT 因此把整条色带的范围压偏

#### Scenario: 瓦片加载失败

- **WHEN** 部分或全部瓦片加载失败
- **THEN** 缺失处 SHALL 留底色
- **AND** 轨迹、统计与分段 SHALL 照常出图

#### Scenario: 请求量受控

- **WHEN** 为出图获取瓦片
- **THEN** 系统 SHALL 只取当前区域、固定缩放级别的瓦片
- **AND** 单次请求的瓦片数量 SHALL 受上限约束

### Requirement: 速度与海拔曲线

系统 SHALL 用曲线呈现行进速度与海拔随行程的变化，速度以 km/h 表示。

#### Scenario: 速度曲线

- **WHEN** 轨迹含时间戳
- **THEN** 系统 SHALL 绘制速度曲线，纵轴单位为 km/h
- **AND** 纵轴 SHALL 越高表示速度越快
- **AND** SHALL 剔除 GPS 抖动造成的瞬时尖峰
- **AND** 取值域 SHALL 在上下两端留出余量，曲线不得贴着边界或穿出绘图区

#### Scenario: 海拔剖面

- **WHEN** 轨迹含海拔
- **THEN** 系统 SHALL 按里程绘制海拔剖面
- **AND** SHALL 标出最高点与最低点

#### Scenario: 海拔按速度着色

- **WHEN** 轨迹含可用时间戳
- **THEN** 海拔折线 SHALL 按同一套速度色带逐段上色
- **AND** 面积填充 SHALL 使用中性底色，不与折线抢视觉

#### Scenario: 数据不足

- **WHEN** 数据点过少，或全程数值没有变化
- **THEN** 系统 SHALL 不绘制该图表
- **AND** 版面 SHALL NOT 留下空白区块
