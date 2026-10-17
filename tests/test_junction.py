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