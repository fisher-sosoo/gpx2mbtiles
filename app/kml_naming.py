"""命名规则：把解析出来的原始要素整理成「App 里看得懂」的名称。

两条主线：

* 轨迹名 —— 地点在最前，日期在后，运动类型收尾（D4）。
* 航点名 —— name → 备注 → 附件文件名 → 位置名称（已走里程 + 累计耗时）（D3）。

全部是纯函数 / 纯计算，不碰 IO，便于单测。
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime

from .kml_processor import KmlPoint, KmlResult, KmlTrack

EARTH_RADIUS = 6371008.8

# 轨迹名里的占位词：两步路/Google Earth 的默认名，不宜进入最终名称
PLACEHOLDER_RE = re.compile(r"^(轨迹片段|轨迹|路线片段|Track|Path|Untitled|KML)\s*#?\d*$", re.I)
DATE_PREFIX_RE = re.compile(r"^(\d{4})[-_./年]?(\d{1,2})[-_./月]?(\d{1,2})日?[\s_]+")
DATE_TOKEN_RE = re.compile(r"(?<!\d)(\d{4})[-_./](\d{1,2})[-_./](\d{1,2})(?!\d)")


@dataclass
class WaypointName:
    text: str
    source: str          # name / note / attach / position / ai / time
    km: float | None = None
    elapsed_s: float | None = None
    note: str = ""       # 用户备注原文（有则写进 desc 与 cmt）
    orig_name: str = ""  # 源文件里的 <name>，用于追溯
    turn: float | None = None   # 该处的转角（负左正右）
    turn_text: str = ""         # 可读转向描述
    turn_kind: str = ""         # junction=路口转向 / terrain=地形转向
    junction_ways: int = 0      # 该路口交汇的道路条数


@dataclass
class ConvertedWaypoint:
    point: KmlPoint
    waypoint_name: WaypointName
    order: int = 0


@dataclass
class TrackStats:
    distance_m: float = 0.0
    cum: list = field(default_factory=list)      # 每个点的累计里程（米）


# ---------------------------------------------------------------- 几何

def haversine_m(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    """两点间球面距离（米）。"""
    d_lat = math.radians(b_lat - a_lat)
    d_lon = math.radians(b_lon - a_lon)
    h = (math.sin(d_lat / 2) ** 2
         + math.cos(math.radians(a_lat)) * math.cos(math.radians(b_lat))
         * math.sin(d_lon / 2) ** 2)
    return 2 * EARTH_RADIUS * math.asin(min(1.0, math.sqrt(h)))


# 转向阈值：50° 以下在山路上太常见（绕树、避石），标出来全是噪音
TURN_MIN_DEG = 50.0
# 120° 以上基本只有发卡弯与折返
HAIRPIN_DEG = 120.0

# 转向基线：用「前后各 120m 的净方向变化」而不是 ±50m。
# 实测 ±50m 会把密林里绕石头、走错再折回都算成转向，整段上坡刷出一堆假标记。
TURN_SPAN_M = 120.0
# 只有达到这个幅度才算「需要提示的转向」；更小的视为地形绕行
TURN_SIGNIFICANT_DEG = 60.0
# 左右反复的判定窗口与合并距离：短距离内一左一右基本等于「在找路」而非决策点
TURN_OSC_WINDOW_KM = 0.45
TURN_MERGE_KM = 0.30


def bearing_deg(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    """从 a 指向 b 的方位角：0=正北，顺时针增大。"""
    d_lon = math.radians(b_lon - a_lon)
    lat1, lat2 = math.radians(a_lat), math.radians(b_lat)
    y = math.sin(d_lon) * math.cos(lat2)
    x = (math.cos(lat1) * math.sin(lat2)
         - math.sin(lat1) * math.cos(lat2) * math.cos(d_lon))
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def normalize_turn(deg: float) -> float:
    """把角度归一到 (-180, 180]：负=左转，正=右转。"""
    while deg > 180.0:
        deg -= 360.0
    while deg <= -180.0:
        deg += 360.0
    return deg


def _index_at_distance(cum, distance: float) -> int:
    """二分找第一个累计里程 >= distance 的点下标。"""
    lo, hi = 0, len(cum) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if cum[mid] < distance:
            lo = mid + 1
        else:
            hi = mid
    return lo


def turn_at(points, stats: TrackStats, index: int,
            span_m: float = 50.0) -> float | None:
    """位置 index 处的转角 = 离开航向 − 进入航向。

    用跨 span_m 米的弦算航向，而不是相邻两点 —— GPS 抖动下相邻点航向是噪声。
    距离不足、点重合或越界时返回 None（视为无有效转向）。
    """
    if not points or index < 0 or index >= len(points):
        return None
    cum = stats.cum
    total = stats.distance_m
    if total <= 0 or len(cum) != len(points):
        return None

    d = cum[index]
    i_in = _index_at_distance(cum, max(0.0, d - span_m))
    i_out = _index_at_distance(cum, min(total, d + span_m))
    if i_in >= index or i_out <= index:
        return None

    a, b, c = points[i_in], points[index], points[i_out]
    if haversine_m(a.lat, a.lon, b.lat, b.lon) < 1.0:
        return None
    if haversine_m(b.lat, b.lon, c.lat, c.lon) < 1.0:
        return None

    heading_in = bearing_deg(a.lat, a.lon, b.lat, b.lon)
    heading_out = bearing_deg(b.lat, b.lon, c.lat, c.lon)
    return normalize_turn(heading_out - heading_in)


def describe_turn(turn: float | None) -> str:
    """转角 → 可读文本（摘要与提示词共用，保证两处说法一致）。"""
    if turn is None:
        return ""
    if abs(turn) < TURN_MIN_DEG:
        return "直行"
    side = "右" if turn > 0 else "左"
    if abs(turn) >= HAIRPIN_DEG:
        return f"发卡弯{side}{abs(turn):.0f}°"
    return f"{side}转{abs(turn):.0f}°"


def pick_significant_turns(names) -> set:
    """从整条航点序列里挑出「显著转向」的下标集合。

    逐点判断没有全局观：密林里绕石头是左右横穿，走错路又折回是 180° 往返，
    这些都不是路线决策点。三步筛选：

    1. 幅度门槛：|转角| 不足 60° 的不算。
    2. 邻近同向合并：300m 内同方向的只留最强的一次。
    3. 左右反复抑制：450m 内出现反向且幅度相近的，两个都丢掉
       —— 一左一右等于净方向没变，那是找路，不是拐弯。
    """
    cands = []
    for i, n in enumerate(names):
        if n.turn is None or n.km is None:
            continue
        if abs(n.turn) < TURN_SIGNIFICANT_DEG:
            continue
        cands.append([i, n.km, n.turn])

    # 2) 邻近同向合并
    merged = []
    for c in sorted(cands, key=lambda x: x[1]):
        last = merged[-1] if merged else None
        if (last and c[1] - last[1] <= TURN_MERGE_KM
                and (c[2] > 0) == (last[2] > 0)):
            if abs(c[2]) > abs(last[2]):
                merged[-1] = c
            continue
        merged.append(c)

    # 3) 左右反复抑制
    keep = []
    for i, (idx, km, turn) in enumerate(merged):
        noisy = False
        for j, (_, km2, turn2) in enumerate(merged):
            if i == j:
                continue
            if (abs(km2 - km) <= TURN_OSC_WINDOW_KM
                    and (turn > 0) != (turn2 > 0)
                    and abs(turn2) >= abs(turn) * 0.5):
                noisy = True
                break
        if not noisy:
            keep.append(idx)
    return set(keep)


def track_stats(points) -> TrackStats:
    """按相邻点累加里程。"""
    cum = [0.0]
    for i in range(1, len(points)):
        prev, cur = points[i - 1], points[i]
        cum.append(cum[-1] + haversine_m(prev.lat, prev.lon, cur.lat, cur.lon))
    return TrackStats(distance_m=cum[-1] if cum else 0.0, cum=cum)


class _TrackIndex:
    """轨迹定位索引。

    用 1 度网格分桶做最近点查询：轨迹上千点时，逐点全量比较是 O(n·m)，
    航点多的时候会明显变慢；分桶后每点只需看附近几个桶。
    """

    def __init__(self, points, stats: TrackStats):
        self.points = points
        self.stats = stats
        self._cells: dict = {}
        for idx, p in enumerate(points):
            key = (int(math.floor(p.lat)), int(math.floor(p.lon)))
            self._cells.setdefault(key, []).append(idx)
        lats = [p.lat for p in points]
        lons = [p.lon for p in points]
        self._min_lat = min(lats) if lats else 0.0
        self._max_lat = max(lats) if lats else 0.0
        self._min_lon = min(lons) if lons else 0.0
        self._max_lon = max(lons) if lons else 0.0

    def nearest(self, lat: float, lon: float) -> int:
        """返回最近的轨迹点下标；搜索半径逐圈扩大直到有候选。"""
        if not self.points:
            return -1
        best, best_d = -1, float("inf")
        span = max(
            self._max_lat - self._min_lat,
            self._max_lon - self._min_lon,
            0.001,
        )
        radius = 1
        while radius <= int(math.ceil(span)) + 2:
            ilat, ilon = int(math.floor(lat)), int(math.floor(lon))
            for di in range(-radius, radius + 1):
                for dj in range(-radius, radius + 1):
                    for idx in self._cells.get((ilat + di, ilon + dj), ()):
                        p = self.points[idx]
                        d = haversine_m(lat, lon, p.lat, p.lon)
                        if d < best_d:
                            best, best_d = idx, d
            if best >= 0 and radius >= 2:
                return best
            radius += 1
        if best >= 0:
            return best
        # 兜底：全量比较（极少数越界情形）
        for idx, p in enumerate(self.points):
            d = haversine_m(lat, lon, p.lat, p.lon)
            if d < best_d:
                best, best_d = idx, d
        return best


# 等距圆柱投影尺度：在该纬度上 1 度经度 = cos(lat) 度纬度。
# 只用于「在两点之间插值比例」，精确经纬距离另由 haversine_m 计算。
_EPS = 1e-12


def _project_on_segment(a_lat, a_lon, b_lat, b_lon, lat, lon) -> float:
    """点在线段 ab 上的投影比例 t（0..1，已截断）。"""
    k = math.cos(math.radians((a_lat + b_lat) / 2.0))
    ax, ay = a_lon * k, a_lat
    bx, by = b_lon * k, b_lat
    px, py = lon * k, lat
    dx, dy = bx - ax, by - ay
    denom = dx * dx + dy * dy
    if denom <= _EPS:
        return 0.0
    t = ((px - ax) * dx + (py - ay) * dy) / denom
    return max(0.0, min(1.0, t))


def along_distance_m(points, stats: TrackStats, point) -> float:
    """航点沿轨迹从起点算起的累计里程（米）。

    落在顶点上直接取该顶点累计值；落在两顶点之间时按投影比例插值；
    偏离轨迹较远（比如不在轨迹上的标注点）时仍取最近位置的里程。
    """
    if not points:
        return 0.0
    index = _TrackIndex(points, stats)
    idx = index.nearest(point.lat, point.lon)
    if idx < 0:
        return 0.0
    best_dev = haversine_m(point.lat, point.lon,
                           points[idx].lat, points[idx].lon)
    best_m = stats.cum[idx]
    for a, b in ((idx - 1, idx), (idx, idx + 1)):
        if a < 0 or b >= len(points):
            continue
        pa, pb = points[a], points[b]
        seg_m = haversine_m(pa.lat, pa.lon, pb.lat, pb.lon)
        if seg_m <= 0:
            continue
        t = _project_on_segment(pa.lat, pa.lon, pb.lat, pb.lon,
                                point.lat, point.lon)
        on_lat = pa.lat + (pb.lat - pa.lat) * t
        on_lon = pa.lon + (pb.lon - pa.lon) * t
        dev = haversine_m(point.lat, point.lon, on_lat, on_lon)
        if dev < best_dev:
            best_dev = dev
            best_m = stats.cum[a] + seg_m * t
    return max(0.0, min(best_m, stats.distance_m))


# ---------------------------------------------------------------- 格式化

def fmt_distance(km: float) -> str:
    return f"{km:.2f}km"


def fmt_elapsed(seconds: float) -> str:
    """累计耗时 → h:mm。

    统一 h:mm 而不是 m:ss：轨迹常常跑好几个小时，「7:35」读作 7 小时 35 分；
    一小时以内显示「0:08」（8 分钟）。
    """
    total_min = int(round(max(0.0, seconds) / 60.0))
    return f"{total_min // 60}:{total_min % 60:02d}"


def fmt_seconds(seconds: float) -> str:
    """desc 里用的可读形式：3 小时 12 分。"""
    total = int(round(max(0.0, seconds) / 60.0))
    h, m = divmod(total, 60)
    if h and m:
        return f"{h} 小时 {m} 分"
    if h:
        return f"{h} 小时"
    return f"{m} 分"


# ---------------------------------------------------------------- 航点

def _attach_label(point: KmlPoint) -> str:
    if point.attach_name:
        return point.attach_name
    if point.attach_id:
        return f"照片 {point.attach_id}"
    return ""


# description 里的「时间」是 App 按 UTC+8 写出的本地钟点，解析时按 UTC 标号后
# 恰好等于真实时刻（见 _aligned_delta 的实测核对），因此不需要再做偏移补偿。


def _aligned_delta(local_wall: datetime, start_time: datetime) -> float | None:
    """把 description 里的本地钟点换成与轨迹起点的差值（秒）。

    实测核对（样本 wp1）：description 的「时间：10:43:05」是 UTC+8 本地钟点，
    按 UTC 标号解析后正好等于该点 ExtendedData 的 epoch（02:43:05Z），也与所属
    轨迹顶点（02:42:27Z）吻合 —— 两个字段是同一时刻的两种写法，直接相减即可。
    返回负数表示航点早于轨迹起点，交给调用方退化处理。
    """
    return (local_wall - start_time).total_seconds()


def waypoint_elapsed(point: KmlPoint, track_points, position_index: int) -> float | None:
    """累计耗时（秒）= 航点时间 − 轨迹首点时间，永不为负。

    时间来源优先级：description 里的「时间」→ ExtendedData 的毫秒 epoch
    （两者实测一致，前者字符串更直观，后者是结构化字段）。
    两者都不可用时，改用该定位处在轨迹上的耗时。
    """
    start_time = None
    for p in track_points or ():
        if p.time is not None:
            start_time = p.time
            break
    if start_time is not None:
        if point.desc_time is not None:
            delta = _aligned_delta(point.desc_time, start_time)
            if delta is not None and delta >= 0:
                return delta
        if point.time is not None:
            delta = (point.time - start_time).total_seconds()
            if delta >= 0:
                return delta
    if track_points and 0 <= position_index < len(track_points):
        anchor = track_points[position_index].time
        if anchor is not None and start_time is not None:
            delta = (anchor - start_time).total_seconds()
            if delta >= 0:
                return delta
    return None


def position_name(km: float, elapsed_s: float | None, ele: float | None) -> str:
    """#01 0.38km · 1:28；无时间时退化为 #01 0.38km · 377m。"""
    if elapsed_s is not None:
        return f"{fmt_distance(km)} · {fmt_elapsed(elapsed_s)}"
    if ele is not None:
        return f"{fmt_distance(km)} · {int(round(ele))}m"
    return fmt_distance(km)


