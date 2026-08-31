import pytest

from app.gpx_processor import GpxParseError, build_tile_plan, parse_gpx
from tests.conftest import make_gpx


class TestParseGpx:
    def test_empty_bytes(self):
        with pytest.raises(GpxParseError, match="为空"):
            parse_gpx(b"")

    def test_invalid_xml(self):
        with pytest.raises(GpxParseError, match="解析失败"):
            parse_gpx(b"this is not xml")

    def test_no_points(self):
        gpx = '<?xml version="1.0"?><gpx version="1.1" creator="t" xmlns="http://www.topografix.com/GPX/1/1"></gpx>'
        with pytest.raises(GpxParseError, match="未找到有效轨迹点"):
            parse_gpx(gpx.encode())

    def test_valid_track(self):
        points, name = parse_gpx(make_gpx([(39.9, 116.4), (39.91, 116.41)]).encode())
        assert len(points) == 2
        assert name == "test-track"
        assert points[0] == (39.9, 116.4)

    def test_invalid_coords_filtered(self):
        gpx = make_gpx([(99.0, 116.4), (39.9, 116.4)])  # 99.0 纬度非法
        points, _ = parse_gpx(gpx.encode())
        assert points == [(39.9, 116.4)]

    def test_route_and_waypoint(self):
        gpx = """<?xml version="1.0"?>
<gpx version="1.1" creator="t" xmlns="http://www.topografix.com/GPX/1/1">
  <rte><rtept lat="40.0" lon="117.0"/></rte>
  <wpt lat="40.1" lon="117.1"/>
</gpx>"""
        points, _ = parse_gpx(gpx.encode())
        assert sorted(points) == [(40.0, 117.0), (40.1, 117.1)]


class TestBuildTilePlan:
    def test_single_point_zero_buffer_z0(self):
        plan = build_tile_plan([(39.9, 116.4)], 0.0, 0, 0, 100)
        assert plan.tiles == [(0, 0, 0)]

    def test_dedup(self):
        plan = build_tile_plan([(39.9, 116.4), (39.9, 116.4)], 0.0, 0, 0, 100)
        assert len(plan.tiles) == 1

    def test_buffer_expands_at_zoom(self):
        # 同一中心点，buffer 越大瓦片越多
        small = build_tile_plan([(39.9, 116.4)], 10, 15, 15, 10000)
        big = build_tile_plan([(39.9, 116.4)], 2000, 15, 15, 10000)
        assert len(big.tiles) > len(small.tiles)

    def test_min_zoom_greater_than_max(self):
        with pytest.raises(GpxParseError, match="不能大于"):
            build_tile_plan([(39.9, 116.4)], 0.0, 5, 4, 100)

    def test_max_tiles_limit(self):
        with pytest.raises(GpxParseError, match="上限"):
            build_tile_plan([(39.9, 116.4)], 5000, 12, 16, 100)

    def test_bounds_computed(self):
        plan = build_tile_plan([(39.9, 116.4), (40.0, 117.0)], 0.0, 10, 10, 1000)
        w, s, e, n = plan.bounds
        assert abs(w - 116.4) < 0.01 and abs(s - 39.9) < 0.01
        assert abs(e - 117.0) < 0.01 and abs(n - 40.0) < 0.01

    def test_tiles_sorted(self):
        plan = build_tile_plan([(39.9, 116.4), (40.0, 117.0)], 500, 12, 13, 50000)
        assert plan.tiles == sorted(plan.tiles)


