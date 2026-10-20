# Proposal

## Why

分段表里只有「爬升」一列，下坡多的段（这条线第 6 段几乎全下坡）在表里
反而显示为 1 米的爬升，看不出实际升降。另外坡度构成的 ±3% 阈值偏严，
平路只统计到 6%，和肉眼感受不一致。

## What Changes

- 分段表把「爬升」列改为 **爬升 / 下降** 两行：`↑xxx` 用红色、`↓xxx` 用绿色，
  每行分别按段内正/负海拔差累计。
- 坡度构成的判定阈值由 ±3% 放宽到 **±5%**。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `analysis-report`：
  - 「自适应分段表」（每段指标增加下降，红/绿两行显示）
  - 「坡度构成」（分类阈值 ±3% → ±5%）

## Impact

- 修改：`web/report.html`、`tests/test_player.py`、`README.md`
- 不改：后端接口、瓦片代理、部署配置、版面其它区块
