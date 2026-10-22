"""Garmin 取数模块的纯逻辑测试（不联网、不需要真实账号）。

覆盖：FIT 记录归一化、心率 0 缺测、缓存命中、下载失败降级、节流并发、
缓存淘汰、授权状态。真实 API 调用被完全挡在外面。
"""
import os
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app import garmin_source


def make_settings(tmp_path, **over):
    base = dict(
        data_dir=str(tmp_path / "data"),
        garmin_tokens=str(tmp_path / "tokens"),
        garmin_enabled=True,
        garmin_is_cn=False,
        garmin_days_default=30,
        garmin_activity_limit=20,
        garmin_cache_max_mb=512,
        garmin_min_interval_seconds=0.0,
        garmin_timeout_seconds=10.0,
    )
    base.update(over)
    return SimpleNamespace(**base)


class FakeClient:
    """只实现取数用到的三个方法。"""

    class ActivityDownloadFormat:
        ORIGINAL = "original"

    def __init__(self, payload=b"FIT-BYTES"):
        self.payload = payload
        self.downloads = 0

    def download_activity(self, activity_id, dl_fmt=None):
        self.downloads += 1
        return self.payload

    def get_activity(self, activity_id):
        return {"activityName": "上雨崩-冰湖", "startTimeLocal": "2025-12-10T08:49:05"}


# ---------------------------------------------------------------- 归一化
def test_normalize_records_maps_all_fields():
    records = [{
        "timestamp": datetime(2025, 12, 10, 0, 49, 5, tzinfo=timezone.utc),
        "position_lat": 28.399689,
        "position_long": 98.774809,
        "enhanced_altitude": 3232.8,
        "heart_rate": 121,
        "cadence": 78,
        "temperature": 9.5,
    }]
    points = garmin_source.normalize_records(records)
    assert len(points) == 1
    point = points[0]
    assert point["lat"] == pytest.approx(28.399689, abs=1e-6)
    assert point["hr"] == 121 and point["cad"] == 78
    assert point["temp"] == pytest.approx(9.5)
    assert point["t"] == 1765327745


def test_heart_rate_zero_is_treated_as_missing():
    records = [{
        "timestamp": 100,
        "position_lat": 28.0,
        "position_long": 98.0,
        "heart_rate": 0,
    }]
    assert garmin_source.normalize_records(records)[0]["hr"] is None


def test_impossible_heart_rate_dropped():
    records = [{
        "timestamp": 100, "position_lat": 28.0,
        "position_long": 98.0, "heart_rate": 999,
    }]
    assert garmin_source.normalize_records(records)[0]["hr"] is None


def test_missing_sensor_fields_stay_null():
    records = [{
        "timestamp": 100, "position_lat": 28.0,
        "position_long": 98.0, "altitude": 3000.0,
    }]
    point = garmin_source.normalize_records(records)[0]
    assert point["hr"] is None and point["cad"] is None and point["temp"] is None
    assert point["ele"] == pytest.approx(3000.0)


def test_semicircle_coordinates_are_converted():
    # FIT 原始的 int32 半圆值
    raw = int(28.399689 * (2 ** 31) / 180)
    records = [{
        "timestamp": 100, "position_lat": raw,
        "position_long": 98.0,
    }]
    point = garmin_source.normalize_records(records)[0]
    assert point["lat"] == pytest.approx(28.399689, abs=1e-5)


def test_points_without_position_are_dropped():
    records = [{"timestamp": 100, "heart_rate": 120}]
    assert garmin_source.normalize_records(records) == []


def test_same_timestamp_keeps_first():
    records = [
        {"timestamp": 100, "position_lat": 28.0, "position_long": 98.0, "heart_rate": 100},
        {"timestamp": 100, "position_lat": 28.1, "position_long": 98.1, "heart_rate": 200},
    ]
    points = garmin_source.normalize_records(records)
    assert len(points) == 1
    assert points[0]["hr"] == 100


