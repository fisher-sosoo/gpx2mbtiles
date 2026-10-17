import asyncio
import logging
import math
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import (FileResponse, JSONResponse, Response,
                               StreamingResponse)
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .gpx_converter import convert
from .gpx_processor import (GpxParseError, build_tile_plan, parse_gpx,
                            parse_track_points)
from .kml_processor import KmlParseError
from .poi_enricher import PoiQueryError, fetch_overpass, filter_pois
from .project_store import ProjectNotFoundError, ProjectStore
from .task_manager import (COMPLETED, TaskLimitError, TaskManager,
                           TaskNotFoundError)
from .tile_cache import TileCache, valid_xyz
from .tile_downloader import TileBlocked, TileFetcher, TileHttpError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("gpx2mbtiles")

settings = get_settings()
manager: TaskManager
tile_cache: TileCache
project_store: ProjectStore


@asynccontextmanager
async def lifespan(app: FastAPI):
    global manager, tile_cache, project_store
    manager = TaskManager(settings)
    manager.start()
    tile_cache = TileCache(settings)
    project_store = ProjectStore(settings)
    cleanup_task = asyncio.create_task(manager.cleanup_loop())
    app.state.manager = manager
    app.state.tile_cache = tile_cache
    app.state.project_store = project_store
    logger.info("gpx2mbtiles started: data_dir=%s max_running=%d interval=%dms",
                settings.data_dir, settings.max_running_tasks, settings.request_interval_ms)
    project_store.prune()
    yield
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    await manager.shutdown()
    logger.info("gpx2mbtiles stopped")


app = FastAPI(title="GPX-to-MBTiles", version="1.0.0", lifespan=lifespan)


def require_api_key(request: Request):
    """AUTH_TOKEN 为空时放行；否则要求 X-API-Key、Bearer 或 URL 查询参数 token 之一匹配。

    URL 查询参数 token 用于前端 <a href> 原生下载（浏览器导航不携带自定义请求头）。
    """
    if not settings.auth_token:
        return True
    supplied = request.headers.get("X-API-Key") or ""
    auth = request.headers.get("Authorization") or ""
    query_token = request.query_params.get("token") or ""
    if (supplied != settings.auth_token
            and auth != f"Bearer {settings.auth_token}"
            and query_token != settings.auth_token):
        raise HTTPException(status_code=401, detail="需要 API Key（X-API-Key 请求头）")
    return True


@app.get("/api/health")
async def health():
    return {"status": "ok", "max_running": settings.max_running_tasks}


# ---------------------------------------------------------------- 瓦片代理
# 前端直接把这些 URL 交给 Leaflet：/api/tile/windy/{z}/{x}/{y}
#
# 为什么要走服务端：Windy 的响应头 credentials:true + origin:* 违反 CORS 规范，
# 浏览器直接请求会被判 ERR_BLOCKED_BY_ORB，底图整片空白。服务端代取后同源返回。
#
# 缓存：命中直接回盘上文件；未命中回源并落盘。容量超限按 LRU 淘汰。

_tile_fetcher = None
_tile_fetch_lock: asyncio.Lock | None = None


def _get_tile_fetcher():
    """懒建一个共享的 TileFetcher（沿用 .env 里的 UA/Referer/代理）。"""
    global _tile_fetcher, _tile_fetch_lock
    if _tile_fetch_lock is None:
        _tile_fetch_lock = asyncio.Lock()
    if _tile_fetcher is None:
        _tile_fetcher = TileFetcher(settings)
    return _tile_fetcher


def _tile_etag(layer: str, z: int, x: int, y: int, body: bytes) -> str:
    """瓦片内容的强 ETag。

    同一 (layer,z,x,y) 的瓦片内容恒定，用内容哈希即可；
    不用 mtime（回源时间不同会导致同一瓦片 ETag 变化，白白失效浏览器缓存）。
    """
    import hashlib
    h = hashlib.sha1(body).hexdigest()[:20]
    return f'"{layer}-{z}-{x}-{y}-{h}"'


