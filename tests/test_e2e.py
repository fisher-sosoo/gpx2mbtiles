import asyncio
import sqlite3

import pytest

from app.task_manager import (CANCELLED, COMPLETED, DOWNLOADING, FAILED,
                              QUEUED)
from tests.conftest import SERVER_BEHAVIOR, make_gpx


async def _poll_status(client, task_id, timeout=40.0):
    import time
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        resp = await client.get(f"/api/status/{task_id}")
        assert resp.status_code == 200
        s = resp.json()
        if s["status"] in (COMPLETED, FAILED, CANCELLED):
            return s
        await asyncio.sleep(0.1)
    raise TimeoutError(f"task {task_id} not finished in {timeout}s")


async def _submit(client, points=None, buffer=0, min_zoom=10, max_zoom=10,
                  concurrency=2, interval_ms=0, filename="t.gpx",
                  output_format="mbtiles"):
    gpx = make_gpx(points or [(39.9, 116.4)])
    files = {"file": (filename, gpx.encode(), "application/gpx+xml")}
    data = {
        "buffer_meters": str(buffer),
        "min_zoom": str(min_zoom),
        "max_zoom": str(max_zoom),
        "concurrency": str(concurrency),
        "interval_ms": str(interval_ms),
        "output_format": output_format,
    }
    return await client.post("/api/submit", files=files, data=data)


async def test_health(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_submit_rejects_wrong_extension(client):
    resp = await _submit(client, filename="t.txt")
    assert resp.status_code == 400


async def test_submit_rejects_invalid_gpx(client):
    files = {"file": ("t.gpx", b"not a gpx file", "application/gpx+xml")}
    data = {"buffer_meters": "0", "min_zoom": "10", "max_zoom": "10",
            "concurrency": "1", "interval_ms": "0"}
    resp = await client.post("/api/submit", files=files, data=data)
    assert resp.status_code == 400
    assert "解析失败" in resp.json()["detail"]


async def test_submit_rejects_empty_gpx(client):
    files = {"file": ("t.gpx", b"   ", "application/gpx+xml")}
    data = {"buffer_meters": "0", "min_zoom": "10", "max_zoom": "10",
            "concurrency": "1", "interval_ms": "0"}
    resp = await client.post("/api/submit", files=files, data=data)
    assert resp.status_code == 400


async def test_status_404(client):
    resp = await client.get("/api/status/deadbeef")
    assert resp.status_code == 404


async def test_full_flow_success(client):
    """上传 → 下载 → 完成 → 下载 mbtiles 且为合法 SQLite。"""
    resp = await _submit(client)
    assert resp.status_code == 200
    task_id = resp.json()["task_id"]
    assert len(task_id) == 32  # uuid hex

    s = await _poll_status(client, task_id)
    assert s["status"] == COMPLETED
    assert s["total_tiles"] == 1
    assert s["downloaded"] == 1
    assert s["failed_tiles"] == 0
    assert s["download_url"] == f"/api/download/{task_id}"

    dl = await client.get(f"/api/download/{task_id}")
    assert dl.status_code == 200
    body = dl.content
    assert body[:16] == b"SQLite format 3\x00"
    import tempfile, os
    fd, path = tempfile.mkstemp(suffix=".mbtiles")
    os.close(fd)
    with open(path, "wb") as f:
        f.write(body)
    try:
        conn = sqlite3.connect(path)
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"tiles", "metadata"} <= tables
        meta = dict(conn.execute("SELECT name, value FROM metadata").fetchall())
        assert "type" not in meta
        assert meta["format"] == "png"
        assert meta["minzoom"] == "10" and meta["maxzoom"] == "10"
        assert len(meta["bounds"].split(",")) == 4
        rows = conn.execute("SELECT count(*) FROM tiles").fetchone()[0]
        assert rows == 1
        conn.close()
    finally:
        os.unlink(path)


