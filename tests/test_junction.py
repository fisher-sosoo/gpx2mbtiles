"""岔路判定与转向分类的纯逻辑测试（不联网）。"""
import pytest

from app import junction_finder as jf
from app import kml_naming as kn


def _ways():
    # 两条在 (24.0, 113.0) 附近交汇的路
    return [
        {"id": 1, "verts": [(24.0000, 112.9990), (24.0000, 113.0000),
                            (24.0000, 113.0010)]},
        {"id": 2, "verts": [(23.9990, 113.0000), (24.0000, 113.0000),
                            (24.0010, 113.0000)]},
        {"id": 3, "verts": [(24.2000, 113.2000), (24.2010, 113.2000)]},
    ]


def _pts():
    return [(24.0000, 112.9990, 0.0),
            (24.0000, 113.0000, 100.0),
            (24.0000, 113.0010, 200.0)]


class TestQuery:
    def test_query_only_asks_for_highways(self):
        q = jf.build_query((24.0, 113.0, 24.1, 113.1), 60)
        assert "highway" in q
        assert "out geom" in q
        assert "peak" not in q and "natural" not in q

    def test_query_has_timeout(self):
        assert "timeout:60" in jf.build_query((24.0, 113.0, 24.1, 113.1), 60)


class TestFindJunctions:
    def test_meeting_of_two_roads_is_a_junction(self):
        out = jf.find_junctions(_pts(), _ways())
        assert len(out) == 1
        assert out[0]["way_count"] >= 2

    def test_single_road_is_not_a_junction(self):
        only = [{"id": 1, "verts": [(24.0, 112.9990), (24.0, 113.0000)]}]
        assert jf.find_junctions(_pts(), only) == []

    def test_far_road_does_not_count(self):
        far = [{"id": 1, "verts": [(24.0, 112.9990), (24.0, 113.0000)]},
               {"id": 9, "verts": [(24.01, 113.0), (24.02, 113.0)]}]
        assert jf.find_junctions(_pts(), far) == []

    def test_adjacent_points_merge_into_one(self):
        pts = [(24.0, 113.0 - i * 0.00002, i * 20.0) for i in range(5)]
        out = jf.find_junctions(pts, _ways())
        assert len(out) == 1, "同一处路口不该刷出多条"

    def test_distance_recorded(self):
        out = jf.find_junctions(_pts(), _ways())
        assert out[0]["distance_m"] is not None
        assert 0 <= out[0]["distance_m"] <= 200

    def test_empty_inputs(self):
        assert jf.find_junctions([], _ways()) == []
        assert jf.find_junctions(_pts(), []) == []


class TestNearest:
    def test_within_tolerance(self):
        j = [{"lat": 24.0, "lon": 113.0}]
        got, dist = jf.nearest_junction(24.0001, 113.0001, j, 40.0)
        assert got is not None and dist < 40

    def test_outside_tolerance(self):
        j = [{"lat": 24.0, "lon": 113.0}]
        got, dist = jf.nearest_junction(24.01, 113.01, j, 40.0)
        assert got is None and dist is None


class TestQuerySerialization:
    """Overpass 会掐断并发重查询，必须有全局串行锁与跨项目缓存。"""

    def test_overpass_lock_exists(self):
        from app import main as m
        assert hasattr(m, "_overpass_lock"), "缺少 Overpass 串行锁"

    def test_lock_is_single_permit(self):
        from app import main as m
        assert getattr(m._overpass_lock, "_value", 1) == 1

    def test_bbox_cache_rounds_to_neighbourhood(self):
        from app import main as m
        a = m._bbox_key((24.3571, 113.6112, 24.3860, 113.6470))
        b = m._bbox_key((24.3574, 113.6119, 24.3863, 113.6478))
        assert a == b, "邻近轨迹应命中同一条缓存"

    def test_bbox_cache_is_bounded(self):
        from app import main as m
        m._junction_bbox_cache.clear()
        for i in range(m._JUNCTION_CACHE_MAX + 10):
            m._junction_cache_put((20 + i, 100, 21 + i, 101), [], 0)
        assert len(m._junction_bbox_cache) <= m._JUNCTION_CACHE_MAX
        m._junction_bbox_cache.clear()

    def test_cache_put_get(self):
        from app import main as m
        m._junction_bbox_cache.clear()
        js = [{"lat": 24.0, "lon": 113.0, "way_count": 3, "distance_m": 10.0}]
        m._junction_cache_put((24.0, 113.0, 24.1, 113.1), js, 5)
        got = m._junction_cache_get((24.0, 113.0, 24.1, 113.1))
        assert got and got["way_count"] == 5
        assert got["junctions"] == js
        m._junction_bbox_cache.clear()


