# 轨迹回放与分析

## Purpose

行程结束后，在 PC 端把多条轨迹叠加到地图上做分析、标注与出图，
用于撰写游记配图。该页面完全运行在浏览器内，不消耗服务端资源
（除 Windy 底图经服务端代理外）。

## Requirements

### Requirement: 多文件导入

系统 SHALL 支持一次导入多个轨迹文件。

#### Scenario: 支持的文件类型

- **WHEN** 用户导入 GPX、KML 或 KMZ
- **THEN** 系统 SHALL 解析其中的轨迹与路径点
- **AND** SHALL 对每个文件单独报告成功或失败原因

#### Scenario: KMZ 解压

- **WHEN** 导入 KMZ
- **THEN** 系统 SHALL 在浏览器内解压并取出其中的 KML
- **AND** 浏览器不支持解压时 SHALL 给出明确提示并建议改用 GPX 或 KML

#### Scenario: 一个文件含多条轨迹

- **WHEN** 文件中存在多条轨迹
- **THEN** 系统 SHALL 分别作为独立图层导入

#### Scenario: 导入失败不影响其它文件

- **WHEN** 某个文件解析失败
- **THEN** 系统 SHALL 保留其余文件的结果

### Requirement: 多轨迹叠加显示

系统 SHALL 在同一地图上叠加显示多条轨迹，并保证在各种底图上都清晰可辨。

#### Scenario: 轨迹绘制

- **WHEN** 轨迹可见
- **THEN** 系统 SHALL 以「浅色描边 + 主色实线」双层绘制

#### Scenario: 每条轨迹独立控制

- **WHEN** 用户操作某条轨迹
- **THEN** 系统 SHALL 允许独立设置：颜色、名称、线宽、不透明度、
  是否显示、是否显示名称标签
- **AND** SHALL 允许单独删除与定位到该轨迹

### Requirement: 名称标签

系统 SHALL 把轨迹与标记的名称直接绘制在地图上，而不是只在悬停时显示。

#### Scenario: 常驻显示名称

- **WHEN** 名称标签已开启
- **THEN** 系统 SHALL 在地图上常驻显示该名称
- **AND** SHALL NOT 使用半透明底色块遮挡地图内容
- **AND** SHALL 使用描边式文字阴影保证在浅色与深色底图上都可读

#### Scenario: 批量开关

- **WHEN** 用户触发批量操作
- **THEN** 系统 SHALL 一次切换全部轨迹或全部标记的名称显示

### Requirement: 标记与注释

系统 SHALL 允许在地图上添加带名称与注释的标记。

#### Scenario: 添加标记

- **WHEN** 用户在地图上选点或进入取坐标模式后点击
- **THEN** 系统 SHALL 创建标记并允许填写名称与多行注释
- **AND** 标记 SHALL 可拖动微调位置

#### Scenario: 标记随拖动更新

- **WHEN** 拖动标记
- **THEN** 其名称标签 SHALL 跟随移动

### Requirement: 行前辅助图层

系统 SHALL 提供徒步分析常用的辅助标注。

#### Scenario: 里程桩

- **WHEN** 用户选择间隔并触发
- **THEN** 系统 SHALL 沿轨迹按该距离打点

#### Scenario: 起终点与方向

- **WHEN** 用户触发
- **THEN** 系统 SHALL 标注每条轨迹的起点与终点
- **AND** SHALL 能沿轨迹绘制表示行进方向的箭头

#### Scenario: 统一清除

- **WHEN** 用户清除工具层
- **THEN** 系统 SHALL 移除全部由工具生成的标注
- **AND** SHALL NOT 影响用户手动添加的标记

### Requirement: 底图选择

系统 SHALL 提供多种底图并允许调节不透明度。

#### Scenario: 切换底图

- **WHEN** 用户选择底图
- **THEN** 系统 SHALL 立即加载该底图并填充当前视野
- **AND** SHALL 在底部显著标明数据来源

#### Scenario: 轨迹可读性

- **WHEN** 底图内容较复杂
- **THEN** 系统 SHALL 允许分别调节底图与轨迹的不透明度

### Requirement: 出图

系统 SHALL 把当前视图导出为 PNG，用于文章配图。

#### Scenario: 导出图片

- **WHEN** 用户触发导出
- **THEN** 系统 SHALL 生成包含底图、轨迹、标记、名称标签与图例的图片
- **AND** SHALL 支持多倍率以输出高清图
- **AND** SHALL NOT 把地图控件（缩放按钮等）画进图片

#### Scenario: 图例

- **WHEN** 图例开启
- **THEN** 系统 SHALL 列出各轨迹的颜色、里程与爬升
- **AND** 图例 SHALL 可拖动位置、可调整大小

### Requirement: 方案保存与迁移

系统 SHALL 自动保存当前方案，并支持导出导入以便跨设备使用。

#### Scenario: 自动保存

- **WHEN** 用户改动轨迹或标记
- **THEN** 系统 SHALL 存入浏览器本地存储
- **AND** 下次打开 SHALL 自动恢复

#### Scenario: 导出与导入方案

- **WHEN** 用户导出方案
- **THEN** 系统 SHALL 生成包含轨迹、样式、标记与视图设置的 JSON
- **AND** 导入该 JSON SHALL 还原全部内容

#### Scenario: 导出标注为 GPX

- **WHEN** 用户导出标记
- **THEN** 系统 SHALL 生成可导入离线导航 App 的 GPX

### Requirement: 纯前端运行

回放页 SHALL 在浏览器内完成解析、渲染与导出，不消耗服务端算力。

#### Scenario: 不调用生成接口

- **WHEN** 使用回放页
- **THEN** 系统 SHALL NOT 调用任务提交等生成类接口
- **AND** 解析、绘制、导出 SHALL 全部在本地完成

#### Scenario: 底图例外

- **WHEN** 使用经服务端代理的底图
- **THEN** 该部分请求 SHALL 仅用于取瓦片
- **AND** SHALL NOT 触发任何服务端解析或计算