def _tile_response(body: bytes, state: str, layer: str, z: int, x: int, y: int,
                   request: Request | None = None) -> Response:
    """统一的瓦片响应：带 immutable 缓存头与 ETag。"""
    headers = _tile_cache_headers(layer, z, x, y, body, state)
    return Response(content=body, media_type="image/png", headers=headers)


def _tile_cache_headers(layer: str, z: int, x: int, y: int, body: bytes, state: str) -> dict:
    return {
        # 瓦片按坐标恒定，可长期immutable：浏览器直接命中本地副本，
        # 连 304 条件请求都不会发。这解决了"反复放大缩小重复请求"的问题
        # （实测快速缩放时重复率高达 75%）。
        "Cache-Control": "public, max-age=2592000, immutable",
        "ETag": _tile_etag(layer, z, x, y, body),
        "X-Tile-Cache": state,
    }


@app.get("/api/tile/{layer}/{z}/{x}/{y}")
async def get_tile(layer: str, z: int, x: int, y: int) -> Response:
    """瓦片代理：同源返回，带磁盘缓存。

    不加 require_api_key：Leaflet 的 <img> 请求带不了自定义头，
    而这里只代理白名单图层、且只读公开瓦片，无敏感信息。
    """
    layer = layer.strip().lower()
    if layer not in settings.tile_proxy_layers:
        raise HTTPException(status_code=404, detail="该图层未开放代理")
    if not valid_xyz(z, x, y):
        raise HTTPException(status_code=400, detail="瓦片坐标越界")

    # 1) 命中缓存
    cached = tile_cache.get(layer, z, x, y)
    if cached is not None:
        return _tile_response(cached, "HIT", layer, z, x, y)

    # 2) 回源（按图层切换 settings 里的模板）
    fetcher = _get_tile_fetcher()
    async with _tile_fetch_lock:
        if fetcher._session is None:
            await fetcher.open()
        provider = settings.tile_providers[layer]
        # TileFetcher 默认用 settings 的模板；这里临时换成本图层
        old_tpl, old_subs = settings.tile_url_template, getattr(settings, "tile_subdomains", ())
        old_ua, old_ref = settings.user_agent, settings.referer
        settings.tile_url_template = provider.url_template
        settings.tile_subdomains = provider.subdomains
        settings.user_agent = provider.user_agent
        settings.referer = provider.referer
        try:
            # 换过 UA/Referer 需要重建 session 头
            await fetcher.close()
            await fetcher.open()
            body = await fetcher.fetch(z, x, y)
        except TileBlocked as exc:
            logger.warning("tile blocked by upstream: %s/%s/%s/%s status=%s",
                           layer, z, x, y, exc.status)
            raise HTTPException(status_code=503,
                                detail="上游限流，请稍后重试（可降低底图加载速度）")
        except TileHttpError as exc:
            raise HTTPException(status_code=502 if exc.status != 404 else 404,
                                detail=f"上游返回 {exc.status}")
        finally:
            settings.tile_url_template = old_tpl
            settings.tile_subdomains = old_subs
            settings.user_agent = old_ua
            settings.referer = old_ref
            await fetcher.close()

    # 3) 落盘并返回
    tile_cache.put(layer, z, x, y, body)
    return _tile_response(body, "MISS", layer, z, x, y)


@app.get("/api/tilecache/stats")
async def tilecache_stats():
    """缓存用量，便于观察磁盘占用。"""
    return tile_cache.stats()


@app.post("/api/tilecache/evict", dependencies=[Depends(require_api_key)])
async def tilecache_evict():
    """手动触发一次 LRU 清理。"""
    removed = tile_cache.evict()
    return {"removed": removed, **tile_cache.stats()}


