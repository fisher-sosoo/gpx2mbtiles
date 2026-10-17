# Spec Delta

## MODIFIED Requirements

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
