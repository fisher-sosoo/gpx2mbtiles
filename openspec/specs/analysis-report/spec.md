# analysis-report Specification

## Purpose
把一条 GPX 轨迹转成一张可直接分享的竖版分析长图：底图上按速度着色的轨迹、
总览数据、配速曲线、海拔剖面与 1km 分段表一次成图，全部在浏览器本地完成。

## Requirements

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
