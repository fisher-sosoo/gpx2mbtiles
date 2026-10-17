"""OSM 地名补点的过滤规则测试（纯逻辑，不联网）。"""
import pytest

from app.poi_enricher import (_crosses, _element_point, _point_seg_side,
                              _river_crossings, build_query, build_ways_query,
                              filter_pois)


def _node(lat, lon, tags):
    return {"type": "node", "lat": lat, "lon": lon, "tags": tags}


def _way(geom, tags):
    return {"type": "way", "geometry": [{"lat": a, "lon": b} for a, b in geom],
            "tags": tags}


class _Settings:
    poi_max_count = 60


def _track_north(n=60, lat0=24.0, lon=113.0, step=0.0002):
    """一条向北的直线轨迹（每步约 22m）。"""
    return [(lat0 + i * step, lon) for i in range(n)]


class TestQuery:
    def test_node_query_covers_key_types(self):
        """主查询只取节点：坐标自带，不需要几何，这是速度的关键。"""
        q = build_query((28.28, 100.29, 28.46, 100.57), 120)
        for needle in ('natural"="saddle', "mountain_pass", 'natural"="peak',
                       'natural"="water', "camp_site", "shelter", 'place"~'):
            assert needle in q, f"节点查询缺少: {needle}"
        assert "28.280000,100.290000,28.460000,100.570000" in q
        assert "out body" in q, "节点查询必须用 out body（out tags 不带坐标）"
        assert "out tags" not in q, "out tags 不返回坐标，会让所有点失效"
        assert "out geom" not in q, "主查询不该再拉几何（会慢一个数量级）"

    def test_ways_query_only_for_rivers(self):
        q = build_ways_query((28.28, 100.29, 28.46, 100.57), 60)
        assert "waterway" in q
        assert "out geom tags" in q, "河流要几何才能判过河"
        assert "peak" not in q, "河流查询不该夹带其它要素"


class TestOverpassRetry:
    """Overpass 的 5xx 是常态，必须退避重试；4xx 不该重试。"""

    class _S:
        poi_proxy = ""
        tile_proxy = ""
        poi_retry_max = 2

    def _boom(self, code):
        import urllib.error
        from io import BytesIO
        return urllib.error.HTTPError("u", code, "err", {}, BytesIO(b""))

    def test_retries_on_5xx_then_succeeds(self, monkeypatch):
        from app import poi_enricher as pe
        calls = {"n": 0}

        def fake(query, settings, timeout_s, proxy):
            calls["n"] += 1
            if calls["n"] < 3:
                raise self._boom(502)
            return [{"type": "node", "lat": 1, "lon": 2, "tags": {"name": "x"}}]

        monkeypatch.setattr(pe, "_query_once", fake)
        monkeypatch.setattr(pe.time, "sleep", lambda s: None)
        out = pe.fetch_overpass((0, 0, 1, 1), self._S())
        assert calls["n"] == 3
        assert len(out) == 1

    def test_gives_up_after_retries(self, monkeypatch):
        from app import poi_enricher as pe
        calls = {"n": 0}

        def fake(*a):
            calls["n"] += 1
            raise self._boom(502)

        monkeypatch.setattr(pe, "_query_once", fake)
        monkeypatch.setattr(pe.time, "sleep", lambda s: None)
        import pytest as _pytest
        with _pytest.raises(pe.PoiQueryError, match="已重试"):
            pe.fetch_overpass((0, 0, 1, 1), self._S())
        assert calls["n"] == 3, "应尝试 1 次 + 重试 2 次"

    def test_no_retry_on_4xx(self, monkeypatch):
        from app import poi_enricher as pe
        calls = {"n": 0}

        def fake(*a):
            calls["n"] += 1
            raise self._boom(400)

        monkeypatch.setattr(pe, "_query_once", fake)
        monkeypatch.setattr(pe.time, "sleep", lambda s: None)
        import pytest as _pytest
        with _pytest.raises(pe.PoiQueryError, match="400"):
            pe.fetch_overpass((0, 0, 1, 1), self._S())
        assert calls["n"] == 1, "4xx 不该重试"

    def test_retries_on_network_error(self, monkeypatch):
        from app import poi_enricher as pe
        import urllib.error
        calls = {"n": 0}

        def fake(*a):
            calls["n"] += 1
            if calls["n"] < 2:
                raise urllib.error.URLError("timeout")
            return []

        monkeypatch.setattr(pe, "_query_once", fake)
        monkeypatch.setattr(pe.time, "sleep", lambda s: None)
        assert pe.fetch_overpass((0, 0, 1, 1), self._S()) == []
        assert calls["n"] == 2


class TestGeometryHelpers:
    def test_crosses_when_opposite_sides(self):
        # 轨迹自南向北穿过东西向的河
        assert _crosses((24.000, 113.0), (24.010, 113.0),
                        (24.005, 112.99), (24.005, 113.01))

    def test_no_cross_when_same_side(self):
        assert not _crosses((24.000, 113.0), (24.001, 113.0),
                            (24.005, 112.99), (24.005, 113.01))

    def test_point_seg_side_sign_flips(self):
        d1, s1 = _point_seg_side((24.000, 113.0), (24.005, 112.99), (24.005, 113.01))
        d2, s2 = _point_seg_side((24.010, 113.0), (24.005, 112.99), (24.005, 113.01))
        assert (s1 > 0) != (s2 > 0), "南北两侧应在河的不同岸"
        assert d1 < 1200 and d2 < 1200

    def test_element_point_node(self):
        assert _element_point({"lat": 1.0, "lon": 2.0}) == (1.0, 2.0)

    def test_element_point_way_uses_centroid(self):
        el = _way([(0.0, 0.0), (0.0, 2.0), (2.0, 2.0), (2.0, 0.0)], {})
        assert _element_point(el) == (1.0, 1.0)


