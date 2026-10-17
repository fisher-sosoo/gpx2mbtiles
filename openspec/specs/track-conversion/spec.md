# track-conversion Specification

## Purpose
把两步路、Google Earth 等来源导出的 KML / KMZ 转换成标准 GPX，
并在转换过程中依据文件内的元数据重新组织轨迹名与航点名，
使只支持 GPX 的 App 导入后依然能看出「这是哪条轨迹、这些点是什么」。

## Requirements

### Requirement: KML 与 KMZ 输入

转换服务 SHALL 接受 KML 文本、KML 文件与 KMZ 压缩包，并从其中取出全部轨迹与点要素。

#### Scenario: 解析 gx:Track 轨迹

- **WHEN** KML 中存在 `gx:Track`
- **THEN** 系统 SHALL 按下标合并平行的 `<gx:coord>` 与 `<when>` 数组得到带时间的轨迹点
- **AND** 时长不足数组中较短者时 SHALL 保留坐标并令缺失的时间为空
- **AND** SHALL NOT 因子数组长度不一致而丢弃整条轨迹

#### Scenario: 解析 LineString 轨迹

- **WHEN** KML 中存在 `<LineString>` 或 `<MultiGeometry>` 内的折线
- **THEN** 系统 SHALL 按 `<coordinates>` 中的 lon,lat[,alt] 顺序取出轨迹点
- **AND** 单条折线少于 2 个有效点时不 SHALL NOT 输出为轨迹

#### Scenario: 解析点要素

- **WHEN** KML 中的 `<Placemark>` 含 `<Point>`
- **THEN** 系统 SHALL 输出为航点，并保留其海拔与（若有）时间

#### Scenario: KMZ 解包

- **WHEN** 上传的是 KMZ
- **THEN** 系统 SHALL 取出其中 `doc.kml`，没有时取第一个 .kml
- **AND** 找不到 .kml 时 SHALL 返回可读的中文错误说明

#### Scenario: 无法识别的输入

- **WHEN** 输入既不是合法 XML、也不是 KML，或不含任何轨迹点与航点
- **THEN** 系统 SHALL 拒绝并返回可读的中文错误说明
- **AND** SHALL NOT 生成任何文件

### Requirement: 标准 GPX 输出

系统 SHALL 输出可被主流 GPX 读取器直接导入的 GPX 1.1 文档。

#### Scenario: 结构与字段

- **WHEN** 转换成功
- **THEN** 根元素 SHALL 为 `<gpx version="1.1">`，并声明默认命名空间
- **AND** 轨迹 SHALL 写在 `<trk><trkseg><trkpt>` 中，航点写在 `<wpt>` 中
- **AND** 每个点 SHALL 带 `lat`/`lon` 属性，有海拔时输出 `<ele>`，有时间时输出 RFC 3339 的 UTC `<time>`
- **AND** 文档 SHALL 通过 XML 良构性校验

#### Scenario: 保留原始扩展信息

- **WHEN** 源文件带有轨迹级或点级的自定义字段（如运动类型、里程、爬升、附件 id）
- **THEN** 系统 SHALL 把它们写入 `<extensions>` 或 `<desc>`
- **AND** SHALL NOT 因字段无法识别而使转换失败

#### Scenario: 不与自产 GPX 冲突

- **WHEN** 输入的 KML 本身就是由 GPX 转成的 KML
- **THEN** 输出的点位与扩展字段 SHALL 与原始 GPX 一致（数量、顺序、坐标、时间）

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

### Requirement: 航点命名

系统 SHALL 为每个输出的航点生成名称，并保证同一文件内航点名称互不重复。

#### Scenario: 命名来源优先级

- **WHEN** KML 的航点带有可读名称
- **THEN** 系统 SHALL 依次尝试：`<name>` → 用户备注 → 附件文件名 → 位置名称
- **AND** 取到第一个非空结果后停止，不使用后续来源

#### Scenario: 备注优先且不再拼接

- **WHEN** 航点带有用户备注
- **THEN** 名称 SHALL 由「序号 + 备注原文」组成（如 `#07 左转进小路`）
- **AND** SHALL NOT 在备注之外再拼里程、累计耗时或海拔
- **AND** 备注里的机器生成内容（附件 JSON、纯数字 id）SHALL NOT 被当作备注

#### Scenario: 备注进入描述与注释

- **WHEN** 航点被重命名
- **THEN** 系统 SHALL 把备注原文写入 `<desc>` 与 `<cmt>`
- **AND** `<desc>` SHALL 同时保留已走里程、累计耗时与海拔
- **AND** 只展示名称或描述的 App 都能看到这条备注

#### Scenario: 位置名称

- **WHEN** 航点在轨迹上有可对应的时间或位置
- **THEN** 系统 SHALL 用「沿轨迹已走的累计里程」与「距离起点的累计耗时」生成该航点的位置名称
- **AND** 无可用时间时 SHALL 退化为「累计里程 + 海拔」