class TestMbtilesBuilder:
    def test_roundtrip_and_metadata(self, tmp_path):
        from app.mbtiles_builder import MbtilesBuilder
        import sqlite3
        p = tmp_path / "out.mbtiles"
        b = MbtilesBuilder(p)
        b.add_tile(0, 0, 0, b"png-data")
        count, bounds = b.finalize("mytrack", 0, 0, (-180.0, -85.0, 180.0, 85.0))
        assert count == 1
        conn = sqlite3.connect(str(p))
        # tiles 表存在且行号已翻转为 TMS：z0 时 0-0-0 不变
        row = conn.execute(
            "SELECT zoom_level, tile_column, tile_row, tile_data FROM tiles").fetchone()
        assert row[0:3] == (0, 0, 0)
        assert row[3] == b"png-data"
        # metadata 完整
        meta = dict(conn.execute("SELECT name, value FROM metadata").fetchall())
        assert meta["name"] == "mytrack"
        assert meta["format"] == "png"
        assert "type" not in meta
        assert meta["minzoom"] == "0"
        assert meta["maxzoom"] == "0"
        assert meta["version"] == "1.0"
        assert len(meta["bounds"].split(",")) == 4
        conn.close()

    def test_tms_row_flip(self, tmp_path):
        from app.mbtiles_builder import MbtilesBuilder
        import sqlite3
        p = tmp_path / "flip.mbtiles"
        b = MbtilesBuilder(p)
        b.add_tile(2, 0, 0, b"a")   # XYZ y=0 → TMS y=3
        b.add_tile(2, 0, 3, b"b")   # XYZ y=3 → TMS y=0
        b.finalize("t", 2, 2, (-180.0, -85.0, 180.0, 85.0))
        conn = sqlite3.connect(str(p))
        rows = dict((r[0], r[1]) for r in conn.execute(
            "SELECT tile_row, tile_data FROM tiles WHERE zoom_level=2").fetchall())
        assert rows == {3: b"a", 0: b"b"}
        conn.close()

    def test_computed_bounds_cover_globe_at_z0(self, tmp_path):
        from app.mbtiles_builder import MbtilesBuilder
        p = tmp_path / "b.mbtiles"
        b = MbtilesBuilder(p)
        b.add_tile(0, 0, 0, b"x")
        count, bounds = b.finalize("t", 0, 0, (-180.0, -85.0, 180.0, 85.0))
        w, s, e, n = bounds
        assert abs(w + 180.0) < 1e-6 and abs(e - 180.0) < 1e-6
        assert abs(s + 85.051) < 0.01 and abs(n - 85.051) < 0.01

    def test_abort_removes_file(self, tmp_path):
        from app.mbtiles_builder import MbtilesBuilder
        p = tmp_path / "abort.mbtiles"
        b = MbtilesBuilder(p)
        b.add_tile(0, 0, 0, b"x")
        b.abort()
        assert not p.exists()


class TestRateLimiter:
    def test_interval_enforced(self):
        import time
        from app.tile_downloader import RateLimiter
        import asyncio
        limiter = RateLimiter(0.05)

        async def run():
            stamps = []
            for _ in range(3):
                await limiter.wait()
                stamps.append(time.monotonic())
            return stamps
        stamps = asyncio.new_event_loop().run_until_complete(run())
        gaps = [b - a for a, b in zip(stamps, stamps[1:])]
        assert all(g >= 0.04 for g in gaps), f"gaps too small: {gaps}"