def _clean_note(note: str) -> str:
    note = re.sub(r"\s+", " ", (note or "")).strip()
    return note[:60]


# 附件 JSON（[{"fileSize":"0","fileId":"..."}]）或纯数字 id 不是人写的备注
_MACHINE_NOTE_RE = re.compile(r"^[\s\[\]{}()\w,:\".-]*$")


def _readable_note(note: str) -> str:
    """只保留像人类写的备注；附件 JSON / id 串返回空。"""
    cleaned = _clean_note(note)
    if not cleaned:
        return ""
    if _MACHINE_NOTE_RE.match(cleaned):
        # 至少得有一个中文字符才当成备注
        if not re.search(r"[\u4e00-\u9fff]", cleaned):
            return ""
    return cleaned


def _dedupe(base: str, used: set) -> str:
    if base not in used:
        used.add(base)
        return base
    i = 2
    while f"{base} ({i})" in used:
        i += 1
    text = f"{base} ({i})"
    used.add(text)
    return text


def apply_junctions(names, junctions, tol_m: float = 40.0) -> int:
    """把落在路口附近的显著转向标成「路口转向」。

    按里程匹配（路口带的是沿轨迹累计距离），避免为了拿坐标去改航点数据结构。
    返回被升级为路口转向的个数。
    """
    if not junctions:
        return 0
    upgraded = 0
    for n in names:
        if not n.turn_text or n.km is None:
            continue
        pos_m = n.km * 1000.0
        best = None
        best_d = None
        for j in junctions:
            jm = j.get("distance_m")
            if jm is None:
                continue
            d = abs(jm - pos_m)
            if best_d is None or d < best_d:
                best, best_d = j, d
        if best is not None and best_d is not None and best_d <= tol_m:
            n.turn_text = "岔路口" + n.turn_text
            n.turn_kind = "junction"
            n.junction_ways = int(best.get("way_count") or 0)
            upgraded += 1
        else:
            n.turn_kind = "terrain"
    return upgraded