async def test_full_flow_gpkg_success(client):
    """默认/显式 gpkg：完成 → 下载 .gpkg 且符合 GeoPackage 规范。"""
    resp = await _submit(client, output_format="gpkg")
    assert resp.status_code == 200
    task_id = resp.json()["task_id"]

    s = await _poll_status(client, task_id)
    assert s["status"] == COMPLETED
    assert s["output_format"] == "gpkg"
    assert s["file_name"].endswith(".gpkg")
    assert s["download_url"] == f"/api/download/{task_id}"

    dl = await client.get(f"/api/download/{task_id}")
    assert dl.status_code == 200
    body = dl.content
    assert body[:16] == b"SQLite format 3\x00"
    assert "attachment" in dl.headers.get("content-disposition", "")
    import tempfile, os
    fd, path = tempfile.mkstemp(suffix=".gpkg")
    os.close(fd)
    with open(path, "wb") as f:
        f.write(body)
    try:
        conn = sqlite3.connect(path)
        app_id = conn.execute("PRAGMA application_id").fetchone()[0]
        assert app_id == 0x47504B47, hex(app_id)
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"gpkg_contents", "gpkg_spatial_ref_sys",
                "gpkg_tile_matrix_set", "gpkg_tile_matrix", "tiles"} <= tables
        # srs 3857 已注册
        srs = conn.execute(
            "SELECT srs_id, organization, organization_coordsys_id"
            " FROM gpkg_spatial_ref_sys").fetchone()
        assert srs[0] == 3857 and srs[1] == "EPSG" and srs[2] == 3857
        # contents 指向 tiles 表且 data_type=tiles
        row = conn.execute(
            "SELECT data_type, srs_id FROM gpkg_contents WHERE table_name='tiles'").fetchone()
        assert row == ("tiles", 3857)
        # 瓦片金字塔覆盖 zoom 10
        mats = {r[0] for r in conn.execute(
            "SELECT zoom_level FROM gpkg_tile_matrix").fetchall()}
        assert 10 in mats
        n = conn.execute("SELECT count(*) FROM tiles").fetchone()[0]
        assert n == 1
        # 下载到的瓦片 blob 是 PNG
        blob = conn.execute("SELECT tile_data FROM tiles LIMIT 1").fetchone()[0]
        assert blob[:8] == bytes.fromhex("89504e470d0a1a0a")
        conn.close()
    finally:
        os.unlink(path)


async def test_submit_rejects_bad_output_format(client):
    files = {"file": ("t.gpx", make_gpx([(39.9, 116.4)]).encode(), "application/gpx+xml")}
    data = {"buffer_meters": "0", "min_zoom": "10", "max_zoom": "10",
            "concurrency": "1", "interval_ms": "0", "output_format": "exe"}
    resp = await client.post("/api/submit", files=files, data=data)
    assert resp.status_code == 400
    assert "output_format" in resp.json()["detail"]


async def test_retry_on_transient_500(client):
    """前 1 个请求 500，重试后成功完成。"""
    SERVER_BEHAVIOR["fail_first_n"] = 1
    resp = await _submit(client)
    assert resp.status_code == 200
    s = await _poll_status(client, resp.json()["task_id"])
    assert s["status"] == COMPLETED
    assert s["downloaded"] == 1
    assert s["failed_tiles"] == 0


async def test_download_conflict_while_running(client):
    """任务未完成时下载返回 409。"""
    SERVER_BEHAVIOR["slow_seconds"] = 0.2
    resp = await _submit(client, buffer=10000, min_zoom=12, max_zoom=12,
                         concurrency=1)
    assert resp.status_code == 200
    task_id = resp.json()["task_id"]
    # 等它进入下载阶段
    for _ in range(100):
        s = (await client.get(f"/api/status/{task_id}")).json()
        if s["status"] == DOWNLOADING:
            break
        await asyncio.sleep(0.05)
    dl = await client.get(f"/api/download/{task_id}")
    assert dl.status_code == 409
    # 收尾：取消，避免测试悬挂
    await client.post(f"/api/cancel/{task_id}")
    await _poll_status(client, task_id)


