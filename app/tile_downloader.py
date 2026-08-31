import asyncio
import logging
import time

import aiohttp

logger = logging.getLogger("gpx2mbtiles.tile_downloader")


class TileHttpError(Exception):
    def __init__(self, status: int, body: bytes):
        super().__init__(f"tile http error {status}")
        self.status = status
        self.body = body


class TileBlocked(TileHttpError):
    """403/429 封禁类响应。"""


class TileFetcher:
    """真实瓦片下载器：带 UA 伪装、Referer、代理与超时。"""

    def __init__(self, settings):
        self._settings = settings
        self._session = None
        self._subdomain_idx = 0

    async def open(self):
        headers = {
            "User-Agent": self._settings.user_agent,
            "Referer": self._settings.referer,
            "Accept": "image/avif,image/webp,image/png,*/*",
        }
        timeout = aiohttp.ClientTimeout(
            total=self._settings.tile_timeout_seconds,
            connect=self._settings.tile_timeout_seconds,
        )
        self._session = aiohttp.ClientSession(
            headers=headers, timeout=timeout, proxy=self._settings.tile_proxy)

    async def close(self):
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def fetch(self, z: int, x: int, y: int) -> bytes:
        if self._session is None:
            raise RuntimeError("TileFetcher session not opened")
        template = self._settings.tile_url_template
        subdomains = getattr(self._settings, "tile_subdomains", ())
        if "{s}" in template and subdomains:
            s = subdomains[self._subdomain_idx % len(subdomains)]
            self._subdomain_idx += 1
            url = template.format(z=z, x=x, y=y, s=s)
        else:
            url = template.format(z=z, x=x, y=y)
        async with self._session.get(url) as resp:
            status = resp.status
            body = await resp.read()
            if status in (403, 429):
                raise TileBlocked(status=status, body=body)
            if status != 200:
                raise TileHttpError(status=status, body=body)
            if not body:
                raise TileHttpError(status=200, body=b"empty tile body")
            return body


class BlockWatcher:
    """统计 403/429：连续超阈值或占比超阈值即判定封禁。"""

    def __init__(self, pause_seconds, fail_min_count, fail_ratio, consecutive_threshold):
        self.pause_seconds = pause_seconds
        self.fail_min_count = fail_min_count
        self.fail_ratio = fail_ratio
        self.consecutive_threshold = consecutive_threshold
        self.total_ok = 0
        self.total_blocked = 0
        self.consecutive_blocked = 0
        self.pause_until = 0.0
        self.blocked = False

    def record_success(self):
        self.total_ok += 1
        self.consecutive_blocked = 0

    def record_failure(self):
        self.total_ok += 1
        self.consecutive_blocked = 0

    def record_blocked(self):
        self.total_blocked += 1
        self.consecutive_blocked += 1
        self.pause_until = time.monotonic() + self.pause_seconds
        processed = self.total_ok + self.total_blocked
        if self.consecutive_blocked >= self.consecutive_threshold:
            self.blocked = True
        elif (self.total_blocked >= self.fail_min_count
              and processed > 0
              and self.total_blocked / processed >= self.fail_ratio):
            self.blocked = True

    def wait_if_paused(self) -> float:
        return max(0.0, self.pause_until - time.monotonic())


class RateLimiter:
    """全局请求间隔限制：任意两个请求开始时间至少间隔 interval 秒。"""

    def __init__(self, interval_seconds: float):
        self.interval = interval_seconds
        self._lock = asyncio.Lock()
        self._next_allowed = 0.0

    async def wait(self):
        async with self._lock:
            now = time.monotonic()
            delay = self._next_allowed - now
            if delay > 0:
                await asyncio.sleep(delay)
            self._next_allowed = time.monotonic() + self.interval


class DownloadResult:
    def __init__(self, total: int):
        self.total = total
        self.succeeded = 0
        self.failed = 0
        self.blocked_failures = 0
        self.cancelled = False
        self.error = None