def name_waypoints(result: KmlResult, track_points, stats: TrackStats,
                   pad: int = 2, junctions=None, junction_tol_m: float = 40.0) -> list:
    """给普通航点取名，返回与 result.waypoints 等长的命名结果。"""
    index = _TrackIndex(track_points, stats) if track_points else None
    out = []
    used = set()
    total = len(result.waypoints)
    width = max(pad, len(str(total)))
    for i, point in enumerate(result.waypoints, start=1):
        seq = f"#{i:0{width}d}"

        km = None
        elapsed = None
        turn = None
        if index is not None:
            km = along_distance_m(track_points, stats, point) / 1000.0
            idx = index.nearest(point.lat, point.lon)
            elapsed = waypoint_elapsed(point, track_points, idx)
            turn = turn_at(track_points, stats, idx, span_m=TURN_SPAN_M)

        text, source = "", ""
        orig_name = _clean_note(point.name)
        note = _readable_note(point.note)
        if orig_name:
            text, source = orig_name, "name"
        if not text and note:
            # 备注最优先：用户亲手写的判断比任何推测都准。
            # 名称只用「序号 + 备注」，不再拼里程/耗时 —— 那些在 desc 里。
            text, source = note, "note"
        if not text:
            # 位置名称排第三：照片文件名/附件 id 对「走到哪了」没有帮助，
            # 只有连位置都算不出来时才退回到附件名。
            if km is not None:
                text, source = position_name(km, elapsed, point.ele), "position"
        if not text:
            label = _attach_label(point)
            if label:
                text, source = label, "attach"
        if not text:
            # 既没轨迹也没有照片：退化为钟点（desc 时间更贴近真实拍摄时刻）
            when = point.desc_time or point.time
            clock = when.strftime("%H:%M") if when else "航点"
            text = f"{clock} · {int(round(point.ele))}m" if point.ele is not None else clock
            source = "time"

        full = _dedupe(f"{seq} {text}", used)
        out.append(WaypointName(text=full, source=source, km=km,
                                elapsed_s=elapsed, note=note,
                                orig_name=orig_name, turn=turn,
                                turn_text=describe_turn(turn)))

    # 全局筛选：只有通过「幅度 + 合并 + 左右反复抑制」的才算显著转向。
    # 未通过的把 turn_text 清空，避免 AI 拿石头绕行去编「右转切上山脊」。
    significant = pick_significant_turns(out)
    for i, n in enumerate(out):
        if i not in significant:
            n.turn_text = ""

    # 有路网信息时，把落在路口附近的转向升级为「路口转向」，
    # 其余标为地形转向（提示时降权）。
    if junctions:
        apply_junctions(out, junctions, junction_tol_m)
    return out