async def test_cancel_downloading(client, settings, monkeypatch):
    """下载中取消 → 状态 cancelled，临时文件清理。"""
    SERVER_BEHAVIOR["slow_seconds"] = 0.05
    resp = await _submit(client, buffer=10000, min_zoom=13, max_zoom=13,
                         concurrency=2)
    assert resp.status_code == 200
    task_id = resp.json()["task_id"]
    for _ in range(200):
        s = (await client.get(f"/api/status/{task_id}")).json()
        if s["status"] == DOWNLOADING:
            break
        await asyncio.sleep(0.05)
    assert s["status"] == DOWNLOADING

    cancel = await client.post(f"/api/cancel/{task_id}")
    assert cancel.status_code == 200

    s = await _poll_status(client, task_id)
    assert s["status"] == CANCELLED

    # 临时文件已清理
    from pathlib import Path
    task_dir = Path(settings.data_dir) / "tasks" / task_id
    assert not (task_dir / "input.gpx").exists()
    assert not (task_dir / "work.mbtiles").exists()
    assert not (task_dir / f"{task_id}.mbtiles").exists()


async def test_blocked_403_fails(client):
    """全部 403 → 封禁判定 → 任务失败。"""
    SERVER_BEHAVIOR["status_override"] = 403
    resp = await _submit(client, buffer=8000, min_zoom=12, max_zoom=12,
                         concurrency=4)
    assert resp.status_code == 200
    s = await _poll_status(client, resp.json()["task_id"], timeout=60)
    assert s["status"] == FAILED
    assert "403/429" in s["error"]
    assert s["blocked_count"] > 0
    # 失败任务不可下载
    dl = await client.get(f"/api/download/{resp.json()['task_id']}")
    assert dl.status_code == 409


async def test_concurrent_task_limit(client):
    """同时运行任务数达上限时，第 3 个任务返回 429。"""
    SERVER_BEHAVIOR["slow_seconds"] = 0.15
    r1 = await _submit(client, buffer=8000, min_zoom=12, max_zoom=12, concurrency=1)
    r2 = await _submit(client, buffer=8000, min_zoom=12, max_zoom=12, concurrency=1)
    assert r1.status_code == 200 and r2.status_code == 200
    t1, t2 = r1.json()["task_id"], r2.json()["task_id"]
    # 等两个任务都进入运行状态
    for _ in range(200):
        s1 = (await client.get(f"/api/status/{t1}")).json()
        s2 = (await client.get(f"/api/status/{t2}")).json()
        if s1["status"] in (DOWNLOADING,) and s2["status"] in (DOWNLOADING,):
            break
        await asyncio.sleep(0.05)
    r3 = await _submit(client, buffer=8000, min_zoom=12, max_zoom=12, concurrency=1)
    assert r3.status_code == 429
    # 清理
    await client.post(f"/api/cancel/{t1}")
    await client.post(f"/api/cancel/{t2}")
    await _poll_status(client, t1)
    await _poll_status(client, t2)


async def test_estimate_endpoint(client):
    """/api/estimate 返回瓦片数与超限标记，且不创建任务。"""
    import app.main as main_mod
    gpx = make_gpx([(39.9, 116.4)])
    files = {"file": ("t.gpx", gpx.encode(), "application/gpx+xml")}
    data = {"buffer_meters": "2500", "min_zoom": "8", "max_zoom": "17"}
    resp = await client.post("/api/estimate", files=files, data=data)
    assert resp.status_code == 200
    j = resp.json()
    assert j["tiles"] > 0
    assert j["point_count"] == 1
    assert "exceeds_limit" in j and isinstance(j["exceeds_limit"], bool)
    # 不创建任务
    tasks = (await client.get("/api/tasks")).json()["tasks"]
    assert tasks == []


