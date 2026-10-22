# Spec Delta

## Purpose

让用户不必手动导出文件，直接把 Garmin Connect 上的徒步活动变成可按生理数据分段的竖版分析长图。

## ADDED Requirements

### Requirement: 活动列表

系统 SHALL 列出账号里最近一段时间内的活动，供用户选择分析对象。

#### Scenario: 默认时间窗

- **WHEN** 用户打开 Garmin 活动长图页
- **THEN** 系统 SHALL 列出最近 30 天内的活动
- **AND** 每项 SHALL 给出名称、日期、距离与耗时

#### Scenario: 时间窗内没有活动

- **WHEN** 指定时间窗内没有任何活动
- **THEN** 系统 SHALL 提示该时间窗内无活动
- **AND** SHALL 允许用户调整时间窗后重试

#### Scenario: 尚未授权

- **WHEN** 服务器上没有可用的 Garmin 授权
- **THEN** 系统 SHALL 提示需要先在服务器上完成一次授权
- **AND** SHALL NOT 以 HTTP 500 结束请求

### Requirement: 单条活动取数

系统 SHALL 按需拉取单条活动的原始数据，归一化成轨迹点序列，并在本地缓存结果。

#### Scenario: 首次拉取

- **WHEN** 用户选择一条尚未缓存的活动
- **THEN** 系统 SHALL 从 Garmin 拉取该活动的原始文件
- **AND** SHALL 解析出位置、海拔、时间与可用的生理字段
- **AND** SHALL 把原始文件与解析结果写入本地缓存

#### Scenario: 重复查看

- **WHEN** 用户再次选择已缓存的活动
- **THEN** 系统 SHALL 直接使用本地缓存
- **AND** SHALL NOT 再次请求 Garmin

#### Scenario: 上游失败

- **WHEN** Garmin 拒绝请求或网络不可达
- **THEN** 系统 SHALL 返回可读的错误说明
- **AND** 已缓存的活动 SHALL 仍可查看

### Requirement: 生理字段解析

系统 SHALL 从活动原始文件中解析心率、步频与温度，并让每个数值对应到正确的轨迹点与时刻。

#### Scenario: 字段可用

- **WHEN** 活动包含心率、步频或温度记录
- **THEN** 每个轨迹点 SHALL 携带其记录时刻的数值
- **AND** 全部时间 SHALL 使用同一时区基准

#### Scenario: 心率缺测值

- **WHEN** 某次心率记录为 0（胸带脱落）
- **THEN** 该点 SHALL 视为缺测
- **AND** SHALL NOT 计入任何心率统计

#### Scenario: 记录密度不一致

- **WHEN** 生理采样与位置采样不在同样的时刻
- **THEN** 系统 SHALL 按时间就近取值
- **AND** SHALL NOT 按数组下标硬对齐

### Requirement: 分段生理统计

系统 SHALL 按累计里程把行程分段，并给出每段的生理指标。

#### Scenario: 分段规则

- **WHEN** 生成分段
- **THEN** 系统 SHALL 沿用与本地 GPX 长图相同的自适应步长规则
- **AND** 段数 SHALL 不超过 10 段

#### Scenario: 两张表

- **WHEN** 渲染分段结果
- **THEN** 系统 SHALL 分别输出运动表与生理表
- **AND** 运动表 SHALL 含距离、用时、配速、爬升与下降
- **AND** 生理表 SHALL 含平均心率、最高心率、平均步频与平均温度
- **AND** 两张表 SHALL 使用相同的分段序号与边界

#### Scenario: 段内缺测

- **WHEN** 某一段没有任何心率记录
- **THEN** 该段心率列 SHALL 显示占位符
- **AND** SHALL NOT 显示 0

### Requirement: 长图版面

系统 SHALL 把结果渲染成竖版长图，版面自上而下与本地 GPX 长图保持同一叙事顺序。

#### Scenario: 版面顺序

- **WHEN** 生成长图
- **THEN** 自上而下 SHALL 依次为：轨迹图 → 总览 → 坡度构成 → 速度曲线 → 海拔剖面 → 运动表 → 生理表

#### Scenario: 生理总览

- **WHEN** 活动含心率或步频
- **THEN** 总览区 SHALL 增加平均心率、最高心率与平均步频
- **AND** 活动含温度时 SHALL 增加温度区间

#### Scenario: 温度表述

- **WHEN** 长图中出现温度
- **THEN** 标签 SHALL 说明其为设备记录温度
- **AND** SHALL NOT 表述为气温

#### Scenario: 全程无生理数据

- **WHEN** 活动完全没有心率、步频与温度
- **THEN** 系统 SHALL 隐藏生理表与生理总览
- **AND** 长图其余区块 SHALL 照常生成

### Requirement: 与本地 GPX 出图页共存

系统 SHALL 保持既有本地 GPX 出图页的行为不变，两个页面互不影响。

#### Scenario: 旧页不受影响

- **WHEN** 本能力上线
- **THEN** 本地 GPX 出图页 SHALL 保持原有的解析、版面与出图结果
- **AND** 其既有的静态断言测试 SHALL 继续通过

#### Scenario: 共享渲染代码

- **WHEN** 两个页面共用同一份纯函数实现
- **THEN** 共享副本与旧页内联副本 SHALL 保持一致
- **AND** 出现不一致时 SHALL 由测试报错

### Requirement: 授权与凭据

系统 SHALL 使用预先授权得到的 Garmin 令牌访问活动数据；默认不在服务器上保存账号密码。

#### Scenario: 一次性预授权

- **WHEN** 用户首次配置账号
- **THEN** 系统 SHALL 通过独立的命令行工具完成交互式登录
- **AND** 登录结果 SHALL 以令牌文件形式保存在服务器上

#### Scenario: 令牌失效

- **WHEN** 令牌过期或刷新失败
- **THEN** 系统 SHALL 提示重新执行预授权
- **AND** SHALL NOT 静默重试到超时

#### Scenario: 显式开启的自动续期

- **WHEN** 用户显式配置了账号凭据并开启自动重登
- **THEN** 系统 SHALL 在令牌失效时尝试用该凭据重新登录并覆盖令牌
- **AND** SHALL NOT 把密码写入磁盘或日志
- **AND** 自动重试之间 SHALL 有冷却间隔，避免把账号刷进风控

#### Scenario: 只读调用

- **WHEN** 系统访问 Garmin
- **THEN** SHALL 只调用读取活动与下载文件的接口
- **AND** SHALL NOT 修改账号内的任何数据

### Requirement: 访问控制与合规

系统 SHALL 把 Garmin 相关接口纳入既有的接口鉴权，并限制使用方式。

#### Scenario: 接口鉴权

- **WHEN** 服务端配置了接口密钥
- **THEN** Garmin 相关接口 SHALL 要求相同的密钥
- **AND** 未携带密钥的请求 SHALL 被拒绝

#### Scenario: 单条查看

- **WHEN** 用户使用本功能
- **THEN** 系统 SHALL 一次只拉取一条活动
- **AND** SHALL NOT 提供批量导出或对外服务
