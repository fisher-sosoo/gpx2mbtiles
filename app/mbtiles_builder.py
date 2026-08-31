import math
import sqlite3
from pathlib import Path


class MbtilesBuilder:
    """按 MBTiles 1.0 规范把 XYZ 瓦片写入 SQLite（内部行号按 TMS 翻转）。"""

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("CREATE TABLE metadata (name TEXT, value TEXT)")
        self._conn.execute(
            "CREATE TABLE tiles ("
            "zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB)")
        self._conn.execute(
            "CREATE UNIQUE INDEX tile_index ON tiles (zoom_level, tile_column, tile_row)")
        self._conn.commit()
        self._buffer = []
        self._written = []
        self._closed = False

    def add_tile(self, z: int, x: int, y: int, data: bytes) -> None:
        tms_y = (1 << z) - 1 - y
        self._buffer.append((z, x, tms_y, data))
        self._written.append((z, x, y))
        if len(self._buffer) >= 200:
            self.flush()

    def flush(self) -> None:
        if not self._buffer:
            return
        self._conn.executemany(
            "INSERT OR REPLACE INTO tiles (zoom_level, tile_column, tile_row, tile_data) "
            "VALUES (?, ?, ?, ?)",
            self._buffer)
        self._conn.commit()
        self._buffer.clear()

    @staticmethod
    def _tile_bounds(z: int, x: int, y: int):
        n = 1 << z
        min_lon = x / n * 360.0 - 180.0
        max_lon = (x + 1) / n * 360.0 - 180.0
        lat_north = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
        lat_south = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
        return (min_lon, min(lat_north, lat_south), max_lon, max(lat_north, lat_south))

    def finalize(self, name: str, min_zoom: int, max_zoom: int,
                 fallback_bounds) -> tuple:
        self.flush()
        count = len(self._written)
        bounds = self.compute_bounds() if count else fallback_bounds
        meta = {
            "name": name,
            "format": "png",
            "minzoom": str(min_zoom),
            "maxzoom": str(max_zoom),
            "bounds": ",".join(f"{v:.6f}" for v in bounds),
            "version": "1.0",
        }
        self._conn.executemany(
            "INSERT INTO metadata (name, value) VALUES (?, ?)", list(meta.items()))
        self._conn.commit()
        self._conn.close()
        self._closed = True
        return count, bounds

    def compute_bounds(self):
        if not self._written:
            return (-180.0, -85.0, 180.0, 85.0)
        min_lon, min_lat, max_lon, max_lat = 180.0, 90.0, -180.0, -90.0
        for z, x, y in self._written:
            lo, la, hi, ha = self._tile_bounds(z, x, y)
            min_lon = min(min_lon, lo)
            min_lat = min(min_lat, la)
            max_lon = max(max_lon, hi)
            max_lat = max(max_lat, ha)
        return (min_lon, min_lat, max_lon, max_lat)

    def abort(self) -> None:
        if not self._closed:
            try:
                self._conn.close()
            except Exception:
                pass
            self._closed = True
        try:
            if self.path.exists():
                self.path.unlink()
        except OSError:
            pass
        for suffix in ("-wal", "-shm"):
            p = Path(str(self.path) + suffix)
            try:
                if p.exists():
                    p.unlink()
            except OSError:
                pass