async def test_oversize_allowed_with_flag(client, monkeypatch):
    """瓦片数超上限时 allow_oversize=true 放行。"""
    import app.main as main_mod
    monkeypatch.setattr(main_mod.settings, "max_tiles_per_task", 1)
    resp = await _submit(client, buffer=2500, min_zoom=8, max_zoom=10,
                         output_format="mbtiles")
    # 未放行：任务最终失败（超上限）
    assert resp.status_code == 200
    s = await _poll_status(client, resp.json()["task_id"])
    assert s["status"] == FAILED
    assert "上限" in s["error"]

    # 放行后成功
    gpx = make_gpx([(39.9, 116.4)])
    files = {"file": ("t.gpx", gpx.encode(), "application/gpx+xml")}
    data = {"buffer_meters": "2500", "min_zoom": "8", "max_zoom": "10",
            "concurrency": "1", "interval_ms": "0", "output_format": "mbtiles",
            "allow_oversize": "true"}
    resp2 = await client.post("/api/submit", files=files, data=data)
    assert resp2.status_code == 200
    s2 = await _poll_status(client, resp2.json()["task_id"])
    assert s2["status"] == COMPLETED
    assert s2["total_tiles"] > 1


async def test_history_list_and_manual_delete(client, settings):
    """历史保留：完成任务留在 /api/tasks，DELETE 后移除记录与文件。"""
    from pathlib import Path
    resp = await _submit(client, output_format="mbtiles")
    assert resp.status_code == 200
    task_id = resp.json()["task_id"]
    s = await _poll_status(client, task_id)
    assert s["status"] == COMPLETED

    # 出现在历史列表
    tasks = (await client.get("/api/tasks")).json()["tasks"]
    ids = [t["task_id"] for t in tasks]
    assert task_id in ids
    item = next(t for t in tasks if t["task_id"] == task_id)
    assert item["file_available"] is True

    # 手动删除
    resp = await client.delete(f"/api/tasks/{task_id}")
    assert resp.status_code == 200
    tasks = (await client.get("/api/tasks")).json()["tasks"]
    assert task_id not in [t["task_id"] for t in tasks]
    task_dir = Path(settings.data_dir) / "tasks" / task_id
    assert not task_dir.exists()

    # 删除不存在的任务 404
    resp = await client.delete(f"/api/tasks/{task_id}")
    assert resp.status_code == 404


async def test_task_timeout_fails_and_cleans(client, settings, monkeypatch):
    """任务超过最大运行时间 → 标记失败并清理临时文件。"""
    import app.main as main_mod
    monkeypatch.setattr(main_mod.settings, "task_timeout_seconds", 2)
    SERVER_BEHAVIOR["slow_seconds"] = 0.1
    # 足够多瓦片 + 单并发，确保 2 秒内跑不完
    resp = await _submit(client, buffer=10000, min_zoom=13, max_zoom=13,
                         concurrency=1)
    assert resp.status_code == 200
    task_id = resp.json()["task_id"]
    s = await _poll_status(client, task_id, timeout=40)
    assert s["status"] == FAILED
    assert "超过最大运行时间" in s["error"], s["error"]
    # 临时文件已清理
    from pathlib import Path
    task_dir = Path(settings.data_dir) / "tasks" / task_id
    assert not (task_dir / "input.gpx").exists()
    assert not (task_dir / "work.mbtiles").exists()
    assert not (task_dir / f"{task_id}.mbtiles").exists()


async def test_auth_token_enforced(client):
    """配置 AUTH_TOKEN 后：无 Key 返回 401，正确 Key 放行。"""
    import app.main as main_mod
    old = main_mod.settings.auth_token
    main_mod.settings.auth_token = "sekrit-key"
    try:
        r = await client.get("/api/health")
        assert r.status_code == 200  # health 不受限
        r = await client.get("/api/status/deadbeef")
        assert r.status_code == 401
        r = await client.get("/api/status/deadbeef",
                             headers={"X-API-Key": "sekrit-key"})
        assert r.status_code == 404  # 鉴权通过后才是任务不存在
    finally:
        main_mod.settings.auth_token = old