@app.post("/api/submit", dependencies=[Depends(require_api_key)])
async def submit(
    file: UploadFile = File(...),
    buffer_meters: float = Form(2500),
    min_zoom: int = Form(8),
    max_zoom: int = Form(17),
    concurrency: int = Form(0),
    interval_ms: int = Form(0),
    output_format: str = Form("gpkg"),
    tile_layer: str = Form("windy"),
    custom_name: str = Form(""),
    allow_oversize: bool = Form(False),
):
    """提交任务：上传 GPX + 参数，返回 task_id。"""
    filename = file.filename or "track.gpx"
    if not _is_track_file(filename):
        raise HTTPException(status_code=400,
                            detail="仅支持 .gpx / .kml / .kmz 文件")
    gpx_data = await file.read()
    if len(gpx_data) > settings.max_gpx_bytes:
        raise HTTPException(status_code=413,
                            detail=f"GPX 文件过大（限制 {settings.max_gpx_bytes // (1024*1024)}MB）")
    if not gpx_data.strip():
        raise HTTPException(status_code=400, detail="GPX 文件为空")
    # 提前校验格式，失败不建任务
    try:
        _parse_track_points(gpx_data, filename)
    except (GpxParseError, KmlParseError) as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    output_format = output_format.strip().lower()
    if output_format not in ("gpkg", "mbtiles"):
        return JSONResponse(status_code=400,
                            content={"detail": "output_format 仅支持 gpkg 或 mbtiles"})
    tile_layer = tile_layer.strip().lower()
    if tile_layer not in settings.tile_providers:
        return JSONResponse(status_code=400,
                            content={"detail": f"tile_layer 仅支持：{', '.join(settings.tile_providers)}"})
    allow_oversize_b = (bool(allow_oversize)
                        if isinstance(allow_oversize, bool)
                        else str(allow_oversize).lower() in ("1", "true", "yes", "on"))
    params = {
        "name": filename.rsplit(".", 1)[0],
        "buffer_meters": float(buffer_meters),
        "min_zoom": int(min_zoom),
        "max_zoom": int(max_zoom),
        "concurrency": int(concurrency or 0),
        "interval_ms": int(interval_ms or 0),
        "output_format": output_format,
        "tile_layer": tile_layer,
        "custom_name": custom_name.strip(),
        "allow_oversize": allow_oversize_b,
        # 记录原始文件名：任务在 worker 里重新解析时要据此判断 GPX / KML / KMZ
        "source_filename": filename,
    }
    try:
        task = await manager.submit(gpx_data, params)
    except TaskLimitError as exc:
        return JSONResponse(status_code=429, content={"detail": str(exc)})
    return {"task_id": task.id, "status": task.status,
            "params": task.params, "message": "任务已提交"}


@app.get("/api/status/{task_id}", dependencies=[Depends(require_api_key)])
async def status(task_id: str):
    """查询任务状态。"""
    try:
        task = manager.get(task_id)
    except TaskNotFoundError:
        raise HTTPException(status_code=404, detail="任务不存在") from None
    return task.to_dict()


@app.post("/api/cancel/{task_id}", dependencies=[Depends(require_api_key)])
async def cancel(task_id: str):
    """取消任务。"""
    try:
        task = await manager.cancel(task_id)
    except TaskNotFoundError:
        raise HTTPException(status_code=404, detail="任务不存在") from None
    return task.to_dict()


@app.get("/api/download/{task_id}", dependencies=[Depends(require_api_key)])
async def download(task_id: str):
    """下载成品 mbtiles。"""
    try:
        task = manager.get(task_id)
    except TaskNotFoundError:
        raise HTTPException(status_code=404, detail="任务不存在") from None
    if task.status != COMPLETED:
        raise HTTPException(status_code=409,
                            detail=f"任务尚未完成（当前状态：{task.status}）")
    fp = manager.output_path(task_id, task.output_format)
    if not fp.exists():
        raise HTTPException(status_code=410, detail="文件已过期，请重新提交任务")
    ext = "gpkg" if task.output_format == "gpkg" else "mbtiles"
    base = task.params.get("custom_name") or task.name
    filename = f"{_safe_name(base)}_{task.tile_layer}.{ext}"
    media = ("application/geopackage+sqlite3"
             if ext == "gpkg" else "application/vnd.sqlite3")
    return FileResponse(
        path=str(fp),
        media_type=media,
        filename=filename,
    )


