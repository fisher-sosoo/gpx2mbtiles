import asyncio
import json
import logging
import os
import shutil
import sqlite3
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path

from .config import Settings
from .gpx_processor import GpxParseError, build_tile_plan, parse_gpx
from .gpkg_builder import GpkgBuilder
from .mbtiles_builder import MbtilesBuilder
from .tile_downloader import TileFetcher, download_tiles

logger = logging.getLogger("gpx2mbtiles.manager")

# 任务状态
QUEUED = "queued"
DOWNLOADING = "downloading"
COMPLETED = "completed"
FAILED = "failed"
CANCELLED = "cancelled"


class TaskLimitError(Exception):
    pass


class TaskNotFoundError(Exception):
    pass


@dataclass
class Task:
    id: str
    status: str
    created_at: float
    updated_at: float
    name: str
    params: dict = field(default_factory=dict)
    total_tiles: int = 0
    downloaded: int = 0
    failed_tiles: int = 0
    min_zoom: int = 0
    max_zoom: int = 0
    point_count: int = 0
    bounds: list = field(default_factory=list)
    error: str = ""
    file_name: str = ""
    file_size: int = 0
    blocked_count: int = 0
    finished_at: float = 0.0
    can_download: bool = False
    failed_details: list = field(default_factory=list)  # 最近 200 条失败瓦片 (z,x,y,reason)
    output_format: str = "gpkg"  # gpkg | mbtiles
    tile_layer: str = "windy"  # windy | opentopomap

    def to_dict(self):
        return {
            "task_id": self.id,
            "file_available": (self.status == COMPLETED and self.can_download),
            "status": self.status,
            "name": self.name,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "finished_at": self.finished_at,
            "params": self.params,
            "total_tiles": self.total_tiles,
            "downloaded": self.downloaded,
            "failed_tiles": self.failed_tiles,
            "blocked_count": self.blocked_count,
            "min_zoom": self.min_zoom,
            "max_zoom": self.max_zoom,
            "point_count": self.point_count,
            "bounds": self.bounds,
            "error": self.error,
            "file_name": self.file_name,
            "file_size": self.file_size,
            "failed_details": self.failed_details,
            "output_format": self.output_format,
            "tile_layer": self.tile_layer,
            "download_url": f"/api/download/{self.id}" if self.status == COMPLETED else None,
        }