async def test_invalid_params_rejected(client):
    """min_zoom > max_zoom 提交后任务失败（服务端校验）。"""
    resp = await _submit(client, min_zoom=14, max_zoom=10)
    assert resp.status_code == 200
    s = await _poll_status(client, resp.json()["task_id"])
    assert s["status"] == FAILED
    assert "缩放" in s["error"] or "不能大于" in s["error"]

# ---------------------------------------------------------------- KML 转换

async def test_convert_endpoint_real_sample(client):
    """/api/convert：真实样本 → 带名称的 GPX + 摘要。"""
    from tests.conftest import sample_kml_bytes
    files = {"file": ("2023-02-18 英德雪山嶂环线.kml",
                      sample_kml_bytes(), "application/vnd.google-earth.kml+xml")}
    resp = await client.post("/api/convert", files=files,
                             data={"track_name": ""})
    assert resp.status_code == 200
    j = resp.json()
    s = j["summary"]
    assert s["tracks"][0]["name"] == "英德雪山嶂环线 2023-02-18 爬山"
    assert s["waypoint_count"] == 30
    assert len(s["waypoints"]) == 30
    assert s["name_sources"]["position"] == 30
    assert j["filename"].endswith(".gpx")
    assert "<gpx" in j["gpx"]
    assert "#01 " in j["gpx"]


async def test_convert_custom_track_name(client):
    from tests.conftest import sample_kml_bytes
    files = {"file": ("x.kml", sample_kml_bytes(),
                      "application/vnd.google-earth.kml+xml")}
    resp = await client.post("/api/convert", files=files,
                             data={"track_name": "我的环线"})
    assert resp.status_code == 200
    j = resp.json()
    assert j["summary"]["tracks"][0]["name"] == "我的环线"
    assert j["filename"] == "我的环线.gpx"


async def test_convert_from_text(client):
    from tests.conftest import make_kml
    kml = make_kml(track_times=[(113.0, 24.0, 1, "2023-02-18T02:00:00Z"),
                                (113.1, 24.1, 2, "2023-02-18T02:10:00Z")],
                   doc_name="2023-02-18 测试线")
    resp = await client.post("/api/convert",
                             data={"text": kml, "filename": "a.kml"})
    assert resp.status_code == 200
    assert resp.json()["summary"]["tracks"][0]["points"] == 2


async def test_convert_rejects_bad_input(client):
    resp = await client.post("/api/convert", data={"text": "not xml"})
    assert resp.status_code == 400
    assert "解析失败" in resp.json()["detail"]

    resp = await client.post("/api/convert", data={"text": "<gpx/>"})
    assert resp.status_code == 400
    assert "KML" in resp.json()["detail"]


async def test_convert_requires_target(client):
    resp = await client.post("/api/convert", data={"text": "   "})
    assert resp.status_code == 400


async def test_convert_does_not_create_task(client):
    from tests.conftest import make_kml
    kml = make_kml(track_times=[(113.0, 24.0, 1, "2023-02-18T02:00:00Z"),
                                (113.1, 24.1, 2, "2023-02-18T02:10:00Z")])
    await client.post("/api/convert", data={"text": kml})
    tasks = (await client.get("/api/tasks")).json()["tasks"]
    assert tasks == []


async def test_estimate_accepts_kml(client):
    from tests.conftest import make_kml
    kml = make_kml(track_times=[(113.0, 24.0, 1, "2023-02-18T02:00:00Z"),
                                (113.1, 24.1, 2, "2023-02-18T02:10:00Z")])
    files = {"file": ("t.kml", kml.encode(), "application/vnd.google-earth.kml+xml")}
    data = {"buffer_meters": "0", "min_zoom": "10", "max_zoom": "10"}
    resp = await client.post("/api/estimate", files=files, data=data)
    assert resp.status_code == 200
    j = resp.json()
    assert j["point_count"] == 2
    assert j["tiles"] >= 1
    tasks = (await client.get("/api/tasks")).json()["tasks"]
    assert tasks == []


