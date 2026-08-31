import time

from app.gpx_processor import build_tile_plan, parse_gpx

path = "/Users/n22008/Downloads/2025-12-10 上雨崩-冰湖切尼色-下雨崩.gpx"
data = open(path, "rb").read()
print("file bytes:", len(data))

t0 = time.monotonic()
points, name = parse_gpx(data)
t1 = time.monotonic()
print(f"parse: {len(points)} points in {t1-t0:.3f}s, name={name!r}")

lats = [p[0] for p in points]
lons = [p[1] for p in points]
print(f"bounds: lon [{min(lons):.6f}, {max(lons):.6f}] lat [{min(lats):.6f}, {max(lats):.6f}]")

# 轨迹长度粗估（米，球面近似）
import math
def haversine(a, b):
    la1, lo1 = map(math.radians, a)
    la2, lo2 = map(math.radians, b)
    dlo = lo2 - lo1
    dla = la2 - la1
    h = math.sin(dla/2)**2 + math.cos(la1)*math.cos(la2)*math.sin(dlo/2)**2
    return 6371000 * 2 * math.asin(math.sqrt(h))

total_m = sum(haversine(a, b) for a, b in zip(points, points[1:]))
print(f"track length: {total_m/1000:.2f} km")

# 常见配置的瓦片数估算
for buf in (100, 500):
    for zmax in (13, 14, 15, 16):
        t0 = time.monotonic()
        plan = build_tile_plan(points, buf, 12, zmax, 200000)
        dt = time.monotonic() - t0
        print(f"buffer={buf:4d}m zoom 12-{zmax:2d}: tiles={len(plan.tiles):6d}  plan-time={dt:.2f}s")
