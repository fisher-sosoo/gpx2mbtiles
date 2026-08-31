import sqlite3, time
import httpx
c = httpx.Client(base_url="http://127.0.0.1:18099", timeout=60)
with open("/Users/n22008/Downloads/2025-12-10 上雨崩-冰湖切尼色-下雨崩.gpx", "rb") as f:
    gpx = f.read()
files = {"file": ("2025-12-10 上雨崩-冰湖切尼色-下雨崩.gpx", gpx, "application/gpx+xml")}
data = {"buffer_meters": "100", "min_zoom": "12", "max_zoom": "13",
        "concurrency": "4", "interval_ms": "0"}
r = c.post("/api/submit", files=files, data=data)
assert r.status_code == 200, r.text
tid = r.json()["task_id"]
for _ in range(200):
    s = c.get("/api/status/" + tid).json()
    if s["status"] in ("completed", "failed", "cancelled"):
        break
    time.sleep(0.2)
print("status:", s["status"], "| name:", s["name"], "| tiles:", s["total_tiles"], "| dl:", s["downloaded"])
assert s["status"] == "completed"
assert s["name"] == "2025-12-10 上雨崩-冰湖切尼色-下雨崩", s["name"]
r = c.get("/api/download/" + tid)
assert r.status_code == 200
hd = r.headers.get("content-disposition", "")
print("content-disposition:", hd)
assert "2025-12-10" in hd and "mbtiles" in hd
print("NAME-FIX PASS")
