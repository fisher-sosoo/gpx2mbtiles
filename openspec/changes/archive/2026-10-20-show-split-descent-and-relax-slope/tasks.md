# Tasks

## 1. 分段表升降两行

- [x] 1.1 分段时同时累计正负海拔差（爬升与下降），末段同样计入，
      用真实轨迹核对升降之和与总览数字一致
- [x] 1.2 表格「爬升」列改为「爬升 / 下降」两行：↑红、↓绿，出图核对颜色与数值
- [x] 1.3 在 `tests/test_player.py` 用 node 断言下降累计（下坡段 loss > 0、平段为 0），
      运行 `pytest tests/test_player.py -q` 通过

## 2. 坡度阈值 ±5%

- [x] 2.1 坡度分类阈值由 ±3% 调整为 ±5%，出图核对平路占比是否更符合直观
- [x] 2.2 在 `tests/test_player.py` 断言 ±5% 边界（4.9% 记平路、5.1% 记爬升），
      运行 `pytest tests/ -q` 通过

## Workflow follow-up

- 实现完成后用 `/openspec-archive-change` 归档，把 delta 合并回主 specs。