@app.get("/api/tasks", dependencies=[Depends(require_api_key)])
async def list_tasks():
    """历史任务列表（含已完成地图，可手动删除）。"""
    tasks = manager.list_all()[:100]
    return {"tasks": [t.to_dict() for t in tasks]}


@app.delete("/api/tasks/{task_id}", dependencies=[Depends(require_api_key)])
async def delete_task(task_id: str):
    """手动删除任务（含成品文件与历史记录）。"""
    try:
        await manager.delete(task_id)
    except TaskNotFoundError:
        raise HTTPException(status_code=404, detail="任务不存在") from None
    return {"deleted": task_id}


@app.post("/api/estimate", dependencies=[Depends(require_api_key)])
async def estimate(
    file: UploadFile = File(...),
    buffer_meters: float = Form(2500),
    min_zoom: int = Form(8),
    max_zoom: int = Form(17),
):
    """预估瓦片数（不建任务）。"""
    filename = file.filename or "track.gpx"
    if not _is_track_file(filename):
        raise HTTPException(status_code=400,
                            detail="仅支持 .gpx / .kml / .kmz 文件")
    gpx_data = await file.read()
    if len(gpx_data) > settings.max_gpx_bytes:
        raise HTTPException(status_code=413,
                            detail=f"GPX 文件过大（限制 {settings.max_gpx_bytes // (1024*1024)}MB）")
    try:
        points, _ = _parse_track_points(gpx_data, filename)
        if int(min_zoom) > int(max_zoom):
            raise GpxParseError(f"最小缩放级别({min_zoom})不能大于最大缩放级别({max_zoom})")
        plan = build_tile_plan(points, float(buffer_meters),
                               int(min_zoom), int(max_zoom), max_tiles=None)
    except GpxParseError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    return {
        "tiles": len(plan.tiles),
        "point_count": plan.point_count,
        "max_tiles_per_task": settings.max_tiles_per_task,
        "exceeds_limit": len(plan.tiles) > settings.max_tiles_per_task,
    }


# ---------------------------------------------------------------- 命名转换
# KML/KMZ 里的「标注点」普遍没有 <name>，轨迹名也只有「轨迹片段1」这种占位词，
# 转成 GPX 后 App 里全是无意义标签。这里在转换时按 metadata 重新组织名称。

TRACK_EXTS = (".gpx", ".xml", ".kml", ".kmz")


def _is_track_file(filename: str) -> bool:
    return filename.lower().endswith(TRACK_EXTS)


def _parse_track_points(data: bytes, filename: str):
    """统一取点入口（实现见 gpx_processor，worker 也用同一份）。"""
    return parse_track_points(data, filename)