#### Scenario: 名称带序号

- **WHEN** 一个文件里有多个可命名航点
- **THEN** 名称 SHALL 以「序号 + 分隔符」开头，序号按航点在文件中出现的先后从 1 递增
- **AND** 序号补零对齐（至少两位）

#### Scenario: 重名去重

- **WHEN** 两个航点算出的名称完全相同
- **THEN** 后出现的 SHALL 自动追加区分后缀，不得与已用名称重复

#### Scenario: 起终点

- **WHEN** 源文件带有起终点标记
- **THEN** 系统 SHALL 分别命名为「起点」「终点」，且不占用普通航点的序号

#### Scenario: 原始名称保留

- **WHEN** 航点被重命名
- **THEN** 系统 SHALL 把原始名称与原始备注保留在 `<cmt>` 或 `<desc>` 中，便于追溯

### Requirement: AI 辅助命名

系统 SHALL 允许借助大语言模型，根据轨迹的地形与节奏为航点起语义名称，且 AI 不可用时不影响转换。

#### Scenario: 显式开启

- **WHEN** 请求中开启了 AI 命名
- **THEN** 系统 SHALL 把该轨迹的航点序列（序号、累计里程、累计耗时、海拔、两点间升降）交给模型
- **AND** SHALL 依据模型的返回为航点命名
- **AND** 未开启时 SHALL NOT 发起任何外部请求

#### Scenario: 未配置密钥

- **WHEN** 未配置模型 API Key 而请求开启 AI 命名
- **THEN** 系统 SHALL 忽略该选项并照常完成转换
- **AND** SHALL 在摘要中说明 AI 命名未生效的原因

#### Scenario: 调用失败或超时

- **WHEN** 模型请求超时、被限流或返回不可解析的内容
- **THEN** 系统 SHALL 回退到既有的四级命名规则
- **AND** 转换 SHALL 仍然成功，不得因 AI 失败而整体报错

#### Scenario: 结果校验

- **WHEN** 模型返回的条目数量与航点不一致，或缺少序号
- **THEN** 系统 SHALL 只用序号能对上的条目，其余航点走回退规则
- **AND** SHALL 丢弃明显不合法的名称（空串、只有标点、超长）
- **AND** 最终名称仍 SHALL 带序号且两两不同

#### Scenario: 人工名称优先

- **WHEN** 某航点在文件里有可读名称或用户备注
- **THEN** 系统 SHALL 保留该名称，AI 结果只用于没有名称的航点

#### Scenario: 来源可追溯

- **WHEN** 使用了 AI 命名
- **THEN** 摘要 SHALL 把这类航点的来源标为 AI
- **AND** 页面 SHALL 明确告知用户该名称由模型推测生成，可能与实际地物不符

#### Scenario: 密钥安全

- **WHEN** 配置文件包含模型密钥
- **THEN** 密钥 SHALL 只通过环境变量或本机未入库文件读取
- **AND** SHALL NOT 出现在任何响应、日志或提交内容中

### Requirement: 轨迹命名

系统 SHALL 为每条输出轨迹生成不含默认占位词的名称，并允许用户指定名称覆盖。

#### Scenario: 默认命名规则

- **WHEN** 用户未指定轨迹名
- **THEN** 轨迹名 SHALL 由「地点」「日期」「运动类型」按该顺序拼接，缺失的部分自动省略
- **AND** 名称 SHALL 以地点开头，日期 SHALL NOT 出现在名称的最前面
- **AND** SHALL NOT 使用 `轨迹片段N`、`Track`、`Untitled` 这类占位名作为最终名称

#### Scenario: 地点来源

- **WHEN** 源文件或轨迹名中已含可识别的地名
- **THEN** 系统 SHALL 直接复用该地名，不再从坐标推断

#### Scenario: 用户指定名称

- **WHEN** 用户填写了自定义轨迹名
- **THEN** 所有输出轨迹 SHALL 以该名称为前缀
- **AND** 多段轨迹时 SHALL 追加分段序号以保证彼此可区分

#### Scenario: 无法确定地名

- **WHEN** 既没有可复用的地名，也无法推断
- **THEN** 系统 SHALL 退化为「开始日期 + 运动类型」组合成名称，不得输出空名称

### Requirement: 转换摘要

系统 SHALL 在转换结果中返回摘要，供用户核对命名是否符合预期。

#### Scenario: 返回内容

- **WHEN** 转换成功
- **THEN** 摘要 SHALL 包含：轨迹数及各轨迹的最终名称、航点数、按来源统计的命名数量、点位总数
- **AND** 摘要 SHALL 为结构化数据，可直接用于页面展示

#### Scenario: 可下载

- **WHEN** 用户在页面上确认结果
- **THEN** 页面 SHALL 能下载到与摘要一致的 GPX 文件
- **AND** 文件名 SHALL 由轨迹名派生，且过滤掉路径分隔符等非法字符

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
