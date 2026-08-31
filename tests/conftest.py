import asyncio
import os
import threading
import time

import pytest
from aiohttp import web

# ---------------- 全局行为开关（测试用例通过 monkeypatch 修改） ----------------
SERVER_BEHAVIOR = {
    "status_override": None,  # 如 403：所有瓦片都返回该状态
    "slow_seconds": 0.0,      # 每个瓦片响应前的休眠秒数
    "fail_first_n": 0,        # 前 N 个请求返回 500（测试重试机制）
    "_request_count": 0,
}

PNG_1x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c6360000002000150cbe9ee0000000049454e44ae426082"
)


class FakeTileServer:
    def __init__(self):
        self.app = web.Application()
        self.app.router.add_get("/tiles/{z}/{x}/{y}.png", self._handle)
        self.app.router.add_get("/health", lambda r: web.Response(text="ok"))
        self._runner = None
        self.port = None

    async def _handle(self, request):
        behavior = SERVER_BEHAVIOR
        if behavior["slow_seconds"] > 0:
            await asyncio.sleep(behavior["slow_seconds"])
        status = behavior["status_override"]
        if status is not None:
            return web.Response(status=status, body=b"blocked")
        behavior["_request_count"] += 1
        if behavior["_request_count"] <= behavior["fail_first_n"]:
            return web.Response(status=500, body=b"transient failure")
        return web.Response(body=PNG_1x1, content_type="image/png")

    async def start(self):
        self._runner = web.AppRunner(self.app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]
        return f"http://127.0.0.1:{self.port}/tiles/{{z}}/{{x}}/{{y}}.png"

    async def stop(self):
        if self._runner is not None:
            await self._runner.cleanup()


@pytest.fixture(scope="session")
def tile_server_url():
    server = FakeTileServer()
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=_run_server, args=(loop, server), daemon=True)
    thread.start()
    for _ in range(500):
        if server.port is not None:
            break
        time.sleep(0.01)
    assert server.port is not None, "fake tile server failed to start"
    os.environ["TILE_URL_TEMPLATE"] = f"http://127.0.0.1:{server.port}/tiles/{{z}}/{{x}}/{{y}}.png"
    yield os.environ["TILE_URL_TEMPLATE"]
    # 守护线程随进程结束退出，无需显式停止


def _run_server(loop, server):
    loop.run_until_complete(server.start())
    loop.run_forever()


@pytest.fixture(autouse=True)
def _reset_behavior():
    SERVER_BEHAVIOR["status_override"] = None
    SERVER_BEHAVIOR["slow_seconds"] = 0.0
    SERVER_BEHAVIOR["fail_first_n"] = 0
    SERVER_BEHAVIOR["_request_count"] = 0
    yield
    SERVER_BEHAVIOR["status_override"] = None
    SERVER_BEHAVIOR["slow_seconds"] = 0.0
    SERVER_BEHAVIOR["fail_first_n"] = 0
    SERVER_BEHAVIOR["_request_count"] = 0


@pytest.fixture()
def settings(tmp_path, monkeypatch, tile_server_url):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MAX_RUNNING_TASKS", "2")
    monkeypatch.setenv("REQUEST_INTERVAL_MS", "0")
    monkeypatch.setenv("MAX_CONCURRENCY", "4")
    monkeypatch.setenv("RETRY_MAX", "1")
    monkeypatch.setenv("RETRY_BACKOFF_BASE", "0.01")
    monkeypatch.setenv("TASK_TIMEOUT_SECONDS", "120")
    monkeypatch.setenv("FILE_EXPIRY_SECONDS", "3600")
    monkeypatch.setenv("CLEANUP_INTERVAL_SECONDS", "3600")
    monkeypatch.setenv("BLOCK_PAUSE_SECONDS", "0.2")
    monkeypatch.setenv("BLOCK_FAIL_MIN_COUNT", "3")
    monkeypatch.setenv("BLOCK_FAIL_RATIO", "0.5")
    monkeypatch.setenv("BLOCK_CONSECUTIVE_THRESHOLD", "2")
    monkeypatch.setenv("MAX_TILES_PER_TASK", "50000")

    # 重新加载配置与 app（env 变化后重建缓存）
    from app import config
    import app.main as main_mod
    config._settings = None
    return config.get_settings()


@pytest.fixture()
async def app(settings, monkeypatch):
    import app.main as main_mod
    from app.task_manager import TaskManager

    monkeypatch.setattr(main_mod, "settings", settings)
    manager = TaskManager(settings)
    main_mod.manager = manager
    cleanup_task = asyncio.create_task(manager.cleanup_loop())
    yield main_mod.app
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    await manager.shutdown()


@pytest.fixture()
async def client(app):
    import httpx
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def make_gpx(points, name="test-track"):
    trkpts = "".join(
        f'<trkpt lat="{lat:.6f}" lon="{lon:.6f}"/>' for lat, lon in points)
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="pytest" xmlns="http://www.topografix.com/GPX/1/1">
  <trk><name>{name}</name><trkseg>{trkpts}</trkseg></trk>
</gpx>'''


def wait_task_done(manager, task_id, timeout=30.0):
    import time
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        t = manager.get(task_id)
        if t.status in ("completed", "failed", "cancelled"):
            return t
        time.sleep(0.05)
    raise TimeoutError(f"task {task_id} did not finish in {timeout}s")
