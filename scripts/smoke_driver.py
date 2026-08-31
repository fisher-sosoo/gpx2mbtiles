import sqlite3
import time

import httpx

BASE = "http://127.0.0.1:18099"
c = httpx.Client(base_url=BASE, timeout=30)

r = c.get("/api/health")
assert r.status_code == 200, r.text
print("health ok:", r.json())

gpx = open("smoke.gpx", "rb").read()
files = {"file": ("smoke.gpx", gpx, "application/gpx+xml")}

# ---- 主流程 ----
data = {"buffer_meters": "0", "min_zoom": "10", "max_zoom": "10",
        "concurrency": "2", "interval_ms": "0"}
r = c.post("/api/submit", files=files, data=data)
assert r.status_code == 200, r.text
tid = r.json()["task_id"]
print("submit ok, task_id:", tid)

s = None
for _ in range(600):
    s = c.get("/api/status/" + tid).json()
    if s["status"] in ("completed", "failed", "cancelled"):
        break
    time.sleep(0.25)
print("final:", s["status"], "dl=", s["downloaded"], "fail=", s["failed_tiles"])
assert s["status"] == "completed", s
assert s["downloaded"] >= 1 and s["failed_tiles"] == 0, s

r = c.get("/api/download/" + tid)
assert r.status_code == 200, r.text
body = r.content
assert body[:16] == b"SQLite format 3\x00", body[:16]
with open("smoke_out.mbtiles", "wb") as f:
    f.write(body)
print("download ok, bytes:", len(body))

conn = sqlite3.connect("smoke_out.mbtiles")
meta = dict(conn.execute("SELECT name, value FROM metadata").fetchall())
n = conn.execute("SELECT count(*) FROM tiles").fetchone()[0]
blob = conn.execute("SELECT tile_data FROM tiles LIMIT 1").fetchone()[0]
conn.close()
assert blob[:8] == bytes.fromhex("89504e470d0a1a0a"), "tile blob not PNG"
assert "type" not in meta and meta["minzoom"] == "10" and meta["maxzoom"] == "10"
assert len(meta["bounds"].split(",")) == 4
print("mbtiles verify ok: tiles=", n, "bounds=", meta["bounds"], "name=", meta["name"])

# ---- 前端页面 ----
r = c.get("/")
assert r.status_code == 200 and "GPX" in r.text and "submitBtn" in r.text
print("frontend page ok")

# ---- 取消流程 ----
data2 = {"buffer_meters": "10000", "min_zoom": "14", "max_zoom": "14",
         "concurrency": "2", "interval_ms": "0"}
r = c.post("/api/submit", files=files, data=data2)
assert r.status_code == 200, r.text
tid2 = r.json()["task_id"]
time.sleep(1.5)  # 等它进入下载阶段
st = c.get("/api/status/" + tid2).json()
print("task2 mid status:", st["status"], "dl=", st["downloaded"], "total=", st["total_tiles"])
r = c.post("/api/cancel/" + tid2)
assert r.status_code == 200, r.text
s2 = c.get("/api/status/" + tid2).json()
print("after cancel:", s2["status"])
assert s2["status"] == "cancelled", s2

# 下载未完成任务的成品应被拒
r = c.get("/api/download/" + tid2)
assert r.status_code in (404, 409, 410), r.status_code
print("download-after-cancel correctly rejected:", r.status_code)

print("SMOKE ALL PASS")
