import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .gpx_processor import GpxParseError, build_tile_plan, parse_gpx
from .task_manager import (COMPLETED, TaskLimitError, TaskManager,
                           TaskNotFoundError)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("gpx2mbtiles")

settings = get_settings()
manager: TaskManager


@asynccontextmanager
async def lifespan(app: FastAPI):
    global manager
    manager = TaskManager(settings)
    manager.start()
    cleanup_task = asyncio.create_task(manager.cleanup_loop())
    app.state.manager = manager
    logger.info("gpx2mbtiles started: data_dir=%s max_running=%d interval=%dms",
                settings.data_dir, settings.max_running_tasks, settings.request_interval_ms)
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
    """AUTH_TOKEN 为空时放行；否则要求 X-API-Key 或 Bearer 鉴权。"""
    if not settings.auth_token:
        return True
    supplied = request.headers.get("X-API-Key") or ""
    auth = request.headers.get("Authorization") or ""
    if supplied != settings.auth_token and auth != f"Bearer {settings.auth_token}":
        raise HTTPException(status_code=401, detail="需要 API Key（X-API-Key 请求头）")
    return True


@app.get("/api/health")
async def health():
    return {"status": "ok", "max_running": settings.max_running_tasks}


@app.post("/api/submit", dependencies=[Depends(require_api_key)])
async def submit(
    file: UploadFile = File(...),
    buffer_meters: float = Form(2500),
    min_zoom: int = Form(8),
    max_zoom: int = Form(17),
    concurrency: int = Form(0),
    interval_ms: int = Form(0),
    output_format: str = Form("gpkg"),
    allow_oversize: bool = Form(False),
):
    """提交任务：上传 GPX + 参数，返回 task_id。"""
    filename = file.filename or "track.gpx"
    if not filename.lower().endswith((".gpx", ".xml")):
        raise HTTPException(status_code=400, detail="仅支持 .gpx 文件")
    gpx_data = await file.read()
    if len(gpx_data) > settings.max_gpx_bytes:
        raise HTTPException(status_code=413,
                            detail=f"GPX 文件过大（限制 {settings.max_gpx_bytes // (1024*1024)}MB）")
    if not gpx_data.strip():
        raise HTTPException(status_code=400, detail="GPX 文件为空")
    # 提前校验格式，失败不建任务
    try:
        from .gpx_processor import parse_gpx
        parse_gpx(gpx_data)
    except GpxParseError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    output_format = output_format.strip().lower()
    if output_format not in ("gpkg", "mbtiles"):
        return JSONResponse(status_code=400,
                            content={"detail": "output_format 仅支持 gpkg 或 mbtiles"})
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
        "allow_oversize": allow_oversize_b,
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
    filename = f"{_safe_name(task.name)}.{ext}"
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
    if not filename.lower().endswith((".gpx", ".xml")):
        raise HTTPException(status_code=400, detail="仅支持 .gpx 文件")
    gpx_data = await file.read()
    if len(gpx_data) > settings.max_gpx_bytes:
        raise HTTPException(status_code=413,
                            detail=f"GPX 文件过大（限制 {settings.max_gpx_bytes // (1024*1024)}MB）")
    try:
        points, _ = parse_gpx(gpx_data)
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


def _safe_name(name: str) -> str:
    keep = [c for c in name if c.isalnum() or c in "-_"]
    return "".join(keep)[:80] or "track"


# 静态前端（构建时复制到 web/）
static_dir = Path(__file__).resolve().parent.parent / "web"
if static_dir.is_dir():
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="web")
