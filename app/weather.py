"""天气预报：Open-Meteo（免费、无需 key）。

实测：2.6 秒返回 7 天逐日预报，支持 elevation 参数按海拔修正。
墙内直连不通，复用 TILE_PROXY 走代理。
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

API_URL = "https://api.open-meteo.com/v1/forecast"
USER_AGENT = "gpx2mbtiles/1.0 (personal hiking tool)"

# WMO 天气码 → 中文
WEATHER_CODES = {
    0: "晴", 1: "晴间多云", 2: "多云", 3: "阴",
    45: "雾", 48: "雾凇",
    51: "小毛毛雨", 53: "毛毛雨", 55: "大毛毛雨",
    56: "冻毛毛雨", 57: "强冻毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨",
    66: "冻雨", 67: "强冻雨",
    71: "小雪", 73: "中雪", 75: "大雪",
    77: "雪粒",
    80: "阵雨", 81: "强阵雨", 82: "暴雨",
    85: "阵雪", 86: "强阵雪",
    95: "雷暴", 96: "雷暴伴冰雹", 99: "强雷暴伴冰雹",
}


class WeatherError(RuntimeError):
    """天气查询失败。"""


def describe_code(code) -> str:
    try:
        return WEATHER_CODES.get(int(code), f"天气码{code}")
    except (TypeError, ValueError):
        return "未知"


def fetch_forecast(lat: float, lon: float, settings,
                   start_date: str = "", end_date: str = "",
                   elevation: float | None = None) -> dict:
    """取逐日预报。start/end 为空时取未来 7 天。"""
    params = {
        "latitude": f"{lat:.4f}",
        "longitude": f"{lon:.4f}",
        "daily": ("temperature_2m_max,temperature_2m_min,precipitation_sum,"
                  "precipitation_probability_max,weather_code,wind_speed_10m_max"),
        "timezone": "Asia/Shanghai",
        "forecast_days": "7",
    }
    if elevation:
        params["elevation"] = f"{int(elevation)}"
    if start_date:
        params["start_date"] = start_date
        params["end_date"] = end_date or start_date
        params.pop("forecast_days", None)

    url = API_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    proxy = getattr(settings, "weather_proxy", "") or getattr(settings, "tile_proxy", "")
    if proxy:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"https": proxy, "http": proxy}))
    else:
        opener = urllib.request.build_opener()
    try:
        with opener.open(req, timeout=getattr(settings, "weather_timeout_seconds", 30)) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:200]
        raise WeatherError(f"天气服务返回 {exc.code}：{detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise WeatherError(f"天气查询失败：{exc}") from exc
    except json.JSONDecodeError as exc:
        raise WeatherError(f"天气响应不是合法 JSON：{exc}") from exc

    return normalise(payload)


def normalise(payload: dict) -> dict:
    """把 Open-Meteo 的平行数组整理成逐日列表。"""
    daily = payload.get("daily") or {}
    times = daily.get("time") or []
    out = []
    for i, day in enumerate(times):
        def at(key):
            arr = daily.get(key) or []
            return arr[i] if i < len(arr) else None
        code = at("weather_code")
        out.append({
            "date": day,
            "t_min": at("temperature_2m_min"),
            "t_max": at("temperature_2m_max"),
            "rain_mm": at("precipitation_sum"),
            "rain_p": at("precipitation_probability_max"),
            "code": code,
            "weather": describe_code(code),
            "wind_kmh": at("wind_speed_10m_max"),
        })
    return {
        "timezone": payload.get("timezone"),
        "elevation": payload.get("elevation"),
        "days": out,
    }


# 判定「不适合出行」的阈值：山区徒步的经验值，可按需调整
def day_risk(day: dict) -> list:
    """给一天打风险标记。"""
    risks = []
    rain = day.get("rain_mm") or 0
    rain_p = day.get("rain_p") or 0
    wind = day.get("wind_kmh") or 0
    t_min = day.get("t_min")
    code = day.get("code")

    if rain >= 10:
        risks.append("降雨明显，路滑且可能涨水")
    elif rain >= 2 or rain_p >= 60:
        risks.append("有降雨可能，注意防雨")

    if wind >= 50:
        risks.append("大风，垭口与山脊行走困难")
    elif wind >= 35:
        risks.append("风力较大，山脊注意保暖")

    if t_min is not None and t_min <= -5:
        risks.append("夜间低温，警惕失温")
    elif t_min is not None and t_min <= 0:
        risks.append("夜间接近冰点")

    if code in (95, 96, 99):
        risks.append("雷暴，避免在山脊与高点暴露")
    if code in (71, 73, 75, 85, 86):
        risks.append("有降雪")
    if code in (45, 48):
        risks.append("有雾，注意辨别方向")
    return risks