def test_records_are_sorted_by_time():
    records = [
        {"timestamp": 200, "position_lat": 28.2, "position_long": 98.2},
        {"timestamp": 100, "position_lat": 28.1, "position_long": 98.1},
    ]
    times = [p["t"] for p in garmin_source.normalize_records(records)]
    assert times == [100, 200]


# ---------------------------------------------------------------- 活动列表
def test_list_activities_normalizes_and_filters(tmp_path, monkeypatch):
    from datetime import timedelta

    settings = make_settings(tmp_path, garmin_days_default=30)
    now = datetime.now(timezone.utc)
    raw = [
        {"activityId": 11, "activityName": "上雨崩", "startTimeGMT": now.isoformat(),
         "startTimeLocal": "2025-12-10T08:49:05", "distance": 12345.6,
         "duration": 3600.0, "activityType": {"typeKey": "hiking"}},
        {"activityId": 12, "activityName": "", "distance": 1, "duration": 1,
         "startTimeGMT": (now - timedelta(days=90)).isoformat(),
         "activityType": {"typeKey": "walking"}},
    ]
    client = SimpleNamespace(get_activities=lambda start, limit: raw)
    monkeypatch.setattr(garmin_source, "get_client", lambda _s: client)

    items = garmin_source.list_activities(settings, days=30)
    assert len(items) == 1  # 90 天前那条被时间窗过滤掉
    item = items[0]
    assert item["id"] == 11
    assert item["name"] == "上雨崩"
    assert item["distance_m"] == pytest.approx(12345.6)
    assert item["duration_s"] == pytest.approx(3600.0)
    assert item["type"] == "hiking"


# ---------------------------------------------------------------- 代理
def test_proxy_env_is_applied_when_missing(tmp_path, monkeypatch):
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "NO_PROXY"):
        monkeypatch.delenv(key, raising=False)
    settings = make_settings(tmp_path, garmin_proxy="http://proxy.local:7893")
    garmin_source._ensure_proxy(settings)
    import os as _os
    assert _os.environ["HTTPS_PROXY"] == "http://proxy.local:7893"
    assert "host.docker.internal" in _os.environ["NO_PROXY"]


def test_proxy_env_is_not_overridden(tmp_path, monkeypatch):
    import os as _os
    monkeypatch.setenv("HTTPS_PROXY", "http://already:8080")
    settings = make_settings(tmp_path, garmin_proxy="http://proxy.local:7893")
    garmin_source._ensure_proxy(settings)
    assert _os.environ["HTTPS_PROXY"] == "http://already:8080"


# ---------------------------------------------------------------- 授权
def test_has_token_false_without_dir(tmp_path):
    assert garmin_source.has_token(make_settings(tmp_path)) is False


def test_has_token_true_with_json(tmp_path):
    settings = make_settings(tmp_path)
    os.makedirs(settings.garmin_tokens)
    open(os.path.join(settings.garmin_tokens, "oauth2_token.json"), "w").close()
    assert garmin_source.has_token(settings) is True


def test_get_client_without_token_raises_auth_error(tmp_path):
    garmin_source.reset_client()
    with pytest.raises(garmin_source.GarminAuthError):
        garmin_source.get_client(make_settings(tmp_path))