class TestFilterRules:
    def test_saddle_near_track_kept(self):
        track = _track_north()
        els = [_node(24.005, 113.0, {"natural": "saddle", "name": "黑湖垭口"})]
        r = filter_pois(els, track, _Settings())
        assert len(r.items) == 1
        assert r.items[0]["name"] == "黑湖垭口"
        assert r.items[0]["type_label"] == "垭口"
        assert r.items[0]["distance_m"] < 30

    def test_saddle_far_dropped(self):
        track = _track_north()
        els = [_node(24.5, 113.0, {"natural": "saddle", "name": "很远垭口"})]
        assert filter_pois(els, track, _Settings()).items == []

    def test_peak_allowed_up_to_3km(self):
        track = _track_north()
        # 约 1.9km 外：作为地标应保留
        els = [_node(24.017, 113.0, {"natural": "peak", "name": "仙乃日", "ele": "5998"})]
        r = filter_pois(els, track, _Settings())
        assert len(r.items) == 1
        assert r.items[0]["type_label"] == "山峰"

    def test_peak_beyond_3km_dropped(self):
        track = _track_north()
        els = [_node(24.10, 113.0, {"natural": "peak", "name": "远处峰"})]
        assert filter_pois(els, track, _Settings()).items == []

    def test_village_at_endpoint_kept(self):
        track = _track_north()
        end = track[-1]
        els = [_node(end[0], end[1], {"place": "hamlet", "name": "扎灌崩"})]
        r = filter_pois(els, track, _Settings())
        assert len(r.items) == 1
        assert r.items[0]["type_label"] == "村落"

    def test_village_midway_dropped(self):
        """路线只是穿过村镇时不标。"""
        track = _track_north(n=200, step=0.0002)
        mid = track[len(track) // 2]
        els = [_node(mid[0], mid[1], {"place": "village", "name": "亚丁村"})]
        assert filter_pois(els, track, _Settings()).items == []

    def test_unnamed_dropped(self):
        track = _track_north()
        els = [_node(24.005, 113.0, {"natural": "saddle"})]
        assert filter_pois(els, track, _Settings()).items == []

    def test_name_prefers_chinese(self):
        track = _track_north()
        els = [_node(24.005, 113.0, {"natural": "saddle",
                                     "name": "Heihu Pass", "name:zh": "黑湖垭口"})]
        r = filter_pois(els, track, _Settings())
        assert r.items[0]["name"] == "黑湖垭口"

    def test_dedupe_keeps_nearest(self):
        """两个同名垭口都合格时，只保留离轨迹更近的那个。"""
        track = _track_north()
        els = [
            _node(24.0055, 113.0, {"natural": "saddle", "name": "同名垭口"}),  # ~61m
            _node(24.0050, 113.0, {"natural": "saddle", "name": "同名垭口"}),  # ~0m
        ]
        r = filter_pois(els, track, _Settings())
        assert len(r.items) == 1
        assert r.items[0]["distance_m"] < 10, "应保留更近的那个"
        assert r.dropped == 1

    def test_truncation_reports_count(self):
        track = _track_north(n=200, step=0.0002)
        els = [_node(24.0 + i * 0.0002, 113.0,
                     {"natural": "saddle", "name": f"垭口{i}"}) for i in range(30)]
        s = _Settings()
        s.poi_max_count = 5
        r = filter_pois(els, track, s)
        assert len(r.items) == 5
        assert r.truncated == 25


class TestRiverCrossing:
    def test_detects_crossing(self):
        track = _track_north(n=80, step=0.0002)          # 自南向北，经度固定 113.0
        rivers = {"白水河": [(24.005, 112.999), (24.005, 113.001)]}
        found = _river_crossings(track, rivers)
        assert "白水河" in found
        lat, lon = found["白水河"]
        assert abs(lat - 24.005) < 0.002

    def test_no_crossing_when_parallel(self):
        """沿河并行但不过河，不应算作过河。"""
        track = _track_north(n=80, step=0.0002)
        rivers = {"并行河": [(24.0, 112.99), (24.1, 112.99)]}   # 西侧平行
        assert _river_crossings(track, rivers) == {}

    def test_only_one_marker_per_river(self):
        track = _track_north(n=200, step=0.0002)
        rivers = {"多次河": [(24.002, 112.999), (24.002, 113.001),
                          (24.030, 112.999), (24.030, 113.001)]}
        found = _river_crossings(track, rivers)
        assert list(found.keys()).count("多次河") == 1

    def test_river_appears_in_result(self):
        track = _track_north(n=80, step=0.0002)
        els = [_way([(24.005, 112.999), (24.005, 113.001)],
                    {"waterway": "stream", "name": "白水河"})]
        r = filter_pois(els, track, _Settings())
        assert any(i["kind"] == "river" for i in r.items)
        names = [i["name"] for i in r.items]
        assert "白水河" in names
