# Tasks

## 1. 样例与解析基础

- [x] 1.1 把用户提供的 `2023-02-18 英德雪山嶂环线.kml` 存入 `samples/`，并在 `tests/conftest.py` 增加小体积的合成 KML fixture（gx:Track + startPoint/endPoint + 无名 realPoint 三型），验证 fixture 能被解析器读出预期点数
- [x] 1.2 实现 `app/kml_processor.py` 的元素树 → 中间结构解析（gx:Track 平行数组、LineString/MultiGeometry、Point、Folder 归属），验证 `test_unit.py` 中 gx:coord 与 when 长度不一致时保留坐标且时间留空
- [x] 1.3 实现 KMZ 解包与文本编码嗅探（UTF-8 → GB18030），验证 doc.kml 优先、无 .kml 时给出中文错误
- [x] 1.4 实现 XML 非法 / 非 KML / 无点位三类输入的拒绝分支，验证错误信息为可读中文且不产出文件

## 2. 命名规则

- [x] 2.1 实现航点四级命名来源（name → 备注 → 附件文件名 → 位置名称）与来源标记，验证每种来源都有单测命中对应等级
- [x] 2.2 实现沿轨迹定位：相邻点 Haversine 累计里程 + KDTree 最近点/插值定位，验证样本 30 个航点全部命中原顶点，里程从 0.38 km 单调增至 8.85 km，全程 11.23 km
- [x] 2.3 实现累计耗时：取 `航点时间 − 轨迹首点时间`，时间优先用 description 解析值、回退 ExtendedData 毫秒值；无时间与无轨迹两种退化路径各有用例，验证样本首点为 `1:28` 且耗时序列单调不减
- [x] 2.4 实现位置名称格式 `#NN <里程>km · <累计耗时>`（两位小数、h:mm），验证样本首个 realPoint 名称为 `#01 0.38km · 1:28`
- [x] 2.5 实现序号补零、重名去重后缀、起点/终点特殊名，验证 30 个 realPoint 的产物名称两两不同且序号与文件顺序一致
- [x] 2.6 实现轨迹命名（剥日期/占位词得地点、`地点 + 日期 + 运动类型` 拼接、用户指定名覆盖与分段序号），验证样本得到 `英德雪山嶂环线 2023-02-18 爬山`，且名称不以日期开头、不含 `轨迹片段`

## 3. GPX 输出与接口

- [x] 3.1 实现 `app/gpx_writer.py`：GPX 1.1 输出 lat/lon、ele、UTC time、name/cmt/desc、extensions，验证输出 XML 良构且字段齐全
- [x] 3.2 实现 `/api/convert`（multipart 文件或文本 + 可选 track_name），返回 `{gpx, filename, summary}`，摘要含轨迹名、航点数、按来源统计、跳过要素数，验证 `test_e2e.py` 全流程与 401/400 分支
- [x] 3.3 核对往返一致性：把样本 KML 转换后与用户提供的同名 GPX 对照点位数量/顺序/坐标/时间，验证不一致项为零（或差异在测试中显式白名单说明）
- [x] 3.4 在 `app/config.py` 增加转换相关环境变量（最大输入字节等），验证默认值生效且可被 monkeypatch 覆盖

## 4. 生成器页支持 KML

- [x] 4.1 抽出统一的「取点」入口供 GPX 与 KML/KMZ 共用，`parse_gpx` 行为保持不变，验证既有 `TestParseGpx` 全绿
- [x] 4.2 `/api/submit` 与 `/api/estimate` 接受 .kml/.kmz，验证同名测试用例覆盖上传 KML 能正常预估与完成
- [x] 4.3 更新生成器页文案与 `accept`，验证 `node --check` 通过且页面提示包含 KML

## 5. 命名转换页

- [x] 5.1 新建 `web/convert.html`：选择/拖拽文件、可选自定义轨迹名、提交后展示摘要（轨迹名、航点表含里程与累计耗时列）、下载按钮，验证 `node --check` 内联脚本语法通过
- [x] 5.2 在生成器页、回放页、门户页加入转换页入口，验证 `test_player.py` 的 `/gpx/` 前缀与链接规则测试通过
- [x] 5.3 页面测试：断言转换页存在关键要素（表单、下载、来源统计展示），验证 `test_frontend.py` 通过
- [x] 5.4 更新 `README.md` 与 `openspec/project.md` 的目录/能力表，验证文档中描述的接口与页面路径可实际访问

## 6. AI 辅助命名（可选）

- [x] 6.1 在 `app/config.py` 增加 `AI_API_KEY` / `AI_BASE_URL` / `AI_MODEL` / `AI_TIMEOUT_SECONDS`，支持从环境变量或未入库的 `apikey` 文件读取，验证未配置时 `ai_names` 自动降级且不报错
- [x] 6.2 实现 `app/ai_naming.py`：构造结构化提示词（序号/里程/耗时/海拔/升降）、调用 chat/completions、解析 JSON 数组，验证返回值能被单测桩替换且不依赖网络
- [x] 6.3 实现结果校验与回退：序号对不上/名称为空/超长/只有标点一律丢弃并回退规则命名，验证 30 条里人为混入坏数据时仍能产出 30 个互不重名的名称
- [x] 6.4 接入 `/api/convert` 的 `ai_names` 参数与摘要来源统计（新增 `ai` 来源与未生效原因），验证开启时来源为 ai、关闭时零外部请求
- [x] 6.5 保留人工名称优先：文件内已有 `<name>` 或备注的航点不被 AI 覆盖，验证单测覆盖混合情形
- [x] 6.6 转换页加「AI 推测命名（可选）」开关与「推测，仅供参考」提示，验证 `node --check` 通过且默认不勾选
- [x] 6.7 确保密钥不入库：`.gitignore` 含 `apikey`，验证 `git check-ignore` 命中且 `git status` 不出现该文件

## 7. 集成验证

- [x] 7.1 全量跑 `pytest`，验证单元/端到端/前端三类用例全绿
- [x] 7.2 用真实样本走一遍「KML → 转换页 → GPX → 生成器页预估」，验证页面链路可用且摘要数字与样本一致（33 个点位、轨迹名以地点开头、航点里程与耗时单调）

## Workflow follow-up

- 提案评审通过后进入 `/openspec-apply-change` 实现。
- 实现完成后 `/openspec-archive-change` 归档并把 delta 合并回主 specs。