class TaskManager:
    """任务账本：内存 + SQLite 持久化，重启后可恢复并续跑。"""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._tasks: dict[str, Task] = {}
        self._running: dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()
        self._tasks_dir = Path(settings.data_dir) / "tasks"
        self._db_path = Path(settings.data_dir) / "tasks.db"
        self._tasks_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._load_tasks()
        self._cleanup_event = asyncio.Event()

    # ---------- 持久化 ----------
    def _conn(self):
        return sqlite3.connect(str(self._db_path))

    def _init_db(self):
        conn = self._conn()
        conn.execute(
            "CREATE TABLE IF NOT EXISTS tasks ("
            "id TEXT PRIMARY KEY, status TEXT, created_at REAL, updated_at REAL,"
            "finished_at REAL, name TEXT, params TEXT, total_tiles INTEGER,"
            "downloaded INTEGER, failed_tiles INTEGER, min_zoom INTEGER, max_zoom INTEGER,"
            "point_count INTEGER, bounds TEXT, error TEXT, file_name TEXT,"
            "file_size INTEGER, blocked_count INTEGER, failed_details TEXT,"
            "output_format TEXT DEFAULT 'mbtiles', tile_layer TEXT DEFAULT 'windy')"
        )
        conn.commit()
        conn.close()

    def _load_tasks(self):
        """重启后恢复任务；未完成的任务进入待执行状态。"""
        conn = self._conn()
        cols = {r[1] for r in conn.execute("PRAGMA table_info(tasks)")}
        if "failed_details" not in cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN failed_details TEXT DEFAULT '[]'")
            conn.commit()
        if "output_format" not in cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN output_format TEXT DEFAULT 'mbtiles'")
            conn.commit()
        if "tile_layer" not in cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN tile_layer TEXT DEFAULT 'windy'")
            conn.commit()
        rows = conn.execute(
            "SELECT id, status, created_at, updated_at, finished_at, name, params,"
            " total_tiles, downloaded, failed_tiles, min_zoom, max_zoom, point_count,"
            " bounds, error, file_name, file_size, blocked_count, failed_details,"
            " output_format, tile_layer FROM tasks"
        ).fetchall()
        conn.close()
        now = time.time()
        for row in rows:
            (task_id, status, created_at, updated_at, finished_at, name, params,
             total_tiles, downloaded, failed_tiles, min_zoom, max_zoom, point_count,
             bounds, error, file_name, file_size, blocked_count, failed_details,
             output_format, tile_layer) = row
            try:
                bounds_list = json.loads(bounds or "[]")
            except Exception:
                bounds_list = []
            try:
                params_dict = json.loads(params or "{}")
            except Exception:
                params_dict = {}
            try:
                failed_details_list = json.loads(failed_details or "[]")
            except Exception:
                failed_details_list = []
            task = Task(
                id=task_id, status=status, created_at=created_at,
                updated_at=updated_at, name=name, params=params_dict,
                total_tiles=total_tiles, downloaded=downloaded,
                failed_tiles=failed_tiles, min_zoom=min_zoom, max_zoom=max_zoom,
                point_count=point_count, bounds=bounds_list, error=error,
                file_name=file_name, file_size=file_size,
                blocked_count=blocked_count, finished_at=finished_at,
                can_download=(status == COMPLETED),
                failed_details=failed_details_list,
                output_format=(output_format or "mbtiles"),
                tile_layer=(tile_layer or "windy"),
            )
            # 历史保留：完成的成品文件不自动删除；
            # 文件若被手动移除则标记不可下载，状态仍为 completed
            if status == COMPLETED:
                fp = self.output_path(task_id, task.output_format)
                if fp.exists():
                    task.file_size = fp.stat().st_size
                    task.can_download = True
                else:
                    task.can_download = False
            elif status in (QUEUED, DOWNLOADING):
                # 重启前正在跑的任务：重置为 queued，清空进度，恢复时重新下载
                task.status = QUEUED
                task.error = ""
                task.can_download = False
                task.downloaded = 0
                task.failed_tiles = 0
                task.blocked_count = 0
                self._save_task(task)
            self._tasks[task_id] = task

    def _save_task(self, task: Task):
        conn = self._conn()
        conn.execute(
            "INSERT OR REPLACE INTO tasks (id, status, created_at, updated_at,"
            " finished_at, name, params, total_tiles, downloaded, failed_tiles,"
            " min_zoom, max_zoom, point_count, bounds, error, file_name,"
            " file_size, blocked_count, failed_details, output_format, tile_layer)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (task.id, task.status, task.created_at, task.updated_at,
             task.finished_at, task.name, json.dumps(task.params),
             task.total_tiles, task.downloaded, task.failed_tiles,
             task.min_zoom, task.max_zoom, task.point_count,
             json.dumps(task.bounds), task.error, task.file_name,
             task.file_size, task.blocked_count,
             json.dumps(task.failed_details[-200:]), task.output_format,
             task.tile_layer))
        conn.commit()
        conn.close()

    # ---------- 路径 ----------
    def task_dir(self, task_id: str) -> Path:
        d = self._tasks_dir / task_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def input_gpx_path(self, task_id: str) -> Path:
        return self.task_dir(task_id) / "input.gpx"

    def work_path(self, task_id: str, output_format: str) -> Path:
        ext = "gpkg" if output_format == "gpkg" else "mbtiles"
        return self.task_dir(task_id) / f"work.{ext}"

    def output_path(self, task_id: str, output_format: str) -> Path:
        ext = "gpkg" if output_format == "gpkg" else "mbtiles"
        return self.task_dir(task_id) / f"{task_id}.{ext}"

    def start(self):
        """启动时恢复排队任务（受并发上限约束）。"""
        to_start = [t for t in self._tasks.values() if t.status == QUEUED]
        for task in to_start[:self.settings.max_running_tasks]:
            coro = self._run_task(task)
            t = asyncio.create_task(coro)
            self._running[task.id] = t
            logger.info("resumed queued task %s after restart", task.id)

    # ---------- 任务提交 ----------
    async def submit(self, gpx_data: bytes, params: dict) -> Task:
        task_id = uuid.uuid4().hex
        async with self._lock:
            running = sum(1 for t in self._running.values() if not t.done())
            if running >= self.settings.max_running_tasks:
                raise TaskLimitError(
                    f"同时运行任务数已达上限（{self.settings.max_running_tasks}），请稍后重试")

        now = time.time()
        tile_layer = str(params.get("tile_layer") or "windy")
        task = Task(
            id=task_id, status=QUEUED, created_at=now, updated_at=now,
            name=params.get("name") or "track",
            tile_layer=tile_layer,
            params={
                "buffer_meters": params.get("buffer_meters", 2500),
                "min_zoom": params.get("min_zoom", 8),
                "max_zoom": params.get("max_zoom", 17),
                "concurrency": params.get("concurrency"),
                "interval_ms": params.get("interval_ms"),
                "output_format": params.get("output_format", "gpkg"),
                "allow_oversize": bool(params.get("allow_oversize")),
                "tile_layer": tile_layer,
                "custom_name": str(params.get("custom_name") or "").strip(),
            },
        )
        # 先落盘 GPX
        self.input_gpx_path(task_id).write_bytes(gpx_data)
        self._tasks[task_id] = task
        self._save_task(task)
        coro = self._run_task(task)
        t = asyncio.create_task(coro)
        self._running[task_id] = t
        return task

    # ---------- 任务执行 ----------
    async def _run_task(self, task: Task):
        try:
            await self._execute(task)
        except asyncio.CancelledError:
            await self._finalize_cancelled(task)
        except Exception as exc:
            logger.exception("task %s crashed", task.id)
            task.status = FAILED
            task.error = f"服务端异常：{exc}"
            task.updated_at = time.time()
            task.finished_at = time.time()
            self._save_task(task)
        finally:
            async with self._lock:
                self._running.pop(task.id, None)

    async def _execute(self, task: Task):
        """解析 GPX → 生成瓦片清单 → 并发下载 → 组装 mbtiles。"""
        if task.status == CANCELLED:
            return
        settings = self.settings
        # 解析瓦片图层提供者（默认 windy）
        tile_layer = str(task.params.get("tile_layer") or task.tile_layer or "windy")
        provider = settings.tile_providers.get(tile_layer)
        if provider is None:
            raise GpxParseError(f"不支持的瓦片图层：{tile_layer}")
        task.tile_layer = tile_layer
        task.status = DOWNLOADING
        task.updated_at = time.time()
        self._save_task(task)

        cancel_event = asyncio.Event()
        task.cancel_event = cancel_event  # 供 cancel() 使用
        start = time.monotonic()
        timeout = settings.task_timeout_seconds
        fetcher = None  # 在 eff_settings 构建后再创建（需 provider 特定的 URL/UA/Referer）
        try:
            # 1. 解析 GPX（轨迹名缺失时保留上传文件名）
            gpx_bytes = self.input_gpx_path(task.id).read_bytes()
            points, name = parse_gpx(gpx_bytes)
            if name and name != "track":
                task.name = name
            task.point_count = len(points)

            buffer_m = float(task.params["buffer_meters"])
            if buffer_m < settings.buffer_min or buffer_m > settings.buffer_max:
                raise GpxParseError(
                    f"缓冲距离必须在 {settings.buffer_min}~{settings.buffer_max} 米之间")
            min_zoom = int(task.params["min_zoom"])
            max_zoom = int(task.params["max_zoom"])
            min_zoom = max(settings.zoom_min_cap, min(min_zoom, settings.zoom_max_cap))
            max_zoom = max(settings.zoom_min_cap, min(max_zoom, settings.zoom_max_cap))
            # 按瓦片源限制最大缩放（如 OpenTopoMap 仅到 z17）
            max_zoom = min(max_zoom, provider.max_zoom)
            if min_zoom > max_zoom:
                raise GpxParseError(f"缩放范围无效：{min_zoom}~{max_zoom}")

            concurrency = int(task.params.get("concurrency") or settings.max_concurrency)
            concurrency = max(1, min(concurrency, 32))
            interval_ms = int(task.params.get("interval_ms") or settings.request_interval_ms)
            interval_ms = max(0, min(interval_ms, 10000))

            allow_oversize = bool(task.params.get("allow_oversize"))
            max_tiles = None if allow_oversize else settings.max_tiles_per_task
            plan = build_tile_plan(points, buffer_m, min_zoom, max_zoom, max_tiles)
            task.total_tiles = len(plan.tiles)
            task.min_zoom = min_zoom
            task.max_zoom = max_zoom
            task.bounds = list(plan.bounds)
            task.updated_at = time.time()
            self._save_task(task)
            logger.info("task %s plan: %d tiles (zoom %d-%d)",
                        task.id, task.total_tiles, min_zoom, max_zoom)

            if not plan.tiles:
                task.status = FAILED
                task.error = "轨迹没有覆盖任何瓦片"
                task.updated_at = task.finished_at = time.time()
                self._save_task(task)
                return

            # 磁盘空间检查（估：每瓦片按 50KB 计）
            est_bytes = len(plan.tiles) * 51200 + settings.disk_min_free_bytes
            free = shutil.disk_usage(settings.data_dir).free
            if free < est_bytes:
                task.status = FAILED
                task.error = (f"磁盘空间不足（剩余 {free // (1024*1024)}MB，"
                              f"预计需要 {est_bytes // (1024*1024)}MB）")
                task.finished_at = task.updated_at = time.time()
                self._save_task(task)
                self._clean_task_files(task.id)
                return

            # 2. 下载瓦片并按所选格式写入
            output_format = str(task.params.get("output_format") or "gpkg")
            if output_format not in ("gpkg", "mbtiles"):
                raise GpxParseError(f"不支持的输出格式：{output_format}")
            task.output_format = output_format
            eff_settings = _derived_settings(settings, concurrency, interval_ms, provider)
            fetcher = TileFetcher(eff_settings)
            # 清理上次中断残留的中间文件（重启恢复场景），保证全新写入
            for leftover in ("work.gpkg", "work.gpkg-wal", "work.gpkg-shm",
                             "work.mbtiles", "work.mbtiles-wal", "work.mbtiles-shm"):
                lp = self.task_dir(task.id) / leftover
                if lp.exists():
                    try:
                        lp.unlink()
                    except OSError:
                        pass
            work_path = self.work_path(task.id, output_format)
            if output_format == "gpkg":
                builder = GpkgBuilder(work_path)
            else:
                builder = MbtilesBuilder(work_path)
            await fetcher.open()

            async def on_success(z, x, y, data):
                builder.add_tile(z, x, y, data)
                task.downloaded += 1
                self._maybe_save_progress(task, force=False)

            async def on_failed(z, x, y, reason):
                task.failed_tiles += 1
                if "403/429" in reason:
                    task.blocked_count += 1
                task.failed_details.append([z, x, y, reason])
                if len(task.failed_details) > 200:
                    del task.failed_details[:-200]

            try:
                result = await asyncio.wait_for(
                    download_tiles(plan.tiles, fetcher.fetch, on_success, on_failed,
                                   eff_settings, cancel_event),
                    timeout=timeout)
            except asyncio.TimeoutError:
                result = None
                timed_out = True
            else:
                timed_out = False

            builder.flush()
            await fetcher.close()

            # 3. 结束处理
            if cancel_event.is_set():
                task.status = CANCELLED
                task.error = "任务已取消"
                task.downloaded = result.downloaded if result else task.downloaded
                builder.abort()
                self._clean_task_files(task.id)
            elif timed_out:
                task.status = FAILED
                task.error = f"任务超过最大运行时间（{timeout // 60} 分钟）被终止"
                task.downloaded = result.downloaded if result else task.downloaded
                builder.abort()
                self._clean_task_files(task.id)
            elif result is not None and result.error:
                task.status = FAILED
                task.error = result.error
                task.downloaded = result.succeeded
                task.failed_tiles = result.failed
                task.blocked_count = result.blocked_failures
                builder.abort()
                self._clean_task_files(task.id)
            elif result is None:
                task.status = FAILED
                task.error = "下载异常结束"
                builder.abort()
                self._clean_task_files(task.id)
            else:
                # 全部瓦片(含失败跳过)处理完成：生成成品
                task.downloaded = result.succeeded
                task.failed_tiles = result.failed
                task.blocked_count = result.blocked_failures
                count, bounds = builder.finalize(task.name, min_zoom, max_zoom,
                                                 fallback_bounds=plan.bounds)
                task.bounds = list(bounds)
                out_path = self.output_path(task.id, output_format)
                work_path.rename(out_path)
                ext = "gpkg" if output_format == "gpkg" else "mbtiles"
                base = task.params.get("custom_name") or task.name
                safe_base = "".join(c for c in str(base) if c.isalnum() or c in "-_")[:80] or "track"
                task.file_name = f"{safe_base}_{tile_layer}.{ext}"
                task.file_size = out_path.stat().st_size
                if count == 0:
                    task.status = FAILED
                    task.error = "没有下载到任何瓦片"
                    self._clean_task_files(task.id)
                elif result.failed >= max(1, task.total_tiles // 2):
                    task.status = FAILED
                    task.error = f"失败瓦片过多（{result.failed}/{task.total_tiles}），成品不可用"
                    self._clean_task_files(task.id)
                else:
                    task.status = COMPLETED
                    task.can_download = True
            task.finished_at = time.time()
            task.updated_at = time.time()
            self._save_task(task)
            logger.info("task %s final: %s (dl=%d fail=%d)",
                        task.id, task.status, task.downloaded, task.failed_tiles)
        except GpxParseError as exc:
            task.status = FAILED
            task.error = str(exc)
            task.finished_at = task.updated_at = time.time()
            self._save_task(task)
            self._clean_task_files(task.id)
        finally:
            if fetcher is not None:
                await fetcher.close()
            await asyncio.sleep(0)

    def _maybe_save_progress(self, task: Task, force: bool):
        """节流：进度每 ~1.5 秒持久化一次，避免高频写库。"""
        now = time.monotonic()
        last = getattr(task, "_last_persist", 0.0)
        if force or now - last >= 1.5:
            task._last_persist = now
            task.updated_at = time.time()
            self._save_task(task)

    async def _finalize_cancelled(self, task: Task):
        task.status = CANCELLED
        task.error = "任务已取消"
        task.finished_at = task.updated_at = time.time()
        self._clean_task_files(task.id)
        self._save_task(task)

    def _clean_task_files(self, task_id: str):
        """删除任务输入文件与中间产物，保留成品。"""
        d = self.task_dir(task_id)
        for name in ("input.gpx",
                     "work.gpkg", "work.gpkg-wal", "work.gpkg-shm",
                     "work.mbtiles", "work.mbtiles-wal", "work.mbtiles-shm"):
            p = d / name
            try:
                if p.exists():
                    p.unlink()
            except OSError:
                pass

    # ---------- 任务操作 ----------
    async def cancel(self, task_id: str) -> Task:
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise TaskNotFoundError("任务不存在")
        if task.status in (QUEUED, DOWNLOADING):
            ev: asyncio.Event | None = getattr(task, "cancel_event", None)
            if ev is not None:
                ev.set()
            running = self._running.get(task_id)
            if running is not None:
                if task.status == DOWNLOADING:
                    running.cancel()
                elif task.status == QUEUED:
                    task.status = CANCELLED
                    task.error = "任务已取消"
                    task.finished_at = task.updated_at = time.time()
                    self._save_task(task)
                    self._clean_task_files(task_id)
            else:
                task.status = CANCELLED
                task.error = "任务已取消"
                task.finished_at = task.updated_at = time.time()
                self._save_task(task)
                self._clean_task_files(task_id)
        return task

    def get(self, task_id: str) -> Task:
        task = self._tasks.get(task_id)
        if task is None:
            raise TaskNotFoundError("任务不存在")
        if task.status in (DOWNLOADING,):
            # 内存实时计数回填
            pass
        return task

    def list_running(self) -> list[Task]:
        return [t for t in self._tasks.values()
                if t.status in (QUEUED, DOWNLOADING)]

    def list_all(self) -> list[Task]:
        return sorted(self._tasks.values(), key=lambda t: t.created_at, reverse=True)

    async def delete(self, task_id: str) -> None:
        """手动删除任务：运行中先取消，删除记录、目录与成品。"""
        task = self._tasks.get(task_id)
        if task is None:
            raise TaskNotFoundError("任务不存在")
        if task.status in (QUEUED, DOWNLOADING):
            await self.cancel(task_id)
        running = self._running.get(task_id)
        if running is not None:
            running.cancel()
            await asyncio.gather(running, return_exceptions=True)
        self._purge_task_dir(task_id)
        self._tasks.pop(task_id, None)
        conn = self._conn()
        conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        conn.commit()
        conn.close()
        logger.info("task %s deleted by user", task_id)

    # ---------- 清理 ----------
    async def cleanup_loop(self):
        """周期清理：删除过期任务目录与孤儿文件。"""
        settings = self.settings
        while True:
            try:
                self._cleanup_once()
            except Exception:
                logger.exception("cleanup failed")
            try:
                await asyncio.wait_for(self._cleanup_event.wait(),
                                       timeout=settings.cleanup_interval_seconds)
                self._cleanup_event.clear()
            except asyncio.TimeoutError:
                pass

    def _cleanup_once(self):
        settings = self.settings
        now = time.time()
        # 1. 过期完成任务的成品文件
        for task in list(self._tasks.values()):
            if task.status == COMPLETED:
                # 历史保留：完成的地图成品不自动删除，由用户手动删除
                fp = self.output_path(task.id, task.output_format)
                if fp.exists():
                    try:
                        task.file_size = fp.stat().st_size
                    except OSError:
                        pass
                    task.can_download = True
                else:
                    task.can_download = False
            elif task.status in (FAILED, CANCELLED):
                ref = max(task.updated_at, task.finished_at)
                if now - ref > settings.file_expiry_seconds:
                    self._purge_task_dir(task.id)
                    self._tasks.pop(task.id, None)
                    logger.info("task %s fully purged", task.id)
        # 2. 孤儿目录（库中无记录）
        for d in self._tasks_dir.iterdir():
            if d.is_dir() and d.name not in self._tasks:
                try:
                    shutil.rmtree(d, ignore_errors=True)
                except OSError:
                    pass

    def _purge_task_dir(self, task_id: str):
        try:
            shutil.rmtree(self.task_dir(task_id), ignore_errors=True)
        except OSError:
            pass

    async def shutdown(self):
        for t in self._running.values():
            t.cancel()
        await asyncio.gather(*self._running.values(), return_exceptions=True)
        self._cleanup_once()


def _derived_settings(settings: Settings, concurrency: int, interval_ms: int, provider):
    """按任务参数与瓦片图层构建下载配置副本。"""
    from .config import TileProvider
    provider: TileProvider
    class _Derived:
        pass
    d = _Derived()
    # 图层相关：来自 provider
    d.tile_url_template = provider.url_template
    d.tile_subdomains = provider.subdomains
    d.user_agent = provider.user_agent
    d.referer = provider.referer
    # 通用：来自全局 settings
    for attr in ("tile_proxy", "tile_timeout_seconds", "retry_max",
                 "retry_backoff_base", "block_pause_seconds", "block_fail_min_count",
                 "block_fail_ratio", "block_consecutive_threshold"):
        setattr(d, attr, getattr(settings, attr))
    d.max_concurrency = concurrency
    d.request_interval_ms = interval_ms
    return d