def special_name(point: KmlPoint, label: str) -> WaypointName:
    return WaypointName(text=label, source="special")


# ---------------------------------------------------------------- 轨迹

def strip_date_prefix(name: str) -> str:
    """去掉名称开头的日期（2023-02-18 / 2023年2月18日 / 20230218）。"""
    name = (name or "").strip()
    m = DATE_PREFIX_RE.match(name)
    if m:
        return name[m.end():].strip(" _-·")
    m = re.match(r"^(\d{4})(\d{2})(\d{2})[\s_-]+", name)
    if m:
        return name[m.end():].strip(" _-·")
    return name


def place_from_name(name: str) -> str:
    """从文件名/文档名里挖出地名：剥扩展名、剥日期前缀、剥占位词。"""
    candidate = re.sub(r"\.(kml|kmz|gpx)$", "", (name or "").strip(), flags=re.I)
    candidate = strip_date_prefix(candidate)
    candidate = DATE_TOKEN_RE.sub("", candidate).strip(" _-·")
    candidate = re.sub(r"[_]+", " ", candidate)
    candidate = re.sub(r"\s+", " ", candidate).strip()
    if not candidate or PLACEHOLDER_RE.match(candidate):
        return ""
    return candidate


def start_date(tracks, fallback_text: str = "") -> str:
    """轨迹开始日期 YYYY-MM-DD：优先首个有效时间，其次名字里的日期。"""
    for track in tracks or ():
        for p in track.points:
            if p.time is not None:
                return p.time.strftime("%Y-%m-%d")
    m = re.search(r"(\d{4})[-_./年]?(\d{1,2})[-_./月]?(\d{1,2})", fallback_text or "")
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return ""


