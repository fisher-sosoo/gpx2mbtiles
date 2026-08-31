import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

# OGC GeoPackage 1.2
APPLICATION_ID = 0x47504B47  # "GPKG"
USER_VERSION = 10200

WORLD_MIN = -20037508.342789244
WORLD_MAX = 20037508.342789244
WORLD_WIDTH = WORLD_MAX - WORLD_MIN  # 40075016.685578488

# EPSG:3857 Web Mercator（与 GDAL 输出一致的权威定义）
WKT1_3857 = (
    'PROJCS["WGS 84 / Pseudo-Mercator",'
    'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563,'
    'AUTHORITY["EPSG","7030"]],AUTHORITY["EPSG","6326"]],'
    'PRIMEM["Greenwich",0,AUTHORITY["EPSG","8901"]],'
    'UNIT["degree",0.0174532925199433,AUTHORITY["EPSG","9122"]],'
    'AUTHORITY["EPSG","4326"]],'
    'PROJECTION["Mercator_1SP"],PARAMETER["central_meridian",0],'
    'PARAMETER["scale_factor",1],PARAMETER["false_easting",0],'
    'PARAMETER["false_northing",0],UNIT["metre",1,AUTHORITY["EPSG","9001"]],'
    'AXIS["X",EAST],AXIS["Y",NORTH],'
    'EXTENSION["PROJ4","+proj=merc +a=6378137 +b=6378137 +lat_ts=0 +lon_0=0 '
    '+x_0=0 +y_0=0 +k=1 +units=m +nadgrids=@null +wktext +no_defs"],'
    'AUTHORITY["EPSG","3857"]]'
)

