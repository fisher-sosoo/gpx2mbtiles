"""沿轨迹识别岔路口。

为什么不用下载 mbtiles：

* OpenTopoMap 的 mbtiles 是**栅格**瓦片（已渲染的像素），里面没有矢量拓扑，
  想从像素里推岔路只能做图像识别，既不可靠也不划算。
* 真正需要的是**路网矢量**：一个 4km 包围盒的 highway 几何只有约 185 KB，
  比下载一堆图片便宜得多，也好缓存。

判定方法：轨迹上某点 **R 米内出现两条及以上不同道路** 即判为路口。
不需要解析路网连通性；已知局限是「两条平行但不相交的路靠得近」会误判，
25 米阈值下影响有限。
"""
from __future__ import annotations

import logging
import math
import time
import urllib.error

from .poi_enricher import PoiQueryError, _proxy_candidates, _query_once

logger = logging.getLogger(__name__)

# 只取与徒步相关的道路类。刻意排除 motorway/trunk。
HIGHWAYS = "^(path|footway|track|steps|bridleway|service|residential|unclassified)$"
JUNCTION_RADIUS_M = 25.0        # 判定半径
JUNCTION_MERGE_POINTS = 8       # 连续判定点合并间隔（采样点个数）
# 转向点离路口多近算「路口转向」。
# 实测：同一处决策点，路口采样点与航点能差 100~200 米（航点按固定里程取，
# 路口按道路顶点取），40 米会全部漏掉，250 米才可靠。
JUNCTION_TURN_TOL_M = 250.0
_CELL = 0.0005                  # 网格单元，约 55 米
M_PER_DEG_LAT = 111320.0


def build_query(bbox, timeout_s: int = 90) -> str:
    s, w, n, e = bbox
    box = "{:.6f},{:.6f},{:.6f},{:.6f}".format(s, w, n, e)
    return (
        "[out:json][timeout:{:d}];\n(\n".format(int(timeout_s))
        + '  way["highway"~"{:s}"]({:s});\n'.format(HIGHWAYS, box)
        + ");\nout geom;"
    )


def fetch_ways(bbox, settings) -> list:
    """取路网几何。与地名查询走同样的代理轮换与退避重试。"""
    query = build_query(bbox, 90)
    proxies = _proxy_candidates(settings) or [""]
    retries = getattr(settings, "poi_retry_max", 2)
    # 连接被断（Overpass 限流/过载）需要更长的冷却，2s 往往还没恢复
    delays = (5.0, 15.0, 30.0)
    timeout_s = getattr(settings, "poi_timeout_seconds", 180)
    last = "查询失败"
    for attempt in range(retries + 1):
        proxy = proxies[attempt % len(proxies)]
        try:
            els = _query_once(query, settings, timeout_s, proxy)
            out = []
            for e in els:
                geom = e.get("geometry") or []
                if e.get("type") != "way" or len(geom) < 2:
                    continue
                out.append({
                    "id": e.get("id"),
                    "verts": [(g["lat"], g["lon"]) for g in geom
                              if g.get("lat") is not None and g.get("lon") is not None],
                })
            return [w for w in out if len(w["verts"]) >= 2]
        except urllib.error.HTTPError as exc:
            last = "上游返回 %s" % exc.code
            if exc.code < 500:
                raise PoiQueryError(last) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = "查询失败：%s" % exc
        except (ValueError, KeyError, TypeError) as exc:
            last = "响应异常：%s" % exc
        if attempt < retries:
            wait = delays[min(attempt, len(delays) - 1)]
            logger.warning("junction query attempt %d via %s failed (%s), retry in %.0fs",
                           attempt + 1, proxy or "direct", last, wait)
            time.sleep(wait)
    raise PoiQueryError(last + "（已重试 %d 次）" % retries)


class _VertexGrid:
    """把道路顶点放进网格，避免轨迹点 × 顶点数的二次复杂度。

    一个 4km 包围盒内通常几百个顶点，但景区密集时可达数万；
    逐个比较会退化成千万次循环，网格把每次查询压到常数级。
    """

    def __init__(self, ways, cell: float = _CELL):
        self.cell = cell
        self.grid = {}
        for w in ways:
            wid = w["id"]
            for la, lo in w["verts"]:
                key = (int(la // cell), int(lo // cell))
                bucket = self.grid.get(key)
                if bucket is None:
                    self.grid[key] = bucket = []
                bucket.append((wid, la, lo))

    def ways_within(self, lat: float, lon: float, radius_m: float) -> set:
        """返回半径内出现过顶点的道路 id 集合。"""
        cell = self.cell
        coslat = math.cos(math.radians(lat))
        if abs(coslat) < 0.05:
            coslat = 0.05 if coslat >= 0 else -0.05
        deg_lat = radius_m / M_PER_DEG_LAT
        deg_lon = radius_m / (M_PER_DEG_LAT * abs(coslat))
        x0 = int((lat - deg_lat) // cell)
        x1 = int((lat + deg_lat) // cell)
        y0 = int((lon - deg_lon) // cell)
        y1 = int((lon + deg_lon) // cell)
        r2 = radius_m * radius_m
        found = set()
        for cx in range(x0, x1 + 1):
            for cy in range(y0, y1 + 1):
                for wid, vlat, vlon in self.grid.get((cx, cy), ()):
                    dy = (vlat - lat) * M_PER_DEG_LAT
                    dx = (vlon - lon) * M_PER_DEG_LAT * abs(coslat)
                    if dx * dx + dy * dy <= r2:
                        found.add(wid)
        return found


def find_junctions(points, ways, radius_m: float = JUNCTION_RADIUS_M,
                   merge: int = JUNCTION_MERGE_POINTS) -> list:
    """points: [(lat, lon, cum_m)]；返回合并后的路口列表。"""
    if not ways or not points:
        return []
    grid = _VertexGrid(ways)
    hits = []
    for i, item in enumerate(points):
        la, lo = item[0], item[1]
        cum = item[2] if len(item) > 2 else None
        near = grid.ways_within(la, lo, radius_m)
        if len(near) >= 2:
            hits.append([i, la, lo, len(near), cum])

    merged = []
    for h in hits:
        if merged and h[0] - merged[-1][0] <= merge:
            # 同一处路口：保留交汇路数更多的那个点
            if h[3] > merged[-1][3]:
                merged[-1] = h
            continue
        merged.append(h)

    return [{
        "index": h[0],
        "lat": round(h[1], 6),
        "lon": round(h[2], 6),
        "way_count": h[3],
        "distance_m": round(h[4], 1) if h[4] is not None else None,
    } for h in merged]


def meters_between(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """短距离等距近似，够用且比 haversine 便宜。"""
    coslat = math.cos(math.radians((lat1 + lat2) / 2.0))
    dy = (lat2 - lat1) * M_PER_DEG_LAT
    dx = (lon2 - lon1) * M_PER_DEG_LAT * coslat
    return math.hypot(dx, dy)


def nearest_junction(lat, lon, junctions, tol_m: float = JUNCTION_TURN_TOL_M):
    """返回 (路口, 距离)；超出容差返回 (None, None)。"""
    best = None
    best_d = None
    for j in junctions or ():
        d = meters_between(lat, lon, j["lat"], j["lon"])
        if best_d is None or d < best_d:
            best, best_d = j, d
    if best is None or best_d is None or best_d > tol_m:
        return None, None
    return best, best_d