async def _fetch_with_retry(z, x, y, fetch_tile, limiter, watcher,
                            settings, cancel_event: asyncio.Event):
    """单瓦片下载：限流等待、重试、指数退避；返回 bytes 或 None(取消)。"""
    last_error = None
    for attempt in range(settings.retry_max + 1):
        if cancel_event.is_set():
            return None
        pause = watcher.wait_if_paused()
        if pause > 0:
            await asyncio.sleep(pause)
        if cancel_event.is_set():
            return None
        await limiter.wait()
        if cancel_event.is_set():
            return None
        try:
            return await fetch_tile(z, x, y)
        except TileBlocked as exc:
            raise exc
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            last_error = exc
            retryable = isinstance(exc, aiohttp.ClientError) or (
                isinstance(exc, TileHttpError) and exc.status >= 500)
            if not retryable and isinstance(exc, TileHttpError):
                raise exc
            if attempt < settings.retry_max:
                delay = settings.retry_backoff_base * (2 ** attempt)
                await asyncio.sleep(delay)
                continue
            raise last_error
    raise last_error or RuntimeError("tile fetch failed")


async def download_tiles(tiles, fetch_tile, on_tile_success, on_tile_failed,
                         settings, cancel_event: asyncio.Event) -> DownloadResult:
    """并发下载瓦片：限流、重试、指数退避、403/429 封禁检测、支持取消。"""
    result = DownloadResult(total=len(tiles))
    if not tiles:
        return result

    limiter = RateLimiter(settings.request_interval_ms / 1000.0)
    watcher = BlockWatcher(
        pause_seconds=settings.block_pause_seconds,
        fail_min_count=settings.block_fail_min_count,
        fail_ratio=settings.block_fail_ratio,
        consecutive_threshold=settings.block_consecutive_threshold,
    )
    queue = asyncio.Queue(maxsize=settings.max_concurrency * 4)
    stop_event = asyncio.Event()
    producer_done = asyncio.Event()

    async def worker():
        while not stop_event.is_set():
            try:
                item = queue.get_nowait()
            except asyncio.QueueEmpty:
                if producer_done.is_set():
                    return
                await asyncio.sleep(0.005)
                continue
            z, x, y = item
            try:
                data = await _fetch_with_retry(z, x, y, fetch_tile, limiter,
                                               watcher, settings, cancel_event)
                if data is None:
                    queue.task_done()
                    if cancel_event.is_set():
                        stop_event.set()
                    continue
                result.succeeded += 1
                watcher.record_success()
                await on_tile_success(z, x, y, data)
            except asyncio.CancelledError:
                queue.task_done()
                raise
            except TileBlocked:
                result.failed += 1
                result.blocked_failures += 1
                watcher.record_blocked()
                await on_tile_failed(z, x, y, "403/429 封禁")
                if watcher.blocked:
                    stop_event.set()
            except Exception as exc:
                result.failed += 1
                watcher.record_failure()
                await on_tile_failed(z, x, y, f"{type(exc).__name__}: {exc}")
            queue.task_done()
            if cancel_event.is_set():
                stop_event.set()

    async def producer():
        for tile in tiles:
            if stop_event.is_set() or cancel_event.is_set():
                break
            await queue.put(tile)
        producer_done.set()

    async def watcher_loop():
        while not stop_event.is_set() and not cancel_event.is_set():
            if watcher.blocked:
                stop_event.set()
                break
            pause = watcher.wait_if_paused()
            if pause > 0:
                await asyncio.sleep(min(pause, 0.5))
            else:
                await asyncio.sleep(0.2)

    worker_tasks = [asyncio.create_task(worker())
                    for _ in range(settings.max_concurrency)]
    producer_task = asyncio.create_task(producer())
    watcher_task = asyncio.create_task(watcher_loop())
    try:
        await producer_task
        await asyncio.gather(*worker_tasks, return_exceptions=True)
    except asyncio.CancelledError:
        # 外层被取消（如任务超时）：终止所有内部任务，防止悬挂
        stop_event.set()
        watcher_task.cancel()
        producer_task.cancel()
        for t in worker_tasks:
            t.cancel()
        await asyncio.gather(*worker_tasks, return_exceptions=True)
        await asyncio.gather(producer_task, return_exceptions=True)
        raise
    watcher_task.cancel()
    try:
        await watcher_task
    except asyncio.CancelledError:
        pass

    if cancel_event.is_set():
        result.cancelled = True
    if watcher.blocked and not result.cancelled:
        result.error = (
            f"瓦片源返回大量 403/429（{result.blocked_failures} 次），"
            "服务器出口 IP 可能已被瓦片源封禁，任务已终止")
    return result
