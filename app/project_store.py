"""项目空间：每次转换落一个目录 + 一条账本记录，可回看、可重转、可删除。

设计取舍（见 docs/NEXT-ITERATIONS.md 第 2 节）：

* **目录存文件，SQLite 存索引**。历史列表要筛选/分页/按时间排序，
  扫目录会随项目数线性变慢；元数据放账本，文件放目录，各司其职。
* **保留原始输入**。重转必须能拿到原件，否则「改个参数再试」就无从谈起。
* **与瓦片任务解耦**。一个项目可关联 0..N 个地图生成任务，但不合表 ——
  两者的生命周期与清理策略完全不同。
"""
from __future__ import annotations

import json
import logging
import shutil
import sqlite3
import time
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

STATUS_DONE = "completed"
STATUS_FAILED = "failed"


class ProjectNotFoundError(LookupError):
    """项目不存在。"""


def _now() -> float:
    return time.time()


class ProjectStore:
    def __init__(self, settings):
        self.settings = settings
        self.root = Path(settings.data_dir)
        self._projects_dir = self.root / "projects"
        self._projects_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = self.root / "projects.db"
        self._init_db()

    # ---------- 底层 ----------
    def _conn(self):
        return sqlite3.connect(str(self._db_path))

    def _init_db(self):
        conn = self._conn()
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS projects ("
                " id TEXT PRIMARY KEY,"
                " created_at REAL NOT NULL,"
                " updated_at REAL NOT NULL,"
                " name TEXT,"
                " source_name TEXT,"
                " ext TEXT,"
                " status TEXT,"
                " error TEXT,"
                " params TEXT,"
                " point_count INTEGER DEFAULT 0,"
                " waypoint_count INTEGER DEFAULT 0,"
                " distance_m REAL DEFAULT 0,"
                " ai_used INTEGER DEFAULT 0,"
                " ai_named INTEGER DEFAULT 0)")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_projects_created"
                " ON projects(created_at DESC)")
            conn.commit()
        finally:
            conn.close()

    def project_dir(self, project_id: str) -> Path:
        return self._projects_dir / project_id

    def input_path(self, project_id: str, ext: str) -> Path:
        return self.project_dir(project_id) / f"input{ext}"

    def output_path(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "output.gpx"

    def pois_path(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "pois.json"

    def save_pois(self, project_id: str, payload: dict) -> None:
        """把地名补点结果缓存到项目目录。"""
        self.project_dir(project_id).mkdir(parents=True, exist_ok=True)
        self.pois_path(project_id).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def load_pois(self, project_id: str):
        """读缓存；不存在返回 None。"""
        path = self.pois_path(project_id)
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def clear_pois(self, project_id: str) -> None:
        try:
            self.pois_path(project_id).unlink()
        except OSError:
            pass

    # ---------- 写入 ----------
    def save(self, *, source_bytes: bytes, source_name: str, ext: str,
             result, params: dict) -> dict:
        """落一个项目：原件 + 产物 + 摘要。返回项目元数据。"""
        project_id = uuid.uuid4().hex
        d = self.project_dir(project_id)
        d.mkdir(parents=True, exist_ok=True)

        suffix = ext if ext.startswith(".") else "." + ext
        with open(self.input_path(project_id, suffix), "wb") as fh:
            fh.write(source_bytes)

        if result is not None:
            self.output_path(project_id).write_text(result.gpx, encoding="utf-8")
            summary = result.summary.to_dict()
            (d / "summary.json").write_text(
                json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
            gpx_name = result.filename
            status, error = STATUS_DONE, ""
            tracks = summary.get("tracks") or [{}]
            name = tracks[0].get("name") or source_name
            point_count = summary.get("point_count", 0)
            waypoint_count = summary.get("waypoint_count", 0)
            distance_m = summary.get("distance_m", 0.0)
            ai_used = 1 if summary.get("ai_used") else 0
            ai_named = summary.get("ai_named", 0)
        else:
            gpx_name = ""
            status, error = STATUS_FAILED, params.get("error", "")
            name = source_name
            point_count = waypoint_count = ai_named = 0
            distance_m = 0.0
            ai_used = 0

        meta = {
            "id": project_id,
            "created_at": _now(),
            "name": name,
            "source_name": source_name,
            "ext": suffix,
            "status": status,
            "error": error,
            "params": params,
            "point_count": point_count,
            "waypoint_count": waypoint_count,
            "distance_m": distance_m,
            "ai_used": ai_used,
            "ai_named": ai_named,
            "gpx_filename": gpx_name,
        }
        (d / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        self._insert(meta)
        self.prune()
        return meta

    def _insert(self, meta: dict):
        conn = self._conn()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO projects (id, created_at, updated_at, name,"
                " source_name, ext, status, error, params, point_count,"
                " waypoint_count, distance_m, ai_used, ai_named)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (meta["id"], meta["created_at"], _now(), meta["name"],
                 meta["source_name"], meta["ext"], meta["status"],
                 meta["error"], json.dumps(meta["params"], ensure_ascii=False),
                 meta["point_count"], meta["waypoint_count"],
                 meta["distance_m"], meta["ai_used"], meta["ai_named"]))
            conn.commit()
        finally:
            conn.close()

    # ---------- 读取 ----------
    @staticmethod
    def _row_to_dict(row, cols) -> dict:
        d = dict(zip(cols, row))
        try:
            d["params"] = json.loads(d.get("params") or "{}")
        except (TypeError, ValueError):
            d["params"] = {}
        d["ai_used"] = bool(d.get("ai_used"))
        return d

    def list(self, limit: int = 50, offset: int = 0) -> dict:
        cols = ("id, created_at, name, source_name, ext, status, point_count,"
                " waypoint_count, distance_m, ai_used, ai_named")
        conn = self._conn()
        try:
            total = conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
            rows = conn.execute(
                f"SELECT {cols} FROM projects ORDER BY created_at DESC"
                " LIMIT ? OFFSET ?", (int(limit), int(offset))).fetchall()
        finally:
            conn.close()
        col_names = [c.strip() for c in cols.split(",")]
        return {"total": total, "items": [self._row_to_dict(r, col_names) for r in rows]}

    def get(self, project_id: str) -> dict:
        cols = ("id, created_at, name, source_name, ext, status, error, params,"
                " point_count, waypoint_count, distance_m, ai_used, ai_named")
        conn = self._conn()
        try:
            row = conn.execute(
                f"SELECT {cols} FROM projects WHERE id = ?", (project_id,)).fetchone()
        finally:
            conn.close()
        if row is None:
            raise ProjectNotFoundError(project_id)
        meta = self._row_to_dict(row, [c.strip() for c in cols.split(",")])
        summary_path = self.project_dir(project_id) / "summary.json"
        if summary_path.is_file():
            try:
                meta["summary"] = json.loads(summary_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                meta["summary"] = None
        else:
            meta["summary"] = None
        out = self.output_path(project_id)
        meta["gpx_available"] = out.is_file()
        meta["input_available"] = any(
            self.project_dir(project_id).glob("input.*"))
        return meta

    def read_gpx(self, project_id: str) -> str:
        self.get(project_id)          # 不存在会抛
        path = self.output_path(project_id)
        if not path.is_file():
            raise ProjectNotFoundError(f"{project_id} 的 GPX 已被清理")
        return path.read_text(encoding="utf-8")

    # ---------- 删除与清理 ----------
    def delete(self, project_id: str) -> bool:
        conn = self._conn()
        try:
            cur = conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            conn.commit()
            existed = cur.rowcount > 0
        finally:
            conn.close()
        shutil.rmtree(self.project_dir(project_id), ignore_errors=True)
        return existed

    def prune(self) -> int:
        """按条数上限与保留天数淘汰。返回删除数量。"""
        max_projects = getattr(self.settings, "max_projects", 200)
        retention_days = getattr(self.settings, "project_retention_days", 30)
        doomed = []

        conn = self._conn()
        try:
            if max_projects > 0:
                rows = conn.execute(
                    "SELECT id FROM projects ORDER BY created_at DESC"
                    " LIMIT -1 OFFSET ?", (int(max_projects),)).fetchall()
                doomed.extend(r[0] for r in rows)
            if retention_days > 0:
                cutoff = _now() - retention_days * 86400
                rows = conn.execute(
                    "SELECT id FROM projects WHERE created_at < ?",
                    (cutoff,)).fetchall()
                doomed.extend(r[0] for r in rows)
        finally:
            conn.close()

        removed = 0
        for pid in set(doomed):
            if self.delete(pid):
                removed += 1
        if removed:
            logger.info("pruned %d expired projects", removed)
        return removed
