"""KML → GPX 转换的单元测试。

核心回归用用户提供的真实两步路样本（samples/ 下的 KML）：
它覆盖了「无名标注点 + 占位轨迹名 + 描述里只有坐标」这个最坑的场景。
"""
import io
import zipfile

import pytest

from app import kml_naming as naming
from app.gpx_converter import convert, extract_points, safe_filename
from app.kml_processor import (KmlParseError, parse_iso_utc, parse_kmz_bytes,
                               parse_kml_bytes, parse_kml_text)
from tests.conftest import make_kml, sample_kml_bytes


class TestKmlParse:
    def test_gx_track(self):
        kml = make_kml(
            track_times=[(113.0, 24.0, 100, "2023-02-18T02:00:00Z"),
                         (113.1, 24.1, 200, "2023-02-18T02:10:00Z")],
            doc_name="D")
        result = parse_kml_text(kml)
        assert len(result.tracks) == 1
        pts = result.tracks[0].points
        assert len(pts) == 2
        assert pts[0].lat == 24.0 and pts[0].lon == 113.0
        assert pts[0].ele == 100.0
        assert pts[0].time is not None and pts[1].time > pts[0].time

    def test_parallel_arrays_mismatch_keeps_coords(self):
        """<when> 比 <gx:coord> 少时，坐标不能丢，只把时间留空。"""
        kml = (
            '<kml xmlns="http://www.opengis.net/kml/2.2" '
            'xmlns:gx="http://www.google.com/kml/ext/2.2"><Document>'
            "<Placemark><gx:Track>"
            "<when>2023-02-18T02:00:00Z</when>"
            "<gx:coord>113.0 24.0 100</gx:coord>"
            "<gx:coord>113.1 24.1 200</gx:coord>"
            "</gx:Track></Placemark></Document></kml>")
        pts = parse_kml_text(kml).tracks[0].points
        assert len(pts) == 2
        assert pts[0].time is not None
        assert pts[1].time is None

    def test_linestring_and_point(self):
        kml = (
            '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
            "<Placemark><name>线</name><LineString><coordinates>"
            "113.0,24.0,10 113.1,24.1,20 113.2,24.2,30</coordinates></LineString></Placemark>"
            "<Placemark><name>点</name><Point><coordinates>113.5,24.5,50</coordinates></Point></Placemark>"
            "</Document></kml>")
        r = parse_kml_text(kml)
        assert len(r.tracks) == 1 and len(r.tracks[0].points) == 3
        assert len(r.waypoints) == 1
        assert r.waypoints[0].name == "点"

    def test_single_point_line_is_not_a_track(self):
        kml = ('<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
               "<Placemark><LineString><coordinates>113.0,24.0</coordinates>"
               "</LineString></Placemark></Document></kml>")
        with pytest.raises(KmlParseError, match="未找到"):
            parse_kml_text(kml)

    def test_special_points_detected(self):
        kml = (
            '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
            '<Placemark id="startPoint"><name>起点</name>'
            "<Point><coordinates>113.0,24.0,1</coordinates></Point></Placemark>"
            '<Placemark id="endPoint"><name>终点</name>'
            "<Point><coordinates>113.9,24.9,2</coordinates></Point></Placemark>"
            "</Document></kml>")
        r = parse_kml_text(kml)
        assert r.start_point is not None and r.start_point.lat == 24.0
        assert r.end_point is not None
        assert r.waypoints == []

    def test_invalid_inputs(self):
        with pytest.raises(KmlParseError, match="为空"):
            parse_kml_bytes(b"")
        with pytest.raises(KmlParseError, match="解析失败"):
            parse_kml_text("<kml><unclosed>")
        with pytest.raises(KmlParseError, match="不是有效的 KML"):
            parse_kml_text("<gpx></gpx>")
        with pytest.raises(KmlParseError, match="未找到"):
            parse_kml_text('<kml xmlns="http://www.opengis.net/kml/2.2"><Document/></kml>')

    def test_kmz_prefers_doc_kml(self):
        buf = io.BytesIO()
        inner = make_kml(track_times=[(113.0, 24.0, 1, "2023-02-18T02:00:00Z"),
                                      (113.1, 24.1, 2, "2023-02-18T02:01:00Z")])
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("other.kml", "<kml/>")
            zf.writestr("doc.kml", inner)
        r = parse_kmz_bytes(buf.getvalue())
        assert len(r.tracks[0].points) == 2

    def test_kmz_without_kml(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("readme.txt", "hi")
        with pytest.raises(KmlParseError, match="没有找到 .kml"):
            parse_kmz_bytes(buf.getvalue())

    def test_kmz_bad_zip(self):
        with pytest.raises(KmlParseError, match="解压失败"):
            parse_kmz_bytes(b"PK\x03\x04garbage")

    def test_gbk_encoding(self):
        kml = make_kml(track_times=[(113.0, 24.0, 1, "2023-02-18T02:00:00Z"),
                                    (113.1, 24.1, 2, "2023-02-18T02:01:00Z")],
                       doc_name="英德雪山嶂")
        raw = kml.encode("gb18030")
        r = parse_kml_bytes(raw)
        assert r.doc_name == "英德雪山嶂"

    def test_iso_parser(self):
        assert parse_iso_utc("2023-02-18T02:35:30Z") is not None
        assert parse_iso_utc("2023-02-18 02:35:30") is not None
        assert parse_iso_utc("") is None
        assert parse_iso_utc("not-a-date") is None


class TestFormat:
    def test_fmt_elapsed_h_mm(self):
        assert naming.fmt_elapsed(0) == "0:00"
        assert naming.fmt_elapsed(455) == "0:08"      # 7 分 35 秒 → 8 分
        assert naming.fmt_elapsed(3600) == "1:00"
        assert naming.fmt_elapsed(23850) == "6:38"

    def test_fmt_distance(self):
        assert naming.fmt_distance(0.382) == "0.38km"
        assert naming.fmt_distance(11.228) == "11.23km"

    def test_position_name_with_and_without_time(self):
        assert naming.position_name(0.38, 455, 377.0) == "0.38km · 0:08"
        assert naming.position_name(0.38, None, 377.4) == "0.38km · 377m"
        assert naming.position_name(0.38, None, None) == "0.38km"


class TestTrackNaming:
    def test_place_first_then_date_then_sport(self):
        result = parse_kml_text(make_kml(
            track_times=[(113.0, 24.0, 1, "2023-02-18T02:00:00Z"),
                         (113.1, 24.1, 2, "2023-02-18T02:01:00Z")],
            doc_name="2023-02-18 英德雪山嶂环线", sport="爬山"))
        names = naming.track_names(result, "2023-02-18 英德雪山嶂环线.kml")
        assert names == ["英德雪山嶂环线 2023-02-18 爬山"]
        # 地点必须在前，日期不能打头
        assert not names[0][:4].isdigit()

    def test_placeholder_words_never_used(self):
        result = parse_kml_text(make_kml(
            track_times=[(113.0, 24.0, 1, "2023-02-18T02:00:00Z"),
                         (113.1, 24.1, 2, "2023-02-18T02:01:00Z")],
            doc_name="轨迹片段1", sport=""))
        name = naming.track_names(result, "轨迹片段1.kml")[0]
        assert "轨迹片段" not in name
        assert name.startswith("2023-02-18")   # 无地名时才退化为日期打头

    def test_custom_name_overrides(self):
        result = parse_kml_text(make_kml(
            track_times=[(113.0, 24.0, 1, "2023-02-18T02:00:00Z"),
                         (113.1, 24.1, 2, "2023-02-18T02:01:00Z")]))
        assert naming.track_names(result, "x.kml", "我的路线") == ["我的路线"]

    def test_strip_date_prefix(self):
        assert naming.strip_date_prefix("2023-02-18 英德雪山嶂环线") == "英德雪山嶂环线"
        assert naming.strip_date_prefix("20230218环线") == "20230218环线"
        assert naming.place_from_name("2023-02-18 英德雪山嶂环线") == "英德雪山嶂环线"


class TestNamingPriority:
    """四级来源：name → 备注 → 位置 → 附件文件名。"""

    def _convert_one(self, **wp):
        track = [(113.0, 24.0, 100, "2023-02-18T02:00:00Z"),
                 (113.01, 24.01, 200, "2023-02-18T02:30:00Z"),
                 (113.02, 24.02, 300, "2023-02-18T03:00:00Z")]
        kml = make_kml(track_times=track, waypoints=[dict(
            lat=24.01, lon=113.01, ele=200, desc_time="2023-02-18 10:30:00", **wp)])
        return convert(kml.encode("utf-8"), "2023-02-18 测试环线.kml").summary.to_dict()

    def test_name_wins(self):
        s = self._convert_one(name="垭口", note="备注", file_id="999")
        wp = s["waypoints"][0]
        assert wp["source"] == "name"
        assert wp["name"].endswith("垭口")

    def test_note_wins_over_position(self):
        s = self._convert_one(note="这里风很大", file_id="999")
        wp = s["waypoints"][0]
        assert wp["source"] == "note"
        assert "这里风很大" in wp["name"]

    def test_attachment_json_is_not_a_note(self):
        """attach 那种 JSON 串不能被当成人类备注。"""
        s = self._convert_one(note='[{"fileSize":"0","fileId":"1"}]', file_id="999")
        assert s["waypoints"][0]["source"] == "position"

    def test_position_beats_attachment(self):
        s = self._convert_one(file_id="1201359289")
        wp = s["waypoints"][0]
        assert wp["source"] == "position"
        assert "km" in wp["name"] and ":" in wp["name"]

    def test_attachment_when_no_track(self):
        kml = (
            '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
            '<Placemark id="realPoint"><ExtendedData>'
            '<Data name="Latitude"><value>24.0</value></Data>'
            '<Data name="Longtitude"><value>113.0</value></Data>'
            '<Data name="FileId"><value>777</value></Data>'
            "</ExtendedData><Point><coordinates>113.0,24.0,10</coordinates></Point>"
            "</Placemark></Document></kml>")
        s = convert(kml.encode("utf-8"), "a.kml").summary.to_dict()
        assert s["waypoints"][0]["source"] == "attach"
        assert "777" in s["waypoints"][0]["name"]


class TestSampleKml:
    """真实样本的端到端数字，作为回归基线。"""

    @pytest.fixture(scope="class")
    def result(self):
        return convert(sample_kml_bytes(), "2023-02-18 英德雪山嶂环线.kml")

    def test_track_name_place_first(self, result):
        s = result.summary
        assert len(s.tracks) == 1
        assert s.tracks[0]["name"] == "英德雪山嶂环线 2023-02-18 爬山"

    def test_point_counts(self, result):
        s = result.summary
        assert s.tracks[0]["points"] == 1052
        assert s.waypoint_count == 30
        assert s.start_point["name"] == "起点"
        assert s.end_point["name"] == "终点"

    def test_distance(self, result):
        # 两步路自报 11608.7m；按顶点累加是 11228.4m，差 3% 属正常抽样误差
        assert 11000 < result.summary.distance_m < 11400

    def test_waypoint_names_unique_and_ordered(self, result):
        names = [w["name"] for w in result.summary.waypoints]
        assert len(names) == 30
        assert len(set(names)) == 30, "航点名称必须两两不同"
        assert names[0].startswith("#01 ")
        assert names[-1].startswith("#30 ")

    def test_first_waypoint_shape(self, result):
        wp = result.summary.waypoints[0]
        assert wp["source"] == "position"
        assert wp["km"] == pytest.approx(0.38, abs=0.02)
        # 8 分 08 秒左右
        assert 6 * 60 < wp["elapsed_s"] < 10 * 60

    def test_along_distance_monotonic(self, result):
        kms = [w["km"] for w in result.summary.waypoints]
        assert kms == sorted(kms), "沿轨迹里程必须单调不减"
        assert kms[-1] == pytest.approx(8.85, abs=0.05)

    def test_elapsed_monotonic(self, result):
        secs = [w["elapsed_s"] for w in result.summary.waypoints]
        assert all(s is not None for s in secs)
        assert secs == sorted(secs), "累计耗时必须单调不减"
        assert 0 <= secs[0] <= secs[-1] <= 7.5 * 3600

    def test_gpx_is_wellformed_with_fields(self, result):
        from xml.etree import ElementTree as ET
        root = ET.fromstring(result.gpx)
        ns = {"g": "http://www.topografix.com/GPX/1/1"}
        assert root.tag.endswith("gpx")
        assert root.get("version") == "1.1"
        wpts = root.findall("g:wpt", ns)
        assert len(wpts) == 32          # 30 标注点 + 起终点
        assert all(w.find("g:name", ns) is not None for w in wpts)
        trkpts = root.findall(".//g:trkpt", ns)
        assert len(trkpts) == 1052
        assert all(p.find("g:ele", ns) is not None for p in trkpts[:5])
        assert all(p.find("g:time", ns) is not None for p in trkpts[:5])

    def test_waypoints_keep_original_coords(self, result):
        """航点坐标必须与源文件逐位一致。"""
        raw = parse_kml_bytes(sample_kml_bytes())
        from xml.etree import ElementTree as ET
        ns = {"g": "http://www.topografix.com/GPX/1/1"}
        root = ET.fromstring(result.gpx)
        got = [(float(w.get("lat")), float(w.get("lon")))
               for w in root.findall("g:wpt", ns)
               if w.find("g:name", ns).text not in ("起点", "终点")]
        want = [(p.lat, p.lon) for p in raw.waypoints]
        assert got == want


class TestAlongTrack:
    def test_distance_and_projection(self):
        pts = [type("P", (), {"lat": 24.0, "lon": 113.0, "ele": 0})(),
               type("P", (), {"lat": 24.0, "lon": 113.01, "ele": 0})(),
               type("P", (), {"lat": 24.0, "lon": 113.02, "ele": 0})()]
        stats = naming.track_stats(pts)
        assert stats.distance_m == pytest.approx(2 * 1017, rel=0.01)
        # 中间点落在第一个顶点上
        mid = type("P", (), {"lat": 24.0, "lon": 113.01, "ele": 0})()
        assert naming.along_distance_m(pts, stats, mid) == pytest.approx(
            stats.distance_m / 2, rel=0.01)
        # 顶点之间插值
        between = type("P", (), {"lat": 24.0, "lon": 113.005, "ele": 0})()
        assert naming.along_distance_m(pts, stats, between) == pytest.approx(
            stats.distance_m / 4, rel=0.02)

    def test_no_track_falls_back_to_chain(self):
        kml = (
            '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
            '<Placemark><Point><coordinates>113.0,24.0,1</coordinates></Point></Placemark>'
            '<Placemark><Point><coordinates>113.01,24.0,2</coordinates></Point></Placemark>'
            "</Document></kml>")
        r = convert(kml.encode("utf-8"), "a.kml")
        assert "no_track" in r.summary.degraded


class TestExtractAndHelpers:
    def test_extract_points_from_kml(self):
        kml = make_kml(track_times=[
            (113.0, 24.0, 1, "2023-02-18T02:00:00Z"),
            (113.1, 24.1, 2, "2023-02-18T02:01:00Z")],
            doc_name="2023-02-18 英德环线", sport="爬山")
        points, name, extra = extract_points(kml.encode("utf-8"), "x.kml")
        assert len(points) == 2
        assert "英德环线" in name

    def test_safe_filename(self):
        assert safe_filename("英德雪山嶂环线 2023-02-18 爬山") == \
            "英德雪山嶂环线 2023-02-18 爬山"
        assert "/" not in safe_filename("a/b")
        assert safe_filename("") == "track"


class TestAiNamingParsing:
    """AI 返回值的校验：只接受序号对得上、名称合格的条目。"""

    def test_plain_json(self):
        from app.ai_naming import parse_names
        out = parse_names('[{"i":1,"name":"起步山径"},{"i":2,"name":"碎石陡段"}]', [1, 2])
        assert out == {1: "起步山径", 2: "碎石陡段"}

    def test_fenced_json(self):
        from app.ai_naming import parse_names
        text = "好的：\n```json\n[{\"i\": 3, \"name\": \"山脊\"}]\n```\n以上。"
        assert parse_names(text, [1, 2, 3]) == {3: "山脊"}

    def test_unknown_seq_dropped(self):
        from app.ai_naming import parse_names
        out = parse_names('[{"i":9,"name":"不存在"},{"i":1,"name":"起步"}]', [1, 2])
        assert out == {1: "起步"}

    def test_bad_names_dropped(self):
        from app.ai_naming import clean_name, parse_names
        assert clean_name("") == ""
        assert clean_name("   ") == ""
        assert clean_name("!!!") == ""
        assert clean_name("这是一个特别特别长的名字超过上限应该被丢掉") == ""
        assert clean_name("一个字符") == "一个字符"
        out = parse_names('[{"i":1,"name":"!!"},{"i":2,"name":"垭口"}]', [1, 2])
        assert out == {2: "垭口"}

    def test_malformed_reply(self):
        from app.ai_naming import parse_names
        assert parse_names("我不能帮你", [1]) == {}
        assert parse_names("[not json", [1]) == {}
        assert parse_names("", [1]) == {}


class TestAiNamingIntegration:
    """接入转换流程后的行为：失败回退、人工优先、来源标记。"""

    def _kml(self):
        track = [(113.0, 24.0, 100, "2023-02-18T02:00:00Z"),
                 (113.01, 24.01, 200, "2023-02-18T02:30:00Z"),
                 (113.02, 24.02, 300, "2023-02-18T03:00:00Z")]
        return make_kml(track_times=track, waypoints=[
            {"lat": 24.005, "lon": 113.005, "ele": 150, "desc_time": "2023-02-18 10:15:00"},
            {"lat": 24.015, "lon": 113.015, "ele": 250, "desc_time": "2023-02-18 10:45:00",
             "name": "垭口"},
        ], doc_name="2023-02-18 测试环线")

    class _Settings:
        ai_api_key = "test-key"
        ai_base_url = "https://example.invalid"
        ai_model = "deepseek-chat"
        ai_timeout_seconds = 5.0
        ai_max_tokens = 500

    def test_ai_names_applied(self, monkeypatch):
        from app import ai_naming
        monkeypatch.setattr(ai_naming, "suggest_names",
                            lambda wps, s, d, st: {1: "林道起步"})
        r = convert(self._kml().encode("utf-8"), "2023-02-18 测试环线.kml",
                    ai_names=True, settings=self._Settings())
        s = r.summary.to_dict()
        assert s["ai_used"] is True and s["ai_named"] == 1
        assert s["waypoints"][0]["source"] == "ai"
        assert "林道起步" in s["waypoints"][0]["name"]
        assert s["waypoints"][0]["name"].startswith("#01 ")

    def test_human_name_wins(self, monkeypatch):
        from app import ai_naming
        seen = {}

        def fake(wps, s, d, st):
            seen["seqs"] = [w["seq"] for w in wps]
            return {w["seq"]: "AI名" for w in wps}

        monkeypatch.setattr(ai_naming, "suggest_names", fake)
        r = convert(self._kml().encode("utf-8"), "x.kml",
                    ai_names=True, settings=self._Settings())
        # 第 2 个航点自带名称，不该进入 AI 候选
        assert seen["seqs"] == [1]
        assert "垭口" in r.summary.to_dict()["waypoints"][1]["name"]

    def test_failure_falls_back(self, monkeypatch):
        from app import ai_naming

        def boom(*a, **k):
            raise ai_naming.AiNamingError("模型请求失败：超时")

        monkeypatch.setattr(ai_naming, "suggest_names", boom)
        r = convert(self._kml().encode("utf-8"), "x.kml",
                    ai_names=True, settings=self._Settings())
        s = r.summary.to_dict()
        assert s["ai_used"] is False
        assert "超时" in s["ai_error"]
        # 转换照常完成，且仍是规则命名
        assert s["waypoints"][0]["source"] == "position"
        assert "<gpx" in r.gpx

    def test_no_key_skips_silently(self, monkeypatch):
        from app import ai_naming
        called = {"n": 0}
        monkeypatch.setattr(ai_naming, "suggest_names",
                            lambda *a: called.__setitem__("n", called["n"] + 1) or {})

        class NoKey:
            ai_api_key = ""

        r = convert(self._kml().encode("utf-8"), "x.kml", ai_names=True, settings=NoKey())
        assert called["n"] == 0, "未配置密钥时不应发起调用"
        assert "未配置" in r.summary.to_dict()["ai_error"]

    def test_off_by_default_makes_no_call(self, monkeypatch):
        from app import ai_naming
        called = {"n": 0}
        monkeypatch.setattr(ai_naming, "suggest_names",
                            lambda *a: called.__setitem__("n", called["n"] + 1) or {})
        convert(self._kml().encode("utf-8"), "x.kml", settings=self._Settings())
        assert called["n"] == 0


class TestAiPrompt:
    def test_prompt_is_compact_and_structured(self):
        from app.ai_naming import build_prompt
        from app.gpx_converter import ConvertSummary
        summary = ConvertSummary(tracks=[{"name": "英德雪山嶂环线"}],
                                 date="2023-02-18", sport="爬山")
        wps = [{"seq": i, "km": i * 0.5, "elapsed_s": i * 600, "ele": 300 + i * 50}
               for i in range(1, 31)]
        prompt = build_prompt(wps, summary, 11228.0)
        assert "30|" in prompt or "   30|" in prompt or "\n30|" in prompt
        assert "海拔" in prompt
        assert "JSON" in prompt
        # 控制在千余字符级别，避免把原始点云塞给模型
        assert len(prompt) < 4000