@app.post("/api/convert", dependencies=[Depends(require_api_key)])
async def convert_track(
    file: UploadFile | None = File(None),
    text: str = Form(""),
    track_name: str = Form(""),
    filename: str = Form(""),
    ai_names: bool = Form(False),
):
    """KML/KMZ → 命名整理过的 GPX，并落成一个项目空间（可回看/重转/删除）。

    ai_names=true 时额外调用一次模型给航点起语义名称；失败自动回退，不影响转换。
    """
    data = b""
    name = (filename or "").strip()
    if file is not None:
        name = file.filename or name
        data = await file.read()
    elif text.strip():
        data = text.encode("utf-8")
        name = name or "pasted.kml"
    if not data or not data.strip():
        raise HTTPException(status_code=400, detail="请上传 KML/KMZ 文件或粘贴 KML 内容")
    if len(data) > settings.max_convert_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"文件过大（限制 {settings.max_convert_bytes // (1024*1024)}MB）")
    want_ai = (ai_names if isinstance(ai_names, bool)
               else str(ai_names).strip().lower() in ("1", "true", "yes", "on"))
    try:
        result = convert(data, name, track_name.strip(),
                         ai_names=want_ai, settings=settings)
    except KmlParseError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    ext = ".kmz" if name.lower().endswith(".kmz") else ".kml"
    project = project_store.save(
        source_bytes=data, source_name=name, ext=ext, result=result,
        params={"track_name": track_name.strip(), "ai_names": want_ai},
    )
    return {
        "gpx": result.gpx,
        "filename": result.filename,
        "summary": result.summary.to_dict(),
        "project_id": project["id"],
    }


# ---------------------------------------------------------------- 项目历史
# 每次转换都是一个项目：原件 + 产物 GPX + 摘要都在 data/projects/<id>/ 下，
# 账本在 projects.db。支持回看、带新参数重转、删除。


@app.get("/api/projects", dependencies=[Depends(require_api_key)])
async def list_projects(limit: int = 50, offset: int = 0):
    """历史转换列表（按时间倒序）。"""
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    return project_store.list(limit=limit, offset=offset)


@app.get("/api/projects/{project_id}", dependencies=[Depends(require_api_key)])
async def get_project(project_id: str):
    """项目详情：元数据 + 摘要 + GPX 文本，便于直接回看。"""
    try:
        meta = project_store.get(project_id)
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail="项目不存在") from None
    gpx = ""
    if meta.get("gpx_available"):
        try:
            gpx = project_store.read_gpx(project_id)
        except ProjectNotFoundError:
            gpx = ""
    return {**meta, "gpx": gpx}


@app.delete("/api/projects/{project_id}", dependencies=[Depends(require_api_key)])
async def delete_project(project_id: str):
    """删除项目（含目录下的原件与产物）。"""
    if not project_store.delete(project_id):
        raise HTTPException(status_code=404, detail="项目不存在")
    return {"deleted": project_id}


@app.post("/api/projects/{project_id}/reconvert",
          dependencies=[Depends(require_api_key)])
async def reconvert_project(project_id: str,
                            track_name: str = Form(""),
                            ai_names: bool = Form(False)):
    """用保存的原件重新转换，生成一个新项目（旧项目保留，便于对比）。"""
    try:
        meta = project_store.get(project_id)
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail="项目不存在") from None
    ext = meta.get("ext") or ".kml"
    src = project_store.input_path(project_id, ext)
    if not src.is_file():
        raise HTTPException(status_code=410, detail="原件已被清理，无法重转")
    data = src.read_bytes()
    want_ai = (ai_names if isinstance(ai_names, bool)
               else str(ai_names).strip().lower() in ("1", "true", "yes", "on"))
    name = meta.get("source_name") or f"project{ext}"
    try:
        result = convert(data, name, track_name.strip(),
                         ai_names=want_ai, settings=settings)
    except KmlParseError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    project = project_store.save(
        source_bytes=data, source_name=name, ext=ext, result=result,
        params={"track_name": track_name.strip(), "ai_names": want_ai,
                "from_project": project_id},
    )
    return {
        "gpx": result.gpx,
        "filename": result.filename,
        "summary": result.summary.to_dict(),
        "project_id": project["id"],
        "reconverted_from": project_id,
    }


# ---------------------------------------------------------------- 地名补点
# Overpass 一次查询要 40 秒上下，绝不能同步等：发起即返回，后台跑，结果落 pois.json。

_poi_jobs: dict = {}


