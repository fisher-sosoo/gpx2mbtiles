"""行前指南与天气的纯逻辑测试（不联网）。"""
import pytest

from app import trip_briefing as tb
from app import weather as wx


class TestWeatherNormalise:
    def test_normalise_parallel_arrays(self):
        payload = {
            "timezone": "Asia/Shanghai", "elevation": 4000,
            "daily": {
                "time": ["2026-10-18", "2026-10-19"],
                "temperature_2m_max": [5.0, 6.0],
                "temperature_2m_min": [-5.0, -4.0],
                "precipitation_sum": [0.0, 3.2],
                "precipitation_probability_max": [0, 70],
                "weather_code": [1, 61],
                "wind_speed_10m_max": [20.0, 30.0],
            },
        }
        out = wx.normalise(payload)
        assert len(out["days"]) == 2
        d = out["days"][1]
        assert d["weather"] == "小雨"
        assert d["rain_mm"] == 3.2

    def test_short_arrays_do_not_crash(self):
        payload = {"daily": {"time": ["a", "b"], "temperature_2m_max": [1.0]}}
        out = wx.normalise(payload)
        assert len(out["days"]) == 2
        assert out["days"][1]["t_max"] is None

    def test_describe_code(self):
        assert wx.describe_code(0) == "晴"
        assert wx.describe_code(61) == "小雨"
        assert "天气码" in wx.describe_code(9999)


class TestDayRisk:
    def test_heavy_rain(self):
        r = wx.day_risk({"rain_mm": 12.0, "rain_p": 80})
        assert any("降雨" in x for x in r)

    def test_cold(self):
        r = wx.day_risk({"t_min": -8})
        assert any("失温" in x for x in r)

    def test_thunderstorm(self):
        r = wx.day_risk({"code": 95})
        assert any("雷暴" in x for x in r)

    def test_calm_day_no_risk(self):
        assert wx.day_risk({"rain_mm": 0, "rain_p": 5, "wind_kmh": 10,
                            "t_min": 3, "code": 0}) == []


def _summary():
    return {
        "tracks": [{"name": "洛亚大转", "points": 24768}],
        "distance_m": 49460.0,
        "sport": "爬山",
        "date": "2026-10-01",
        "waypoints": [
            {"turn_text": "发卡弯左144°"}, {"turn_text": "右转64°"},
            {"turn_text": "直行"},
        ],
    }


def _pois():
    return {"items": [
        {"name": "黑湖垭口", "kind": "saddle", "type_label": "垭口",
         "km": 12.0, "ele": 4720.0},
        {"name": "杂巴拉垭口", "kind": "saddle", "type_label": "垭口",
         "km": 24.0, "ele": 4750.0},
        {"name": "白水河", "kind": "river", "type_label": "过河",
         "km": 30.0, "ele": None},
        {"name": "新果牛场", "kind": "camp_site", "type_label": "营地",
         "km": 18.0, "ele": 4270.0},
        {"name": "牛奶海", "kind": "water", "type_label": "湖泊",
         "km": 40.0, "ele": 4600.0},
        {"name": "仙乃日", "kind": "peak", "type_label": "山峰",
         "km": 20.0, "ele": 5998.5},
    ]}


def _weather():
    return {"days": [
        {"date": "2026-10-18", "weather": "晴", "t_min": -6, "t_max": 4,
         "rain_mm": 0, "rain_p": 0, "wind_kmh": 20, "code": 0},
        {"date": "2026-10-19", "weather": "小雨", "t_min": -5, "t_max": 3,
         "rain_mm": 4, "rain_p": 70, "wind_kmh": 45, "code": 61},
    ]}


class TestBriefing:
    def test_key_points_sorted_by_km(self):
        kps = tb.key_points(_pois()["items"])
        kms = [p["km"] for p in kps]
        assert kms == sorted(kms)

    def test_key_points_dedup(self):
        items = _pois()["items"] + [
            {"name": "黑湖垭口", "kind": "saddle", "km": 12.5, "ele": 4720}]
        kps = tb.key_points(items)
        names = [p["name"] for p in kps if p["kind"] == "saddle"]
        assert names.count("黑湖垭口") == 1

    def test_risks_mention_high_pass(self):
        risks = tb.build_risks(_summary(), _pois()["items"], _weather())
        assert any("高海拔垭口" in r for r in risks)
        assert any("过河" in r for r in risks)

    def test_risks_include_bad_weather_day(self):
        risks = tb.build_risks(_summary(), _pois()["items"], _weather())
        assert any("2026-10-19" in r for r in risks)

    def test_mistakes_mention_hairpin(self):
        tips = tb.build_mistakes(_summary(), _pois()["items"],
                                 _summary()["waypoints"])
        assert any("发卡弯" in t for t in tips)
        assert any("营地" in t or "牛场" in t for t in tips)

    def test_overview_contains_distance_and_peak(self):
        ov = tb.build_overview(_summary(), _pois()["items"], _weather())
        assert "49.46 km" in ov
        assert "仙乃日" in ov
        assert "垭口" in ov

    def test_build_and_markdown(self):
        brief = tb.build(_summary(), _pois(), _weather(), "2026-10-18 ~ 2026-10-19")
        assert brief["title"] == "洛亚大转"
        md = tb.render_markdown(brief)
        assert "# 行前指南" in md
        assert "## 关键节点" in md
        assert "## 天气" in md
        assert "## 风险提示" in md
        assert "黑湖垭口" in md
        assert "2026-10-19" in md

    def test_markdown_without_ai(self):
        brief = tb.build(_summary(), _pois(), _weather())
        md = tb.render_markdown(brief)
        assert "综合分析" not in md

    def test_markdown_with_ai_and_error(self):
        brief = tb.build(_summary(), _pois(), _weather())
        brief["ai_narrative"] = "注意午后雷暴，建议 6 点前出发。"
        md = tb.render_markdown(brief)
        assert "## 综合分析" in md
        assert "6 点前出发" in md

        brief["ai_narrative"] = ""
        brief["ai_error"] = "模型请求失败：超时"
        md = tb.render_markdown(brief)
        assert "未生成" in md

    def test_ai_prompt_contains_facts(self):
        brief = tb.build(_summary(), _pois(), _weather())
        prompt = tb.make_ai_prompt(brief)
        assert "洛亚大转" in prompt
        assert "黑湖垭口" in prompt
        assert "2026-10-18" in prompt
        assert "行前风险分析" in prompt