# ---------------------------------------------------------------- 缓存与取数
def test_load_activity_reads_cache_without_network(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    base = garmin_source.cache_dir(settings)
    with open(os.path.join(base, "42.json"), "w", encoding="utf-8") as fh:
        fh.write('{"id": 42, "points": []}')

    def boom(_settings):
        raise AssertionError("命中缓存时不应该请求 Garmin")

    monkeypatch.setattr(garmin_source, "get_client", boom)
    payload = garmin_source.load_activity(settings, 42)
    assert payload["id"] == 42


def test_load_activity_downloads_parses_and_caches(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    client = FakeClient()
    monkeypatch.setattr(garmin_source, "get_client", lambda _s: client)
    monkeypatch.setattr(garmin_source, "parse_fit",
                        lambda data: [{"t": 1, "lat": 28.0, "lng": 98.0,
                                       "ele": 3000.0, "hr": 120, "cad": 80, "temp": 9.0}])

    payload = garmin_source.load_activity(settings, 7)
    assert payload["name"] == "上雨崩-冰湖"
    assert len(payload["points"]) == 1
    assert client.downloads == 1

    fit_path, json_path = garmin_source.cache_paths(settings, 7)
    assert os.path.isfile(fit_path) and os.path.isfile(json_path)

    # 第二次走缓存，不再下载
    garmin_source.load_activity(settings, 7)
    assert client.downloads == 1


def test_load_activity_survives_unparsable_file(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    monkeypatch.setattr(garmin_source, "get_client", lambda _s: FakeClient())
    monkeypatch.setattr(garmin_source, "parse_fit", lambda data: [])

    payload = garmin_source.load_activity(settings, 8)
    assert payload["points"] == []
    assert payload["partial"] is True


def test_second_fetch_is_rejected_as_busy(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    monkeypatch.setattr(garmin_source, "get_client", lambda _s: FakeClient())
    monkeypatch.setattr(garmin_source, "parse_fit", lambda data: [])

    assert garmin_source._fetch_lock.acquire(blocking=False)
    try:
        with pytest.raises(garmin_source.GarminBusyError):
            garmin_source.load_activity(settings, 9)
    finally:
        garmin_source._fetch_lock.release()


def test_cache_eviction_removes_oldest(tmp_path):
    settings = make_settings(tmp_path, garmin_cache_max_mb=1)
    base = garmin_source.cache_dir(settings)
    old = os.path.join(base, "old.fit")
    new = os.path.join(base, "new.fit")
    for path, stamp in ((old, 1_000_000), (new, 2_000_000)):
        with open(path, "wb") as fh:
            fh.write(b"x" * 700_000)
        os.utime(path, (stamp, stamp))

    garmin_source._evict(settings)
    assert not os.path.exists(old)
    assert os.path.exists(new)


def test_zip_wrapped_download_is_unwrapped():
    """Garmin 的原始文件接口回的是 zip，解析前必须剥掉。"""
    import io as _io
    import zipfile

    buffer = _io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("activity.fit", b"FIT-INSIDE")
    assert garmin_source._unwrap_fit(buffer.getvalue()) == b"FIT-INSIDE"
    assert garmin_source._unwrap_fit(b"\x0eplain-fit") == b"\x0eplain-fit"


def test_load_activity_unwraps_zip(tmp_path, monkeypatch):
    import io as _io
    import zipfile

    buffer = _io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("activity.fit", b"FIT-INSIDE")

    settings = make_settings(tmp_path)
    monkeypatch.setattr(garmin_source, "get_client", lambda _s: FakeClient(buffer.getvalue()))
    seen = {}

    def fake_parse(data):
        seen["data"] = data
        return []

    monkeypatch.setattr(garmin_source, "parse_fit", fake_parse)
    garmin_source.load_activity(settings, 77)
    assert seen["data"] == b"FIT-INSIDE"


def test_parse_fit_returns_empty_on_garbage():
    assert garmin_source.parse_fit(b"definitely not a fit file") == []


# ---------------------------------------------------------------- 状态
def test_status_reports_authorization(tmp_path):
    settings = make_settings(tmp_path)
    status = garmin_source.status(settings)
    assert status["enabled"] is True and status["authorized"] is False

    os.makedirs(settings.garmin_tokens)
    open(os.path.join(settings.garmin_tokens, "oauth2_token.json"), "w").close()
    assert garmin_source.status(settings)["authorized"] is True


def test_status_disabled_hides_token_dir(tmp_path):
    status = garmin_source.status(make_settings(tmp_path, garmin_enabled=False))
    assert status["enabled"] is False and status["tokens_dir"] is None