WKT2_3857 = (
    'PROJCRS["WGS 84 / Pseudo-Mercator",'
    'BASEGEOGCRS["WGS 84",'
    'ENSEMBLE["World Geodetic System 1984 ensemble",'
    'MEMBER["World Geodetic System 1984 (Transit)"],'
    'MEMBER["World Geodetic System 1984 (G730)"],'
    'MEMBER["World Geodetic System 1984 (G873)"],'
    'MEMBER["World Geodetic System 1984 (G1150)"],'
    'MEMBER["World Geodetic System 1984 (G1674)"],'
    'MEMBER["World Geodetic System 1984 (G1762)"],'
    'MEMBER["World Geodetic System 1984 (G2139)"],'
    'ELLIPSOID["WGS 84",6378137,298.257223563,LENGTHUNIT["metre",1]],'
    'ENSEMBLEACCURACY[2.0]],'
    'PRIMEM["Greenwich",0,ANGLEUNIT["degree",0.0174532925199433]],'
    'ID["EPSG",4326]],'
    'CONVERSION["Popular Visualisation Pseudo-Mercator",'
    'METHOD["Popular Visualisation Pseudo Mercator",ID["EPSG",1024]],'
    'PARAMETER["Latitude of natural origin",0,ANGLEUNIT["degree",0.0174532925199433],'
    'ID["EPSG",8801]],'
    'PARAMETER["Longitude of natural origin",0,ANGLEUNIT["degree",0.0174532925199433],'
    'ID["EPSG",8802]],'
    'PARAMETER["False easting",0,LENGTHUNIT["metre",1],ID["EPSG",8806]],'
    'PARAMETER["False northing",0,LENGTHUNIT["metre",1],ID["EPSG",8807]]],'
    'CS[Cartesian,2],'
    'AXIS["easting (X)",east,ORDER[1],LENGTHUNIT["metre",1]],'
    'AXIS["northing (Y)",north,ORDER[2],LENGTHUNIT["metre",1]],'
    'ID["EPSG",3857]]'
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class GpkgBuilder:
    """按 OGC GeoPackage 1.2 规范把 XYZ 瓦片写入 SQLite（3857 瓦片金字塔）。

    注意：GeoPackage 的 tile_row 与 XYZ 的 y 一致（行 0 在北侧），
    与 MBTiles 的 TMS 翻转不同，无需换算。
    """

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path))
        self._conn.execute("PRAGMA application_id = %d" % APPLICATION_ID)
        self._conn.execute("PRAGMA user_version = %d" % USER_VERSION)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA foreign_keys=OFF")
        self._create_schema()
        self._conn.commit()
        self._buffer = []
        self._written = []  # (z, x, y) XYZ 已写入
        self._closed = False

    def _create_schema(self):
        c = self._conn
        c.execute(
            "CREATE TABLE gpkg_spatial_ref_sys ("
            "srs_name TEXT NOT NULL, srs_id INTEGER NOT NULL PRIMARY KEY,"
            "organization TEXT NOT NULL, organization_coordsys_id INTEGER NOT NULL,"
            "definition TEXT NOT NULL, description TEXT)")
        c.execute(
            "CREATE TABLE gpkg_contents ("
            "table_name TEXT NOT NULL PRIMARY KEY, data_type TEXT NOT NULL,"
            "identifier TEXT UNIQUE, description TEXT DEFAULT '',"
            "last_change DATETIME NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),"
            "min_x DOUBLE, min_y DOUBLE, max_x DOUBLE, max_y DOUBLE,"
            "srs_id INTEGER,"
            "CONSTRAINT fk_gc_r_srs_id FOREIGN KEY (srs_id)"
            " REFERENCES gpkg_spatial_ref_sys(srs_id))")
        c.execute(
            "CREATE TABLE gpkg_tile_matrix_set ("
            "table_name TEXT NOT NULL PRIMARY KEY, srs_id INTEGER NOT NULL,"
            "min_x DOUBLE NOT NULL, min_y DOUBLE NOT NULL,"
            "max_x DOUBLE NOT NULL, max_y DOUBLE NOT NULL,"
            "CONSTRAINT fk_gtms_table_name FOREIGN KEY (table_name)"
            " REFERENCES gpkg_contents(table_name),"
            "CONSTRAINT fk_gtms_srs FOREIGN KEY (srs_id)"
            " REFERENCES gpkg_spatial_ref_sys(srs_id))")
        c.execute(
            "CREATE TABLE gpkg_tile_matrix ("
            "table_name TEXT NOT NULL, zoom_level INTEGER NOT NULL,"
            "matrix_width INTEGER NOT NULL, matrix_height INTEGER NOT NULL,"
            "tile_width INTEGER NOT NULL, tile_height INTEGER NOT NULL,"
            "pixel_x_size DOUBLE NOT NULL, pixel_y_size DOUBLE NOT NULL,"
            "CONSTRAINT pk_ttm PRIMARY KEY (table_name, zoom_level),"
            "CONSTRAINT fk_tmm_table_name FOREIGN KEY (table_name)"
            " REFERENCES gpkg_contents(table_name))")
        c.execute(
            "CREATE TABLE tiles ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "zoom_level INTEGER NOT NULL, tile_column INTEGER NOT NULL,"
            "tile_row INTEGER NOT NULL, tile_data BLOB NOT NULL,"
            "UNIQUE (zoom_level, tile_column, tile_row))")

    def add_tile(self, z: int, x: int, y: int, data: bytes) -> None:
        self._buffer.append((z, x, y, data))
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
    def _tile_wgs84_bounds(z: int, x: int, y: int):
        """XYZ 瓦片 WGS84 边界 (min_lon, min_lat, max_lon, max_lat)。"""
        n = 1 << z
        min_lon = x / n * 360.0 - 180.0
        max_lon = (x + 1) / n * 360.0 - 180.0
        lat_north = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
        lat_south = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
        return (min_lon, min(lat_north, lat_south), max_lon, max(lat_north, lat_south))

    @staticmethod
    def _tile_meter_bounds(z: int, x: int, y: int):
        """XYZ 瓦片 Web Mercator 米边界 (min_x, min_y, max_x, max_y)。"""
        tile_m = WORLD_WIDTH / (1 << z)
        min_x = WORLD_MIN + x * tile_m
        max_x = min_x + tile_m
        max_y = WORLD_MAX - y * tile_m
        min_y = max_y - tile_m
        return (min_x, min_y, max_x, max_y)

    def finalize(self, name: str, min_zoom: int, max_zoom: int,
                 fallback_bounds) -> tuple:
        """写入 gpkg_contents/gpkg_spatial_ref_sys/金字塔并关闭。
        返回 (瓦片数, WGS84 bounds)，与 MbtilesBuilder 接口一致。"""
        self.flush()
        count = len(self._written)

        # WGS84 边界（对外）
        wgs84 = self._wgs84_bounds() if count else fallback_bounds
        # 米制边界（gpkg_contents 内部）
        if count:
            m = [self._tile_meter_bounds(z, x, y) for z, x, y in self._written]
            min_x = min(t[0] for t in m)
            min_y = min(t[1] for t in m)
            max_x = max(t[2] for t in m)
            max_y = max(t[3] for t in m)
        else:
            min_x = min_y = WORLD_MIN
            max_x = max_y = WORLD_MAX

        c = self._conn
        c.execute(
            "INSERT INTO gpkg_spatial_ref_sys (srs_name, srs_id, organization,"
            " organization_coordsys_id, definition, description)"
            " VALUES (?,?,?,?,?,?)",
            ("WGS 84 / Pseudo-Mercator", 3857, "EPSG", 3857, WKT1_3857,
             "Web Mercator (Windy Outdoor tiles)"))
        c.execute(
            "INSERT INTO gpkg_contents (table_name, data_type, identifier,"
            " description, last_change, min_x, min_y, max_x, max_y, srs_id)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("tiles", "tiles", name or "tiles", name or "", _now_iso(),
             min_x, min_y, max_x, max_y, 3857))
        c.execute(
            "INSERT INTO gpkg_tile_matrix_set (table_name, srs_id, min_x, min_y,"
            " max_x, max_y) VALUES (?,?,?,?,?,?)",
            ("tiles", 3857, WORLD_MIN, WORLD_MIN, WORLD_MAX, WORLD_MAX))
        pixel = WORLD_WIDTH / (256.0)  # 每 zoom 的像素尺寸由矩阵宽度决定
        for z in range(min_zoom, max_zoom + 1):
            n = 1 << z
            p = WORLD_WIDTH / (n * 256.0)
            c.execute(
                "INSERT INTO gpkg_tile_matrix (table_name, zoom_level, matrix_width,"
                " matrix_height, tile_width, tile_height, pixel_x_size, pixel_y_size)"
                " VALUES (?,?,?,?,?,?,?,?)",
                ("tiles", z, n, n, 256, 256, p, p))
        c.execute(
            "UPDATE gpkg_contents SET last_change = ? WHERE table_name = 'tiles'",
            (_now_iso(),))
        self._conn.commit()
        self._conn.close()
        self._closed = True
        return count, wgs84

    def _wgs84_bounds(self):
        min_lon, min_lat, max_lon, max_lat = 180.0, 90.0, -180.0, -90.0
        for z, x, y in self._written:
            lo, la, hi, ha = self._tile_wgs84_bounds(z, x, y)
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
