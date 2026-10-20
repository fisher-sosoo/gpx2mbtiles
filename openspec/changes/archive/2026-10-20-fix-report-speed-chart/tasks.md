# Tasks

## 1. 修正曲线溢出

- [x] 1.1 绘制前把坐标系裁剪到绘图区，并把取值范围收敛到分位区间，
      用同一张真实轨迹出图确认曲线不再越过底部刻度线
- [x] 1.2 在 `tests/test_player.py` 断言存在裁剪逻辑（`clip()` 调用与绘图区矩形），
      运行 `pytest tests/test_player.py -q` 通过

## 2. 改用 km/h

- [x] 2.1 区块标题由「配速」改为「速度」，纵轴刻度与右上角说明改为 km/h，
      越高越快（不再反向），出图核对刻度数值与曲线方向一致
- [x] 2.2 在 `tests/test_player.py` 断言 `drawSpeedChart` 与 `km/h` 文案存在，
      并同步更新 `README.md` 的区块说明，运行 `pytest tests/ -q` 通过

## Workflow follow-up

- 实现完成后用 `/openspec-archive-change` 归档，把 delta 合并回主 specs。