async def test_submit_accepts_kml(client):
    """KML 直接提交也能完成任务（服务端先转换再取点）。"""
    from tests.conftest import make_kml
    kml = make_kml(track_times=[(113.0, 24.0, 1, "2023-02-18T02:00:00Z"),
                                (113.1, 24.1, 2, "2023-02-18T02:10:00Z")],
                   doc_name="2023-02-18 测试线")
    files = {"file": ("t.kml", kml.encode(), "application/vnd.google-earth.kml+xml")}
    data = {"buffer_meters": "0", "min_zoom": "10", "max_zoom": "10",
            "concurrency": "1", "interval_ms": "0", "output_format": "mbtiles"}
    resp = await client.post("/api/submit", files=files, data=data)
    assert resp.status_code == 200
    s = await _poll_status(client, resp.json()["task_id"])
    assert s["status"] == COMPLETED
    assert s["total_tiles"] >= 1


# ---------------------------------------------------------------- 项目空间

def _sample_kml():
    from tests.conftest import make_kml
    return make_kml(track_times=[
        (113.0, 24.0, 100, "2023-02-18T02:00:00Z"),
        (113.01, 24.01, 200, "2023-02-18T02:30:00Z"),
        (113.02, 24.02, 300, "2023-02-18T03:00:00Z")],
        doc_name="2023-02-18 测试环线")


async def test_convert_saves_project(client):
    """每次转换都落成项目，返回 project_id。"""
    kml = _sample_kml()
    resp = await client.post("/api/convert",
                             files={"file": ("x.kml", kml.encode(), "application/xml")})
    assert resp.status_code == 200
    pid = resp.json()["project_id"]
    assert len(pid) == 32

    lst = (await client.get("/api/projects")).json()
    assert lst["total"] == 1
    assert lst["items"][0]["id"] == pid
    assert lst["items"][0]["status"] == "completed"


async def test_project_detail_and_gpx(client):
    kml = _sample_kml()
    pid = (await client.post("/api/convert",
            files={"file": ("x.kml", kml.encode(), "application/xml")})).json()["project_id"]
    d = (await client.get(f"/api/projects/{pid}")).json()
    assert d["point_count"] == 3
    assert d["summary"]["tracks"][0]["points"] == 3
    assert "<gpx" in d["gpx"]
    assert d["gpx_available"] is True
    assert d["input_available"] is True


async def test_project_delete(client, settings):
    from pathlib import Path
    kml = _sample_kml()
    pid = (await client.post("/api/convert",
            files={"file": ("x.kml", kml.encode(), "application/xml")})).json()["project_id"]
    d = Path(settings.data_dir) / "projects" / pid
    assert d.is_dir()
    r = await client.delete(f"/api/projects/{pid}")
    assert r.status_code == 200
    assert not d.exists()
    assert (await client.get(f"/api/projects/{pid}")).status_code == 404
    assert (await client.delete(f"/api/projects/{pid}")).status_code == 404


async def test_project_reconvert(client):
    """用保存的原件重转，生成新项目并保留旧项目。"""
    kml = _sample_kml()
    pid = (await client.post("/api/convert",
            files={"file": ("x.kml", kml.encode(), "application/xml")})).json()["project_id"]
    r = await client.post(f"/api/projects/{pid}/reconvert",
                          data={"track_name": "改过的名字"})
    assert r.status_code == 200
    j = r.json()
    assert j["project_id"] != pid
    assert j["reconverted_from"] == pid
    assert j["summary"]["tracks"][0]["name"] == "改过的名字"
    lst = (await client.get("/api/projects")).json()
    assert lst["total"] == 2, "重转应保留旧项目"


