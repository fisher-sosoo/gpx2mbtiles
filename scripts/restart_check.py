import os
import signal
import socket
import subprocess
import sys
import time

import httpx

BASE = "http://127.0.0.1:18099"
PROJECT = "/Users/n22008/Projects/gpx2mbtiles"
VENV_PY = f"{PROJECT}/.venv/bin/python"
TILE_SLOW = "http://127.0.0.1:18199/tiles/{z}/{x}/{y}.png"


def wait_http(timeout=30.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            r = httpx.get(BASE + "/api/health", timeout=2)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


def port_free(port=18099):
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def start_uvicorn():
    env = os.environ.copy()
    env.update({
        "DATA_DIR": "./restart_data",
        "TILE_URL_TEMPLATE": TILE_SLOW,
        "REQUEST_INTERVAL_MS": "0",
        "MAX_CONCURRENCY": "2",
        "MAX_RUNNING_TASKS": "2",
        "TILE_TIMEOUT_SECONDS": "10",
        "TASK_TIMEOUT_SECONDS": "600",
    })
    log = open(f"{PROJECT}/restart_uvicorn.log", "ab")
    p = subprocess.Popen(
        [VENV_PY, "-m", "uvicorn", "app.main:app", "--port", "18099",
         "--log-level", "warning"],
        cwd=PROJECT, env=env, stdout=log, stderr=log, start_new_session=True)
    return p


def main():
    assert wait_http(30), "initial server not ready"
    c = httpx.Client(base_url=BASE, timeout=30)

    with open("/Users/n22008/Downloads/2025-12-10 上雨崩-冰湖切尼色-下雨崩.gpx", "rb") as f:
        gpx = f.read()
    files = {"file": ("yubeng.gpx", gpx, "application/gpx+xml")}
    data = {"buffer_meters": "500", "min_zoom": "12", "max_zoom": "16",
            "concurrency": "2", "interval_ms": "0"}
    r = c.post("/api/submit", files=files, data=data)
    assert r.status_code == 200, r.text
    tid = r.json()["task_id"]
    print("submitted:", tid)

    # 等进入下载阶段（500m/12-16 有 94 片，50ms/片 → 至少跑几秒）
    for _ in range(200):
        s = c.get("/api/status/" + tid).json()
        if s["status"] == "downloading":
            break
        time.sleep(0.2)
    print("mid status:", s["status"], "dl:", s["downloaded"], "/", s["total_tiles"])
    assert s["status"] == "downloading"

    # ---- 硬杀 uvicorn（模拟服务器断电/崩溃，非优雅退出） ----
    print("killing uvicorn (hard)...")
    kill = subprocess.run(
        ["pkill", "-9", "-f", "uvicorn app.main:app --port 18099"],
        capture_output=True)
    print("pkill rc:", kill.returncode)
    for _ in range(100):
        if port_free():
            break
        time.sleep(0.1)
    assert port_free(), "port still bound after kill"
    # 确认 DB 里任务还是 downloading（未优雅收尾）
    import sqlite3
    conn = sqlite3.connect(f"{PROJECT}/restart_data/tasks.db")
    st = conn.execute("SELECT status FROM tasks WHERE id=?", (tid,)).fetchone()[0]
    conn.close()
    print("db status after crash:", st)
    assert st == "downloading", f"unexpected db status {st}"

    # ---- 重启服务 ----
    print("restarting uvicorn...")
    start_uvicorn()
    assert wait_http(30), "restarted server not ready"
    c2 = httpx.Client(base_url=BASE, timeout=30)

    # ---- 轮询到任务续跑完成 ----
    s = None
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        s = c2.get("/api/status/" + tid).json()
        if s["status"] in ("completed", "failed", "cancelled"):
            break
        time.sleep(0.5)
    print("resumed final:", s["status"], "dl:", s["downloaded"], "/", s["total_tiles"],
          "fail:", s["failed_tiles"])
    assert s["status"] == "completed", s
    assert s["downloaded"] == 94 and s["failed_tiles"] == 0, s

    # 成品可下载且完整
    r = c2.get("/api/download/" + tid, timeout=30)
    assert r.status_code == 200
    assert len(r.content) > 0 and r.content[:16] == b"SQLite format 3\x00"
    print("RESTART-PERSISTENCE PASS (resumed after hard crash)")


if __name__ == "__main__":
    main()