class TestGpkgBuilder:
    def test_schema_and_application_id(self, tmp_path):
        from app.gpkg_builder import GpkgBuilder
        import sqlite3
        p = tmp_path / "out.gpkg"
        b = GpkgBuilder(p)
        b.add_tile(10, 0, 0, b"png-data")
        count, bounds = b.finalize("mytrack", 10, 10, (-180.0, -85.0, 180.0, 85.0))
        assert count == 1
        conn = sqlite3.connect(str(p))
        assert conn.execute("PRAGMA application_id").fetchone()[0] == 0x47504B47
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"gpkg_contents", "gpkg_spatial_ref_sys",
                "gpkg_tile_matrix_set", "gpkg_tile_matrix", "tiles"} <= tables
        conn.close()

    def test_srs_and_contents(self, tmp_path):
        from app.gpkg_builder import GpkgBuilder
        import sqlite3
        p = tmp_path / "srs.gpkg"
        b = GpkgBuilder(p)
        b.add_tile(10, 0, 0, b"x")
        b.finalize("t", 10, 10, (-180.0, -85.0, 180.0, 85.0))
        conn = sqlite3.connect(str(p))
        srs = conn.execute(
            "SELECT srs_name, srs_id, organization, organization_coordsys_id"
            " FROM gpkg_spatial_ref_sys").fetchone()
        assert srs == ("WGS 84 / Pseudo-Mercator", 3857, "EPSG", 3857)
        row = conn.execute(
            "SELECT data_type, srs_id, min_x, min_y, max_x, max_y"
            " FROM gpkg_contents WHERE table_name='tiles'").fetchone()
        assert row[0] == "tiles" and row[1] == 3857
        # 内容边界在 Web Mercator 米制范围内
        assert -20037508.4 <= row[2] <= row[4] <= 20037508.4
        conn.close()

    def test_tile_row_not_flipped(self, tmp_path):
        """GeoPackage 行号与 XYZ 一致（行 0 在北），不做 TMS 翻转。"""
        from app.gpkg_builder import GpkgBuilder
        import sqlite3
        p = tmp_path / "flip.gpkg"
        b = GpkgBuilder(p)
        b.add_tile(2, 0, 0, b"north")  # XYZ y=0 最北
        b.add_tile(2, 0, 3, b"south")
        b.finalize("t", 2, 2, (-180.0, -85.0, 180.0, 85.0))
        conn = sqlite3.connect(str(p))
        rows = dict((r[0], r[1]) for r in conn.execute(
            "SELECT tile_row, tile_data FROM tiles").fetchall())
        assert rows == {0: b"north", 3: b"south"}
        conn.close()

    def test_tile_matrix_pyramid(self, tmp_path):
        from app.gpkg_builder import GpkgBuilder
        import sqlite3
        p = tmp_path / "pyramid.gpkg"
        b = GpkgBuilder(p)
        b.add_tile(12, 0, 0, b"a")
        b.finalize("t", 12, 14, (-180.0, -85.0, 180.0, 85.0))
        conn = sqlite3.connect(str(p))
        mats = conn.execute(
            "SELECT zoom_level, matrix_width, matrix_height, tile_width, tile_height,"
            " pixel_x_size, pixel_y_size FROM gpkg_tile_matrix ORDER BY zoom_level"
        ).fetchall()
        assert [m[0] for m in mats] == [12, 13, 14]
        for z, mw, mh, tw, th, px, py in mats:
            assert (mw, mh) == (1 << z, 1 << z)
            assert (tw, th) == (256, 256)
            assert abs(px - py) < 1e-12
        # 矩阵集为全球范围
        tms = conn.execute(
            "SELECT min_x, min_y, max_x, max_y FROM gpkg_tile_matrix_set"
        ).fetchone()
        assert tms[0] < tms[2] and tms[1] < tms[3]
        conn.close()

    def test_abort_removes_file(self, tmp_path):
        from app.gpkg_builder import GpkgBuilder
        p = tmp_path / "abort.gpkg"
        b = GpkgBuilder(p)
        b.add_tile(0, 0, 0, b"x")
        b.abort()
        assert not p.exists()


class TestBlockWatcher:
    def test_consecutive_triggers(self):
        from app.tile_downloader import BlockWatcher
        w = BlockWatcher(0.1, 15, 0.25, 3)
        w.record_blocked()
        w.record_blocked()
        assert not w.blocked
        w.record_blocked()
        assert w.blocked

    def test_ratio_triggers(self):
        from app.tile_downloader import BlockWatcher
        w = BlockWatcher(0.1, 3, 0.5, 100)
        w.record_success()
        w.record_blocked()
        w.record_success()
        w.record_blocked()
        w.record_blocked()
        assert w.blocked

    def test_success_resets_consecutive(self):
        from app.tile_downloader import BlockWatcher
        w = BlockWatcher(0.1, 15, 0.25, 3)
        w.record_blocked()
        w.record_blocked()
        w.record_success()
        w.record_blocked()
        w.record_blocked()
        assert not w.blocked
