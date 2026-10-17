"""OSM 地名补点：把「垭口 / 牛场 / 营地 / 山峰 / 湖泊 / 过河点」补成航点。

实测约束（docs/NEXT-ITERATIONS.md 第 4 节）：

* Overpass 单次查询约 42 秒，且只有 overpass-api.de 通（其他镜像 5xx），
  墙内必须走代理 —— 所以只能做成**后台任务 + 结果缓存**，不能同步返回。
* 距离阈值必须**按类型分**：垭口/牛场实测离轨迹 1~30 米，一刀切会把它们全滤掉；
  山峰（三神山）离轨迹 1.7~2.3km 但全程可见，反而是该标的。
* 河流不能按距离判，否则沿河走几十公里会标上百次；只能按**几何相交**判过河。
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "gpx2mbtiles/1.0 (personal hiking tool)"

# 类型 -> 距轨迹的最大容忍距离（米）。None 表示不按距离判（河流按相交判）。
POI_MAX_DISTANCE_M = {
    "saddle": 200.0,
    "mountain_pass": 200.0,
    "camp_site": 200.0,
    "alpine_hut": 200.0,
    "wilderness_hut": 200.0,
    "shelter": 200.0,
    "peak": 3000.0,
    "water": 300.0,
    "viewpoint": 300.0,
}

# 类型中文名（写进航点描述）
TYPE_LABELS = {
    "saddle": "垭口",
    "mountain_pass": "山隘",
    "camp_site": "营地",
    "alpine_hut": "山屋",
    "wilderness_hut": "野营点",
    "shelter": "避难所",
    "peak": "山峰",
    "water": "湖泊",
    "viewpoint": "观景点",
    "place_village": "村庄",
    "place_hamlet": "村落",
    "place_town": "城镇",
    "place_isolated_dwelling": "散户",
    "stream": "过河",
    "river": "过河",
}

# 重要性排序：截断时优先保留靠前的
TYPE_PRIORITY = {
    "saddle": 0, "mountain_pass": 0,
    "camp_site": 1, "alpine_hut": 1, "wilderness_hut": 1, "shelter": 1,
    "peak": 2,
    "water": 3, "viewpoint": 3,
    "river": 4, "stream": 4,
    "place_town": 5, "place_village": 5, "place_hamlet": 5,
    "place_isolated_dwelling": 6,
}

R = 6371008.8


def haversine_m(a_lat, a_lon, b_lat, b_lon) -> float:
    d_lat = math.radians(b_lat - a_lat)
    d_lon = math.radians(b_lon - a_lon)
    h = (math.sin(d_lat / 2) ** 2
         + math.cos(math.radians(a_lat)) * math.cos(math.radians(b_lat))
         * math.sin(d_lon / 2) ** 2)
    return 2 * R * math.asin(min(1.0, math.sqrt(h)))


# ---------------------------------------------------------------- 查询

def build_query(bbox, timeout_s: int) -> str:
    s, w, n, e = bbox
    box = f"{s:.6f},{w:.6f},{n:.6f},{e:.6f}"
    return (
        f"[out:json][timeout:{timeout_s}];\n(\n"
        f'  node["natural"="saddle"]({box});\n'
        f'  node["mountain_pass"="yes"]({box});\n'
        f'  node["natural"="peak"]["name"]({box});\n'
        f'  node["natural"="water"]["name"]({box});\n'
        f'  way["natural"="water"]["name"]({box});\n'
        f'  node["tourism"~"^(camp_site|alpine_hut|wilderness_hut)$"]({box});\n'
        f'  node["amenity"="shelter"]({box});\n'
        f'  node["tourism"="viewpoint"]["name"]({box});\n'
        f'  node["place"~"^(town|village|hamlet|isolated_dwelling)$"]({box});\n'
        f'  way["waterway"~"^(river|stream)$"]["name"]({box});\n'
        ");\nout geom tags;"
    )


def fetch_overpass(bbox, settings, timeout_s: int = 180) -> list:
    """同步查询（放到线程里跑，避免堵事件循环）。"""
    query = build_query(bbox, timeout_s=120)
    data = urllib.parse.urlencode({"data": query}).encode("utf-8")
    req = urllib.request.Request(OVERPASS_URL, data=data, headers={
        "User-Agent": USER_AGENT,
        "Content-Type": "application/x-www-form-urlencoded",
    })
    proxy = getattr(settings, "poi_proxy", "") or getattr(settings, "tile_proxy", "")
    if proxy:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"https": proxy, "http": proxy}))
    else:
        opener = urllib.request.build_opener()
    try:
        with opener.open(req, timeout=timeout_s) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise PoiQueryError(f"上游返回 {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise PoiQueryError(f"查询失败：{exc}") from exc
    except json.JSONDecodeError as exc:
        raise PoiQueryError(f"响应不是合法 JSON：{exc}") from exc
    return payload.get("elements", []) or []


class PoiQueryError(RuntimeError):
    """地名查询失败。"""


# ---------------------------------------------------------------- 几何工具

class _TrackGrid:
    """轨迹点的网格索引，用于「POI 到轨迹最近距离」。

    24768 个点 × 120 个 POI 直接全量比较要跑好几秒，分格后只看邻近格子。
    """

    CELL = 0.01       # 约 1.1km

    def __init__(self, points):
        self.points = points
        self.cells: dict = {}
        for idx, (lat, lon) in enumerate(points):
            key = (int(math.floor(lat / self.CELL)), int(math.floor(lon / self.CELL)))
            self.cells.setdefault(key, []).append((lat, lon, idx))
        lats = [p[0] for p in points]
        lons = [p[1] for p in points]
        self._bounds = (min(lats), min(lons), max(lats), max(lons)) if points else (0, 0, 0, 0)

    def min_distance(self, lat, lon) -> float:
        if not self.points:
            return float("inf")
        ilat = int(math.floor(lat / self.CELL))
        ilon = int(math.floor(lon / self.CELL))
        best = float("inf")
        # 半径逐圈扩大：先看本格，再一圈圈外扩，找到后多扩一圈即可
        for radius in range(0, 40):
            found = False
            for di in range(-radius, radius + 1):
                for dj in range(-radius, radius + 1):
                    if radius and max(abs(di), abs(dj)) != radius:
                        continue
                    for plat, plon, _idx in self.cells.get((ilat + di, ilon + dj), ()):
                        d = haversine_m(lat, lon, plat, plon)
                        if d < best:
                            best = d
                            found = True
            if best < float("inf") and radius >= 1:
                break
            if not found and radius > 30:
                break
        if best == float("inf"):
            for plat, plon in self.points:
                d = haversine_m(lat, lon, plat, plon)
                if d < best:
                    best = d
        return best


def _element_point(el):
    """取出一个要素的代表点。节点用自身坐标，面/线用几何中心。"""
    if "lat" in el and "lon" in el:
        return float(el["lat"]), float(el["lon"])
    geom = el.get("geometry") or []
    if not geom:
        center = el.get("center") or {}
        if "lat" in center:
            return float(center["lat"]), float(center["lon"])
        return None
    lats = [g["lat"] for g in geom if "lat" in g]
    lons = [g["lon"] for g in geom if "lon" in g]
    if not lats:
        return None
    return sum(lats) / len(lats), sum(lons) / len(lons)


def _element_polyline(el):
    geom = el.get("geometry") or []
    out = [(float(g["lat"]), float(g["lon"])) for g in geom
           if "lat" in g and "lon" in g]
    if len(out) >= 2:
        return out
    pt = _element_point(el)
    return [pt] if pt else []


def _kind_of(tags: dict) -> str:
    if tags.get("natural") in ("saddle",):
        return "saddle"
    if tags.get("mountain_pass") == "yes":
        return "mountain_pass"
    if tags.get("natural") == "peak":
        return "peak"
    if tags.get("natural") == "water":
        return "water"
    if tags.get("waterway") in ("river", "stream"):
        return tags["waterway"]
    if tags.get("tourism") in ("camp_site", "alpine_hut", "wilderness_hut", "viewpoint"):
        return tags["tourism"]
    if tags.get("amenity") == "shelter":
        return "shelter"
    place = tags.get("place")
    if place:
        return "place_" + place
    return ""


def _name_of(tags: dict) -> str:
    for key in ("name:zh", "name:zh-Hans", "name", "name:en"):
        v = (tags.get(key) or "").strip()
        if v:
            return v
    return ""


# ---------------------------------------------------------------- 过河检测

def _point_seg_side(p, a, b):
    """点 p 相对线段 ab 的位置：(到线段距离米, 有符号侧别)。

    侧别用叉积算，正负表示在河的两岸；为 0 表示正好落在线上。
    距离用「到线段」而不是「到无限直线」，避免远端的平行河段误判。
    """
    # 平面近似：1 度纬度 ≈ 111320m，经度按纬度收缩
    k = math.cos(math.radians(p[0]))
    px, py = p[1] * k, p[0]
    ax, ay = a[1] * k, a[0]
    bx, by = b[1] * k, b[0]
    dx, dy = bx - ax, by - ay
    denom = dx * dx + dy * dy
    if denom <= 1e-18:
        d_m = haversine_m(p[0], p[1], a[0], a[1])
        return d_m, 0.0
    t = ((px - ax) * dx + (py - ay) * dy) / denom
    side = (px - ax) * dy - (py - ay) * dx
    if t <= 0.0:
        return haversine_m(p[0], p[1], a[0], a[1]), side
    if t >= 1.0:
        return haversine_m(p[0], p[1], b[0], b[1]), side
    cx, cy = ax + dx * t, ay + dy * t
    # 转回经纬度再算球面距离
    lat = cy
    lon = cx / k if k > 1e-9 else cx
    return haversine_m(p[0], p[1], lat, lon), side


def _orient(a, b, c) -> float:
    return (b[1] - a[1]) * (c[0] - a[0]) - (b[0] - a[0]) * (c[1] - a[1])


def _on_segment(a, b, p) -> bool:
    """p 落在 ab 的包围盒内（配合 |orient|≈0 判断点在线上）。"""
    return (min(a[0], b[0]) - 1e-12 <= p[0] <= max(a[0], b[0]) + 1e-12
            and min(a[1], b[1]) - 1e-12 <= p[1] <= max(a[1], b[1]) + 1e-12)


def _crosses(ta, tb, ra, rb) -> bool:
    """轨迹段 ta→tb 是否穿过河段 ra→rb。

    用严格相交，但额外处理「端点正好落在河上」的退化情形 ——
    实测轨迹穿过河流时，交点常常正好落在某个轨迹顶点或河段端点上，
    只判严格「一正一负」会漏掉这些情况。
    """
    tol = 1e-13
    d1 = _orient(ra, rb, ta)
    d2 = _orient(ra, rb, tb)
    d3 = _orient(ta, tb, ra)
    d4 = _orient(ta, tb, rb)

    if ((d1 > tol and d2 < -tol) or (d1 < -tol and d2 > tol)) and \
            ((d3 > tol and d4 < -tol) or (d3 < -tol and d4 > tol)):
        return True

    if abs(d1) <= tol and _on_segment(ra, rb, ta):
        return True
    if abs(d2) <= tol and _on_segment(ra, rb, tb):
        return True
    if abs(d3) <= tol and _on_segment(ta, tb, ra):
        return True
    if abs(d4) <= tol and _on_segment(ta, tb, rb):
        return True
    return False


def _river_crossings(track_points, rivers, cell: float = 0.005):
    """返回 {river_name: (lat, lon)} —— 每条河只记第一次过河点。"""
    if not track_points or not rivers:
        return {}
    # 线段网格：把河流段按格子索引
    grid: dict = {}
    for name, poly in rivers.items():
        for i in range(1, len(poly)):
            a, b = poly[i - 1], poly[i]
            key = (int(math.floor((a[0] + b[0]) / 2 / cell)),
                   int(math.floor((a[1] + b[1]) / 2 / cell)))
            grid.setdefault(key, []).append((name, a, b))

    found: dict = {}
    for i in range(1, len(track_points)):
        ta, tb = track_points[i - 1], track_points[i]
        # 轨迹段很短，看自身所在格与 8 邻域即可
        keys = set()
        for p in (ta, tb):
            base = (int(math.floor(p[0] / cell)), int(math.floor(p[1] / cell)))
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    keys.add((base[0] + di, base[1] + dj))
        for key in keys:
            for name, ra, rb in grid.get(key, ()):
                if name in found:
                    continue
                if _crosses(ta, tb, ra, rb):
                    found[name] = (tb[0], tb[1])
    return found


# ---------------------------------------------------------------- 过滤

@dataclass
class PoiResult:
    items: list = field(default_factory=list)
    total_raw: int = 0
    dropped: int = 0
    truncated: int = 0
    fetched_at: float = 0.0


def filter_pois(elements, track_points, settings) -> PoiResult:
    """按类型规则筛选，去重，截断。"""
    result = PoiResult(total_raw=len(elements), fetched_at=time.time())
    if not track_points:
        return result

    grid = _TrackGrid(track_points)
    start_pt, end_pt = track_points[0], track_points[-1]
    max_pois = getattr(settings, "poi_max_count", 60)

    # 累计里程：给每个地名点标出「在路线第几公里」，行前指南要按这个排序
    cum = [0.0]
    for i in range(1, len(track_points)):
        cum.append(cum[-1] + haversine_m(track_points[i - 1][0], track_points[i - 1][1],
                                         track_points[i][0], track_points[i][1]))

    rivers = {}
    candidates = []
    for el in elements:
        tags = el.get("tags") or {}
        name = _name_of(tags)
        if not name:
            continue
        kind = _kind_of(tags)
        if not kind:
            continue

        if kind in ("river", "stream"):
            poly = _element_polyline(el)
            if len(poly) >= 2:
                rivers.setdefault(name, poly)
            continue

        pt = _element_point(el)
        if pt is None:
            continue
        lat, lon = pt
        dist = grid.min_distance(lat, lon)

        if kind.startswith("place_"):
            # 村镇：只有位于起终点附近才标，路过不标
            near = min(haversine_m(lat, lon, start_pt[0], start_pt[1]),
                       haversine_m(lat, lon, end_pt[0], end_pt[1]))
            if near > 200.0:
                continue
            dist = near
        else:
            limit = POI_MAX_DISTANCE_M.get(kind)
            if limit is None or dist > limit:
                continue

        candidates.append({
            "name": name,
            "kind": kind,
            "type_label": TYPE_LABELS.get(kind, kind),
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "ele": _safe_float(tags.get("ele")),
            "distance_m": round(dist, 1),
            "km": _km_at(track_points, cum, lat, lon),
            "source": "osm",
            "detail": _detail_of(tags),
        })

    # 过河点
    crossings = _river_crossings(track_points, rivers)
    for name, (lat, lon) in crossings.items():
        dist = grid.min_distance(lat, lon)
        candidates.append({
            "name": name,
            "kind": "river",
            "type_label": TYPE_LABELS["river"],
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "ele": None,
            "distance_m": round(dist, 1),
            "km": _km_at(track_points, cum, lat, lon),
            "source": "osm",
            "detail": "过河点",
        })

    # 同名去重：保留离轨迹最近的
    best: dict = {}
    for c in candidates:
        key = (c["name"], c["kind"])
        cur = best.get(key)
        if cur is None or c["distance_m"] < cur["distance_m"]:
            best[key] = c
    result.dropped = len(candidates) - len(best)

    items = list(best.values())
    items.sort(key=lambda x: (TYPE_PRIORITY.get(x["kind"], 9), x["distance_m"]))
    if len(items) > max_pois:
        result.truncated = len(items) - max_pois
        items = items[:max_pois]
    result.items = items
    return result


def _km_at(track_points, cum, lat, lon):
    """某个坐标在路线上的大致里程（取最近轨迹点的累计值）。"""
    if not track_points or not cum:
        return None
    idx = _nearest_index(track_points, lat, lon)
    return round(cum[idx] / 1000.0, 2)


# 最近点索引缓存：同一条轨迹会被多个地名点反复查询
_NEAREST_CACHE: dict = {}


def _nearest_index(track_points, lat, lon) -> int:
    """网格加速的最近轨迹点查找。"""
    cell = _TrackGrid.CELL
    ilat = int(math.floor(lat / cell))
    ilon = int(math.floor(lon / cell))
    key = id(track_points)
    grid = _NEAREST_CACHE.get(key)
    if grid is None:
        grid = {}
        for i, (plat, plon) in enumerate(track_points):
            k = (int(math.floor(plat / cell)), int(math.floor(plon / cell)))
            grid.setdefault(k, []).append((plat, plon, i))
        _NEAREST_CACHE[key] = grid
    best_i, best_d = 0, float("inf")
    for radius in range(0, 8):
        for di in range(-radius, radius + 1):
            for dj in range(-radius, radius + 1):
                if radius and max(abs(di), abs(dj)) != radius:
                    continue
                for plat, plon, idx in grid.get((ilat + di, ilon + dj), ()):
                    d = haversine_m(lat, lon, plat, plon)
                    if d < best_d:
                        best_i, best_d = idx, d
        if best_d < float("inf") and radius >= 1:
            break
    return best_i


def _safe_float(v):
    try:
        return round(float(v), 1)
    except (TypeError, ValueError):
        return None


def _detail_of(tags: dict) -> str:
    bits = []
    for key, prefix in (("ele", "海拔 "), ("operator", ""), ("description", "")):
        v = (tags.get(key) or "").strip()
        if v and key != "ele":
            bits.append(v[:40])
    return " · ".join(bits)
