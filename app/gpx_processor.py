import math
from dataclasses import dataclass

import gpxpy


class GpxParseError(ValueError):
    """GPX 文件无法解析或内容无效。"""


@dataclass
class TilePlan:
    tiles: list
    bounds: tuple
    point_count: int


def parse_gpx(data: bytes):
    """解析 GPX 字节流，返回 (轨迹点列表 [(lat, lon), ...], 轨迹名)。"""
    if not data or not data.strip():
        raise GpxParseError("GPX 文件为空")
    try:
        gpx = gpxpy.parse(data)
    except Exception as exc:
        raise GpxParseError(f"GPX 解析失败：{exc}") from exc

    points = []
    for track in gpx.tracks:
        for segment in track.segments:
            for point in segment.points:
                lat, lon = float(point.latitude), float(point.longitude)
                if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0:
                    points.append((lat, lon))
    for route in gpx.routes:
        for point in route.points:
            lat, lon = float(point.latitude), float(point.longitude)
            if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0:
                points.append((lat, lon))
    for waypoint in gpx.waypoints:
        lat, lon = float(waypoint.latitude), float(waypoint.longitude)
        if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0:
            points.append((lat, lon))

    if not points:
        raise GpxParseError("GPX 文件中未找到有效轨迹点（trkpt/rtept/wpt）")

    name = "track"
    if gpx.tracks and gpx.tracks[0].name:
        name = gpx.tracks[0].name
    return points, name


def _tile_ranges_for_point(lat: float, lon: float, buffer_meters: float, zoom: int):
    """以轨迹点为中心、buffer 米为缓冲，计算覆盖的 (x, y) 瓦片范围。"""
    n = 1 << zoom
    lat = max(-85.0, min(85.0, lat))
    d_lat = buffer_meters / 111320.0
    cos_lat = max(0.0001, math.cos(math.radians(lat)))
    d_lon = buffer_meters / (111320.0 * cos_lat)

    min_lat, max_lat = lat - d_lat, lat + d_lat
    min_lon, max_lon = lon - d_lon, lon + d_lon

    def xtile(lonv: float) -> int:
        return int((lonv + 180.0) / 360.0 * n)

    def ytile(latv: float) -> int:
        latv = max(-85.05112878, min(85.05112878, latv))
        lat_rad = math.radians(latv)
        return int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)

    x1, x2 = xtile(min_lon), xtile(max_lon)
    min_x, max_x = min(x1, x2), max(x1, x2)
    y1, y2 = ytile(min_lat), ytile(max_lat)
    min_y, max_y = min(y1, y2), max(y1, y2)

    min_x = max(0, min(min_x, n - 1))
    max_x = max(0, min(max_x, n - 1))
    min_y = max(0, min(min_y, n - 1))
    max_y = max(0, min(max_y, n - 1))
    return min_x, max_x, min_y, max_y


def build_tile_plan(points, buffer_meters: float, min_zoom: int, max_zoom: int,
                    max_tiles=None) -> TilePlan:
    """根据轨迹点与缓冲距离，计算全部需要下载的 XYZ 瓦片（去重、排序）。

    max_tiles 为 None 时不设上限（估算/用户确认放行场景）。
    """
    if min_zoom > max_zoom:
        raise GpxParseError(
            f"最小缩放级别({min_zoom})不能大于最大缩放级别({max_zoom})")

    tiles = set()
    for lat, lon in points:
        for zoom in range(min_zoom, max_zoom + 1):
            min_x, max_x, min_y, max_y = _tile_ranges_for_point(
                lat, lon, buffer_meters, zoom)
            for x in range(min_x, max_x + 1):
                for y in range(min_y, max_y + 1):
                    tiles.add((zoom, x, y))
        if max_tiles is not None and len(tiles) > max_tiles:
            raise GpxParseError(
                f"瓦片数量超过上限（{len(tiles)} > {max_tiles}），请缩小缓冲距离或"
                f"缩放范围，或把长轨迹拆分为多段分别生成")

    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    bounds = (min(lons), min(lats), max(lons), max(lats))
    return TilePlan(tiles=sorted(tiles), bounds=bounds, point_count=len(points))
