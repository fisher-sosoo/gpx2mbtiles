import sqlite3
import time

import httpx

BASE = "http://127.0.0.1:18099"
c = httpx.Client(base_url=BASE, timeout=60)

r = c.get("/api/health")
assert r.status_code == 200

gpx_path = "/Users/n22008/Downloads/2025-12-10 上雨崩-冰湖切尼色-下雨崩.gpx"
with open(gpx_path, "rb") as f:
    gpx = f.read()
print("gpx bytes:", len(gpx))

files = {"file": ("yubeng.gpx", gpx, "application/gpx+xml")}
data = {"buffer_meters": "500", "min_zoom": "12", "max_zoom": "16",
        "concurrency": "4", "interval_ms": "50"}
r = c.post("/api/submit", files=files, data=data, timeout=60)
assert r.status_code == 200, r.text
tid = r.json()["task_id"]
print("submitted task:", tid)

expect_tiles = 94  # 与离线分析一致
last_dl = -1
t_start = time.monotonic()
for _ in range(2400):  # 最多 10 分钟
    s = c.get("/api/status/" + tid).json()
    if s["downloaded"] != last_dl:
        pct = (s["downloaded"] / s["total_tiles"] * 100) if s["total_tiles"] else 0
        print(f"[{time.monotonic()-t_start:6.1f}s] {s['status']:12s} "
              f"{s['downloaded']:4d}/{s['total_tiles']:4d} ({pct:5.1f}%) fail={s['failed_tiles']}")
        last_dl = s["downloaded"]
    if s["status"] in ("completed", "failed", "cancelled"):
        break
    time.sleep(0.5)

print("final:", s["status"], "| downloaded:", s["downloaded"],
      "| failed:", s["failed_tiles"], "| error:", s["error"])
assert s["status"] == "completed", s
assert s["total_tiles"] == expect_tiles, f"tiles mismatch: {s['total_tiles']} != {expect_tiles}"
assert s["downloaded"] == expect_tiles and s["failed_tiles"] == 0

r = c.get("/api/download/" + tid, timeout=60)
assert r.status_code == 200
body = r.content
out = f"real_{tid}.mbtiles"
with open(out, "wb") as f:
    f.write(body)
print("downloaded:", len(body), "bytes ->", out)

conn = sqlite3.connect(out)
meta = dict(conn.execute("SELECT name, value FROM metadata").fetchall())
n = conn.execute("SELECT count(*) FROM tiles").fetchone()[0]
conn.close()
print("mbtiles metadata:", {k: meta[k] for k in ("name","format","minzoom","maxzoom")},
      "| bounds:", meta["bounds"], "| tiles:", n)
assert n == expect_tiles
print("REAL-GPX E2E PASS")