def _project_track_points(store: ProjectStore, project_id: str):
    """从项目的产物 GPX 里取轨迹点（用于算包围盒与距离）。"""
    import gpxpy
    path = store.output_path(project_id)
    if not path.is_file():
        return []
    try:
        gpx = gpxpy.parse(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    pts = []
    for trk in gpx.tracks:
        for seg in trk.segments:
            for p in seg.points:
                pts.append((float(p.latitude), float(p.longitude)))
    return pts


def _bbox_of(points, pad_m: float):
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    dlat = pad_m / 111320.0
    cos_lat = max(0.0001, math.cos(math.radians(sum(lats) / len(lats))))
    dlon = pad_m / (111320.0 * cos_lat)
    return (min(lats) - dlat, min(lons) - dlon,
            max(lats) + dlat, max(lons) + dlon)


async def _run_poi_job(project_id: str, force: bool = False):
    job = {"status": "running", "started": time.time(), "count": 0, "error": ""}
    _poi_jobs[project_id] = job
    try:
        points = _project_track_points(project_store, project_id)
        if not points:
            raise PoiQueryError("项目里没有可用的轨迹点")
        bbox = _bbox_of(points, settings.poi_bbox_pad_m)
        elements = await asyncio.to_thread(
            fetch_overpass, bbox, settings, settings.poi_timeout_seconds)
        result = filter_pois(elements, points, settings)
        payload = {
            "fetched_at": result.fetched_at,
            "bbox": [round(v, 6) for v in bbox],
            "total_raw": result.total_raw,
            "dropped": result.dropped,
            "truncated": result.truncated,
            "items": result.items,
        }
        project_store.save_pois(project_id, payload)
        job.update(status="done", count=len(result.items),
                   dropped=result.dropped, truncated=result.truncated,
                   total_raw=result.total_raw, finished=time.time())
        logger.info("poi enrichment %s: %d items (raw %d, dropped %d, truncated %d)",
                    project_id, len(result.items), result.total_raw,
                    result.dropped, result.truncated)
    except PoiQueryError as exc:
        job.update(status="failed", error=str(exc), finished=time.time())
    except Exception as exc:                      # 兜底：不能拖垮服务
        logger.exception("poi enrichment failed for %s", project_id)
        job.update(status="failed", error=f"{type(exc).__name__}: {exc}",
                   finished=time.time())


@app.post("/api/projects/{project_id}/pois", dependencies=[Depends(require_api_key)])
async def enrich_project_pois(project_id: str, refresh: bool = Form(False)):
    """发起地名补点（异步）。refresh=true 时忽略缓存重查。"""
    try:
        project_store.get(project_id)
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail="项目不存在") from None
    if not getattr(settings, "poi_enabled", True):
        raise HTTPException(status_code=503, detail="地名补点未启用（POI_ENABLED=0）")
    want_refresh = (refresh if isinstance(refresh, bool)
                    else str(refresh).strip().lower() in ("1", "true", "yes", "on"))
    if not want_refresh:
        cached = project_store.load_pois(project_id)
        if cached is not None:
            return {"status": "cached", "count": len(cached.get("items", [])),
                    "data": cached}
    running = _poi_jobs.get(project_id)
    if running and running.get("status") == "running":
        return {"status": "running", "count": 0}
    asyncio.create_task(_run_poi_job(project_id, force=want_refresh))
    return {"status": "started", "count": 0}


@app.get("/api/projects/{project_id}/pois", dependencies=[Depends(require_api_key)])
async def get_project_pois(project_id: str):
    """取地名补点结果：缓存优先，其次任务状态。"""
    try:
        project_store.get(project_id)
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail="项目不存在") from None
    job = _poi_jobs.get(project_id)
    cached = project_store.load_pois(project_id)
    if cached is not None:
        return {"status": "done", "count": len(cached.get("items", [])),
                "data": cached}
    if job:
        return {"status": job.get("status", "running"),
                "count": job.get("count", 0),
                "error": job.get("error", "")}
    return {"status": "none", "count": 0}