async def test_project_export_handles_chinese_filename(client):
    """导出要能正确处理中文文件名（HTTP 头不能放非 latin-1 字符）。"""
    kml = _sample_kml()
    pid = (await client.post("/api/convert",
            files={"file": ("x.kml", kml.encode(), "application/xml")})).json()["project_id"]
    r = await client.get(f"/api/projects/{pid}/export")
    assert r.status_code == 200, r.text
    assert "<gpx" in r.text
    disp = r.headers.get("content-disposition", "")
    assert "filename*=UTF-8''" in disp, f"应使用 RFC5987 编码: {disp}"


async def test_project_export_merges_pois(client, settings):
    """有地名缓存时导出应把地名点并入，且不改动原轨迹点数。"""
    import json
    from pathlib import Path
    kml = _sample_kml()
    pid = (await client.post("/api/convert",
            files={"file": ("x.kml", kml.encode(), "application/xml")})).json()["project_id"]
    base = (await client.get(f"/api/projects/{pid}/export")).text
    base_trkpt = base.count("<trkpt")

    pois = {"items": [{"name": "测试垭口", "type_label": "垭口", "lat": 24.01,
                       "lon": 113.01, "ele": 200.0, "distance_m": 12.0}]}
    (Path(settings.data_dir) / "projects" / pid / "pois.json").write_text(
        json.dumps(pois, ensure_ascii=False), encoding="utf-8")

    merged = (await client.get(f"/api/projects/{pid}/export")).text
    assert "测试垭口" in merged
    assert merged.count("<trkpt") == base_trkpt, "轨迹点不能变"
    assert merged.count("<wpt") == base.count("<wpt") + 1


async def test_project_download(client):
    kml = _sample_kml()
    pid = (await client.post("/api/convert",
            files={"file": ("x.kml", kml.encode(), "application/xml")})).json()["project_id"]
    r = await client.get(f"/api/projects/{pid}/download")
    assert r.status_code == 200
    assert r.text.startswith("<?xml")
    assert "<gpx" in r.text


async def test_project_prune_by_limit(client, settings, monkeypatch):
    """超过条数上限时淘汰最旧的。"""
    import app.main as main_mod
    monkeypatch.setattr(main_mod.project_store.settings, "max_projects", 2)
    ids = []
    for i in range(4):
        kml = _sample_kml()
        r = await client.post("/api/convert",
                              files={"file": (f"x{i}.kml", kml.encode(), "application/xml")})
        ids.append(r.json()["project_id"])
    lst = (await client.get("/api/projects")).json()
    assert lst["total"] <= 2, f"应淘汰到上限内，实得 {lst['total']}"
    assert ids[-1] in [it["id"] for it in lst["items"]], "最新的必须保留"


async def test_projects_404(client):
    assert (await client.get("/api/projects/deadbeef")).status_code == 404
    assert (await client.get("/api/projects/deadbeef/download")).status_code == 404


class TestProjectStoreUnit:
    def test_save_and_read(self, settings):
        from app.project_store import ProjectStore
        from app.gpx_converter import convert
        from tests.conftest import make_kml
        store = ProjectStore(settings)
        kml = make_kml(track_times=[(113.0, 24.0, 1, "2023-02-18T02:00:00Z"),
                                    (113.1, 24.1, 2, "2023-02-18T02:10:00Z")],
                       doc_name="2023-02-18 T")
        res = convert(kml.encode(), "t.kml")
        meta = store.save(source_bytes=kml.encode(), source_name="t.kml",
                          ext=".kml", result=res, params={"ai_names": False})
        assert meta["status"] == "completed"
        got = store.get(meta["id"])
        assert got["summary"]["tracks"][0]["points"] == 2
    
    def test_missing_project_raises(self, settings):
        from app.project_store import ProjectNotFoundError, ProjectStore
        store = ProjectStore(settings)
        import pytest as _pytest
        with _pytest.raises(ProjectNotFoundError):
            store.get("nope")