def sport_label(result: KmlResult) -> str:
    extras = result.document_extras or {}
    for key in ("SportTypeName", "SportType", "TrackTags"):
        val = (extras.get(key) or "").strip()
        if val and not val.isdigit():
            return val
    return ""


def track_names(result: KmlResult, source_label: str = "",
                custom_name: str = "") -> list:
    """为每条轨迹生成名称。

    有用户指定 → 用指定名（多段加 1/2、2/2）。
    否则 → 「地点 日期 运动类型」，缺项省略；地点永远在最前。
    """
    n = len(result.tracks)
    custom = (custom_name or "").strip()
    if custom:
        if n <= 1:
            return [custom]
        return [f"{custom} {i}/{n}" for i in range(1, n + 1)]

    # 地点候选按信息量排序：文件名常常被改成 a.kml / x.kml 这种占位，
    # 文件内的 Document 名反而更可信。太短（<=2 字）的候选视为占位跳过。
    candidates = [place_from_name(source_label), place_from_name(result.doc_name)]
    place = next((c for c in candidates if c and len(c) > 2), "") \
        or next((c for c in candidates if c), "")
    date = start_date(result.tracks, source_label or result.doc_name)
    sport = sport_label(result)

    parts = [p for p in (place, date, sport) if p]
    if not parts:
        parts = [date or "轨迹"]
    base = " ".join(parts)

    if n <= 1:
        return [base]
    return [f"{base} {i}/{n}" for i in range(1, n + 1)]
