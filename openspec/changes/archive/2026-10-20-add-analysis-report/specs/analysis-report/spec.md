# Spec Delta

## Purpose

把一条 GPX 轨迹转成一张可直接分享的竖版分析长图：底图上按速度着色的轨迹、
总览数据、配速曲线、海拔剖面与 1km 分段表一次成图，全部在浏览器本地完成。

## ADDED Requirements

### Requirement: GPX 导入

系统 SHALL 允许用户导入 GPX 文件，并从中解析出轨迹点、海拔、时间与航点。

#### Scenario: 导入方式

- **WHEN** 用户拖入或选择一个 `.gpx` 文件
- **THEN** 系统 SHALL 解析该文件并显示轨迹名、里程与耗时
- **AND** SHALL 立即生成可预览的长图

#### Scenario: 多段与多条轨迹

- **WHEN** GPX 含多个 `trkseg`
- **THEN** 系统 SHALL 按文件内顺序把它们拼接成一条连续轨迹
- **AND** 当文件含多条 `trk` 时，SHALL 列出各条并允许选择分析对象，默认选里程最长的一条

#### Scenario: 解析失败

- **WHEN** 文件不是合法 GPX，或不含任何轨迹点
- **THEN** 系统 SHALL 提示具体原因
- **AND** SHALL NOT 生成残缺的长图

#### Scenario: 不支持的文件类型

- **WHEN** 用户选择非 GPX 文件
- **THEN** 系统 SHALL 提示本页只接受 GPX

### Requirement: 长图版面

系统 SHALL 把分析结果渲染成一张宽度固定、高度随内容变化的竖版长图。

#### Scenario: 版面顺序

- **WHEN** 长图生成
- **THEN** 自上而下 SHALL 依次为：轨迹图 → 总览数据 → 配速曲线 → 海拔剖面 → 1km 分段表
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
- **THEN** 图头 SHALL 显示轨迹名与日期
- **AND** SHALL NOT 出现第三方 App 的品牌、用户名或其它身份标识

### Requirement: 底图与速度着色

系统 SHALL 用 Windy 户外底图铺底，并按行进速度给轨迹着色。

#### Scenario: 底图来源

- **WHEN** 生成轨迹图
- **THEN** 瓦片 SHALL 经本站的 `/api/tile/windy` 代理获取
- **AND** 图上 SHALL 标明底图数据来源

#### Scenario: 速度色带

- **WHEN** 轨迹含可用时间戳
- **THEN** 轨迹 SHALL 按速度渐变着色
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

### Requirement: 总览数据

系统 SHALL 在长图中给出本次行程的关键指标。

#### Scenario: 基本指标

- **WHEN** 长图生成
- **THEN** SHALL 显示里程、耗时、均速、累计爬升与最高海拔

#### Scenario: 缺少海拔

- **WHEN** 轨迹不含海拔
- **THEN** 系统 SHALL 隐藏累计爬升与最高海拔
- **AND** 其余指标 SHALL 照常显示

#### Scenario: 缺少时间戳

- **WHEN** 轨迹不含时间戳
- **THEN** 系统 SHALL 隐藏耗时与均速
- **AND** SHALL 明确提示缺少时间信息

### Requirement: 配速与海拔曲线

系统 SHALL 用曲线呈现配速与海拔随行程的变化。

#### Scenario: 配速曲线

- **WHEN** 轨迹含时间戳
- **THEN** 系统 SHALL 绘制配速曲线，且纵轴满足「越快越高」
- **AND** SHALL 剔除 GPS 抖动造成的瞬时尖峰

#### Scenario: 海拔剖面

- **WHEN** 轨迹含海拔
- **THEN** 系统 SHALL 按里程绘制海拔剖面
- **AND** SHALL 标出最高点与最低点

#### Scenario: 数据不足

- **WHEN** 数据点过少，或全程数值没有变化
- **THEN** 系统 SHALL 不绘制该图表
- **AND** 版面 SHALL NOT 留下空白区块

### Requirement: 1km 分段表

系统 SHALL 按累计里程把轨迹切成 1km 的段，并列出每段数据。

#### Scenario: 分段规则

- **WHEN** 生成分段
- **THEN** 系统 SHALL 每 1000m 切一段，段边界按轨迹插值取点
- **AND** 末段不足 1km 时 SHALL 单独成行并标注实际距离

#### Scenario: 每段指标

- **WHEN** 列出某一段
- **THEN** SHALL 显示分段序号、距离、用时、配速、均速与爬升

#### Scenario: 快慢高亮

- **WHEN** 分段完成
- **THEN** 最快的段与最慢的段 SHALL 用不同底色标识

#### Scenario: 缺失列隐藏

- **WHEN** 轨迹不含心率或步频数据
- **THEN** 对应列 SHALL 整列不出现

### Requirement: 纯前端与合规

系统 SHALL 在浏览器内完成解析、计算与渲染，只让瓦片请求走本站代理。

#### Scenario: 不调用生成接口

- **WHEN** 使用分析长图页
- **THEN** 系统 SHALL NOT 调用任务提交、任务查询等生成类接口

#### Scenario: 瓦片例外

- **WHEN** 页面请求瓦片
- **THEN** 该请求 SHALL 仅用于取图
- **AND** SHALL NOT 触发任何服务端解析或计算

#### Scenario: 个人自用

- **WHEN** 使用本页出图
- **THEN** 系统 SHALL NOT 提供批量抓取或对外出图能力
