# Tasks

## 1. 速度着色细分与海拔染色

- [x] 1.1 速度色由 5 档跳变改为档间线性插值（细分 33 级），出图确认轨迹颜色连续过渡
- [x] 1.2 海拔折线按同一色带逐段上色、面积改中性底色，出图核对颜色随速度变化
- [x] 1.3 在 `tests/test_player.py` 用 node 断言 `speedColor`/`gradientColor` 的端点与插值
      （含停顿中性色、无数据返回空），运行 `pytest tests/test_player.py -q` 通过

## 2. 底图透明度

- [x] 2.1 底图瓦片以约 80% 不透明度绘制（去掉原来的白色提亮层），
      出图确认轨迹比之前更醒目
- [x] 2.2 在 `tests/test_player.py` 断言存在 `globalAlpha` 与 0.8 的底图透明度设置，
      运行 `pytest tests/test_player.py -q` 通过

## 3. 自适应分段（最多 10 段）

- [x] 3.1 新增步长选择函数：从 1km 起按整数倍递增，直到段数不超过 10；
      用 12.3km 与 100km 两条轨迹核对段数与表头文案
- [x] 3.2 分段与表头改用动态步长，末段不足步长仍单独成行并标注实际距离
- [x] 3.3 在 `tests/test_player.py` 断言步长选择边界（3420m→1km、12300m→2km、
      100000m→10km）与带步长的分段结果，运行 `pytest tests/test_player.py -q` 通过

## 4. 曲线两端留余量

- [x] 4.1 速度曲线取值域在分位基础上加余量，出图确认曲线不再贴顶或贴底
- [x] 4.2 在 `tests/test_player.py` 断言余量常量存在，运行 `pytest tests/ -q` 通过

## Workflow follow-up

- 实现完成后用 `/openspec-archive-change` 归档，把 delta 合并回主 specs。