def _merge_pois_into_gpx(gpx_text: str, pois: list) -> str:
    """把地名点作为额外 <wpt> 插入 GPX（在 </gpx> 前），不改动原有轨迹。"""
    from xml.sax.saxutils import escape, quoteattr
    parts = []
    for it in pois:
        name = it.get("name") or ""
        label = f"{it.get('type_label') or ''} {name}".strip()
        bits = [f"来源 OSM", f"距轨迹 {it.get('distance_m')} m"]
        if it.get("ele") is not None:
            bits.insert(0, f"海拔 {int(round(it['ele']))} m")
        desc = " · ".join(bits)
        parts.append(
            f'  <wpt lat={quoteattr("%.6f" % it["lat"])} '
            f'lon={quoteattr("%.6f" % it["lon"])}>\n')
        if it.get("ele") is not None:
            parts.append(f'    <ele>{"%.6f" % it["ele"]}</ele>\n')
        parts.append(f"    <name>{escape(label)}</name>\n")
        parts.append(f"    <desc>{escape(desc)}</desc>\n")
        parts.append(f"    <cmt>{escape(name)}</cmt>\n")
        parts.append("    <sym>Scenic Area</sym>\n")
        parts.append("  </wpt>\n")
    idx = gpx_text.rfind("</gpx>")
    if idx < 0:
        return gpx_text
    return gpx_text[:idx] + "".join(parts) + gpx_text[idx:]


@app.get("/api/projects/{project_id}/export",
         dependencies=[Depends(require_api_key)])
async def export_project_with_pois(project_id: str):
    """导出 GPX 文本；?pois=1 时把地名点并入。"""
    try:
        meta = project_store.get(project_id)
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail="项目不存在") from None
    try:
        gpx_text = project_store.read_gpx(project_id)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from None
    cached = project_store.load_pois(project_id)
    if cached and cached.get("items"):
        gpx_text = _merge_pois_into_gpx(gpx_text, cached["items"])
    fname = f"{_safe_name(meta.get('name') or project_id)}.gpx"
    # 文件名常含中文，HTTP 头只能是 latin-1，必须按 RFC 5987 做 UTF-8 百分号编码
    from urllib.parse import quote
    disposition = ("attachment; filename=track.gpx; filename*=UTF-8''"
                   + quote(fname))
    return Response(content=gpx_text, media_type="application/gpx+xml",
                    headers={"Content-Disposition": disposition})


@app.get("/api/projects/{project_id}/download",
         dependencies=[Depends(require_api_key)])
async def download_project(project_id: str):
    """下载项目产物 GPX。"""
    try:
        meta = project_store.get(project_id)
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail="项目不存在") from None
    path = project_store.output_path(project_id)
    if not path.is_file():
        raise HTTPException(status_code=410, detail="产物已被清理，请重新转换")
    fname = meta.get("name") or project_id
    return FileResponse(path=str(path), media_type="application/gpx+xml",
                        filename=f"{_safe_name(fname)}.gpx")


def _safe_name(name: str) -> str:
    keep = [c for c in name if c.isalnum() or c in "-_"]
    return "".join(keep)[:80] or "track"


# 静态前端（构建时复制到 web/）
#
# 同时挂载到 "/" 和 "/gpx" 两个前缀：
#   - 直接访问 http://host:8000/          -> /         （容器内直连、本地开发）
#   - 经 Caddy 反代 http://host/gpx/...   -> /gpx/...  （生产入口，避免与门户主页抢根路径）
# 前端内部的绝对路径引用（fetch('/api/...')）不受前缀影响，因为 /api/* 始终挂在根上。
static_dir = Path(__file__).resolve().parent.parent / "web"
if static_dir.is_dir():
    _web = StaticFiles(directory=str(static_dir), html=True)
    app.mount("/gpx", _web, name="web_gpx")
    app.mount("/", _web, name="web")
