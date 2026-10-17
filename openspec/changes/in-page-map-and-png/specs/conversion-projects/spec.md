# Spec Delta

## ADDED Requirements

### Requirement: 页面内地图

项目页 SHALL 直接展示轨迹地图，无需跳转到其它页面。

#### Scenario: 显示轨迹

- **WHEN** 用户完成转换或打开历史项目
- **THEN** 页面 SHALL 显示以 OpenTopoMap 为底图的地图
- **AND** SHALL 绘制完整轨迹并自动缩放到全部范围
- **AND** 底图来源 SHALL 在图上标明

#### Scenario: 加载失败降级

- **WHEN** 轨迹数据获取失败
- **THEN** 地图 SHALL NOT 阻断其它功能
- **AND** 其它区块 SHALL 正常可用

### Requirement: 风险点圈注

系统 SHALL 在地图上标出需要留意的转向位置。

#### Scenario: 圈出转向点

- **WHEN** 摘要中存在显著转向的航点
- **THEN** 地图 SHALL 在该位置绘制圆圈
- **AND** 圆圈大小 SHALL 随转角幅度增大
- **AND** SHALL 可单独开关显示

#### Scenario: 与文字对应

- **WHEN** 指南的文字提示提到某个转向位置
- **THEN** 该位置 SHALL 能在地图上找到对应的圈
- **AND** 两者 SHALL 使用同一份转向数据

#### Scenario: 地名点

- **WHEN** 项目已有地名点
- **THEN** 地图 SHALL 以另一种颜色标出
- **AND** SHALL 可单独开关显示

### Requirement: 本页出图

系统 SHALL 在当前页面导出带底图与标注的 PNG。

#### Scenario: 导出

- **WHEN** 用户点击导出
- **THEN** 系统 SHALL 在浏览器内合成图片：底图瓦片、轨迹、风险圈、地名点与标题
- **AND** SHALL 支持多倍率
- **AND** SHALL NOT 跳转到其它页面

#### Scenario: 图层尊重当前开关

- **WHEN** 用户关闭了风险圈或地名点
- **THEN** 导出的图片 SHALL 同样不包含它们

#### Scenario: 瓦片缺失

- **WHEN** 部分底图瓦片加载失败
- **THEN** 系统 SHALL 仍然出图，缺失处留底色，不得整体失败