class TestTrackStatsTolerance:
    """重算路径会传 (lat, lon) 元组，track_stats 必须都能吃。"""

    def test_accepts_tuples(self):
        pts = [(24.0, 113.0), (24.001, 113.0), (24.002, 113.0)]
        st = kn.track_stats(pts)
        assert len(st.cum) == 3
        assert st.distance_m > 200

    def test_accepts_objects(self):
        class P:
            def __init__(self, la, lo):
                self.lat, self.lon = la, lo
        pts = [P(24.0, 113.0), P(24.001, 113.0)]
        assert kn.track_stats(pts).distance_m > 100

    def test_tuples_and_objects_agree(self):
        class P:
            def __init__(self, la, lo):
                self.lat, self.lon = la, lo
        a = kn.track_stats([(24.0, 113.0), (24.002, 113.002)]).distance_m
        b = kn.track_stats([P(24.0, 113.0), P(24.002, 113.002)]).distance_m
        assert abs(a - b) < 0.01


class TestApplyJunctions:
    def _names(self):
        n1 = kn.WaypointName(text="#01 a", source="position", km=0.100,
                             turn=70.0, turn_text="右转70°")
        n2 = kn.WaypointName(text="#02 b", source="position", km=5.000,
                             turn=-80.0, turn_text="左转80°")
        return [n1, n2]

    def test_turn_near_junction_upgraded(self):
        names = self._names()
        js = [{"lat": 24.0, "lon": 113.0, "way_count": 3, "distance_m": 110.0}]
        got = kn.apply_junctions(names, js, tol_m=40.0)
        assert got == 1
        assert names[0].turn_text.startswith("岔路口")
        assert names[0].turn_kind == "junction"
        assert names[0].junction_ways == 3

    def test_default_tolerance_covers_real_sampling_gap(self):
        """真实数据里路口与航点能差 170 米左右，默认容差必须覆盖。"""
        names = self._names()          # 航点在 km=0.100 (100 m)
        js_far = [{"lat": 24.0, "lon": 113.0, "way_count": 2, "distance_m": 400.0}]
        assert kn.apply_junctions(names, js_far) == 0, "300m 超出默认容差"
        js_near = [{"lat": 24.0, "lon": 113.0, "way_count": 2, "distance_m": -60.0}]
        assert kn.apply_junctions(names, js_near) == 1, "160m 应在默认容差内"

    def test_turn_far_from_junction_is_terrain(self):
        names = self._names()
        js = [{"lat": 24.0, "lon": 113.0, "way_count": 3, "distance_m": 110.0}]
        kn.apply_junctions(names, js, tol_m=40.0)
        assert names[1].turn_kind == "terrain"
        assert not names[1].turn_text.startswith("岔路口")

    def test_no_junctions_leaves_text_alone(self):
        names = self._names()
        assert kn.apply_junctions(names, []) == 0
        assert names[0].turn_text == "右转70°"

    def test_waypoint_without_turn_untouched(self):
        n = kn.WaypointName(text="#03 c", source="position", km=0.1)
        js = [{"lat": 24.0, "lon": 113.0, "way_count": 3, "distance_m": 100.0}]
        assert kn.apply_junctions([n], js) == 0
        assert n.turn_text == ""