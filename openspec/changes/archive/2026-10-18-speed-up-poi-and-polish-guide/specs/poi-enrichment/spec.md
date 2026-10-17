# Spec Delta

## MODIFIED Requirements

### Requirement: 按区域查询地名

系统 SHALL 依据轨迹的包围盒向 OSM 查询有名字的地物。

#### Scenario: 查询范围

- **WHEN** 用户对某个项目发起补点
- **THEN** 系统 SHALL 用该轨迹的外接矩形（含少量外扩）作为查询范围
- **AND** SHALL 查询垭口、山隘、营地、山屋、避难所、山峰、湖泊、村镇
- **AND** SHALL 查询河流以判断过河点

#### Scenario: 分层查询

- **WHEN** 执行查询
- **THEN** 节点类地物 SHALL 用不带几何的查询（节点自带坐标）
- **AND** 河流几何 SHALL 单独查询，且该查询失败时 SHALL NOT 影响主结果
- **AND** 主查询 SHALL NOT 拉取面要素的完整几何，避免查询耗时成倍增长

#### Scenario: 代理自愈

- **WHEN** 查询失败需要重试
- **THEN** 系统 SHALL 在多个代理端口中轮换
- **AND** SHALL 在全部失败后返回可读错误并说明公共查询服务可能过载

#### Scenario: 公共设施礼貌

- **WHEN** 调用公共查询服务
- **THEN** 系统 SHALL 带可识别的 User-Agent
- **AND** SHALL 有超时与失败重试上限
- **AND** SHALL NOT 在短时间内重复查询同一区域

## ADDED Requirements

### Requirement: 功能入口常驻

系统 SHALL 让项目页各功能入口在项目存在时始终可见且可操作。

#### Scenario: 对话入口

- **WHEN** 项目存在但尚无地名点
- **THEN** 对话面板 SHALL 可见
- **AND** 输入框 SHALL 处于禁用态并提示先补充地名点
- **AND** SHALL NOT 隐藏整个面板

#### Scenario: 有地名点后

- **WHEN** 补点完成
- **THEN** 对话输入 SHALL 自动恢复可用

### Requirement: 指南可读性

系统 SHALL 把生成的指南渲染为可读内容而非 Markdown 源码。

#### Scenario: 渲染

- **WHEN** 指南生成完成
- **THEN** 页面 SHALL 以标题、表格、列表等等价形式展示
- **AND** 复制与下载 SHALL 仍输出 Markdown 原文

#### Scenario: 安全

- **WHEN** 渲染指南内容
- **THEN** 系统 SHALL 先做 HTML 转义再解析结构
- **AND** SHALL NOT 直接插入未转义内容

### Requirement: 分析针对本路线

指南中的 AI 分析 SHALL 只针对当次路线，不给通用建议。

#### Scenario: 禁止套话

- **WHEN** 生成分析
- **THEN** SHALL NOT 出现「导入手机」「保持离线可用」「提前下载轨迹」这类与具体路线无关的建议

#### Scenario: 装备按条件

- **WHEN** 分析提到装备
- **THEN** SHALL 只在天气或地形条件相关时提：降雪结冰提防滑、降雨提防水与备换、
  大风或低温提保暖防失温、需手脚并用的攀爬提手套
- **AND** SHALL NOT 罗列徒步鞋、登山杖、头灯这类默认装备

#### Scenario: 位置可定位

- **WHEN** 分析提到风险位置
- **THEN** SHALL 给出里程或节点名，便于在地图上定位

#### Scenario: 补充信息

- **WHEN** 用户填写了补充信息（到达时间、是否商团轻装等）
- **THEN** 系统 SHALL 把它作为上下文一并交给模型
- **AND** SHALL 在指南中保留该字段以便追溯

### Requirement: 航点自动显示

回放页 SHALL 在导入带路径点的 GPX 时自动显示这些点。

#### Scenario: 导入即显示

- **WHEN** 导入的 GPX 含 `<wpt>`
- **THEN** 系统 SHALL 自动把路径点渲染为标记
- **AND** SHALL 提示已自动标出的数量
- **AND** SHALL NOT 要求用户先点击某个按钮
