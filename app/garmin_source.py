"""Garmin 活动取数：预授权令牌 → 活动列表 → 原始 FIT → 归一化轨迹。

设计见 openspec/changes/add-garmin-activity-report/design.md：
- **只读**：只列活动、读详情、下载文件，绝不写账号数据。
- **只存令牌**：账号密码只用在 app/garmin_auth.py 的一次性登录里，运行期不碰。
- **心率 0 = 缺测**：胸带脱落会记 0，在解析层就转 None，避免污染所有统计。
"""
from __future__ import annotations

import io
import json
import logging
import os
import threading
import time
import zipfile
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

_client = None
_client_lock = threading.Lock()
_fetch_lock = threading.Lock()
_last_fetch = 0.0
_last_relogin = 0.0


class GarminError(RuntimeError):
    """Garmin 相关错误的基类。"""


class GarminAuthError(GarminError):
    """缺少令牌、令牌损坏或刷新失败。"""


class GarminUpstreamError(GarminError):
    """上游拒绝或网络不可达。"""


class GarminBusyError(GarminError):
    """另一条活动正在拉取，或两次拉取间隔过短。"""


# ---------------------------------------------------------------- 授权
def token_dir(settings) -> str:
    return os.path.abspath(os.path.expanduser(settings.garmin_tokens))


def has_token(settings) -> bool:
    """令牌目录里至少有一个 JSON（garth 写 oauth1/oauth2 token）。"""
    directory = token_dir(settings)
    if not os.path.isdir(directory):
        return False
    try:
        names = os.listdir(directory)
    except OSError:
        return False
    return any(name.endswith(".json") for name in names)


def _ensure_proxy(settings) -> None:
    """让 garminconnect 走宿主机代理。

    garminconnect 内部用 requests / curl_cffi 发请求，两者都从环境变量取代理，
    没有可以注入 proxies 的入口。容器里如果没有直连出口（本项目部署机就是），
    不设这两个变量会表现为 DNS 解析失败 + 长时间挂起。
    已经设了代理的环境不覆盖。
    """
    proxy = getattr(settings, "garmin_proxy", "") or ""
    if not proxy:
        return
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        if not os.environ.get(key):
            os.environ[key] = proxy
    if not os.environ.get("NO_PROXY"):
        os.environ["NO_PROXY"] = "localhost,127.0.0.1,host.docker.internal"


def new_client(settings, email=None, password=None, prompt_mfa=None):
    """新建客户端。延迟导入 garminconnect：没装也能 import 本模块跑单测。"""
    _ensure_proxy(settings)
    from garminconnect import Garmin

    kwargs = {"is_cn": bool(getattr(settings, "garmin_is_cn", False))}
    if email is not None:
        kwargs["email"] = email
    if password is not None:
        kwargs["password"] = password
    if prompt_mfa is not None:
        kwargs["prompt_mfa"] = prompt_mfa
    # 逐级回退：老版本可能不接受 is_cn / prompt_mfa，但账号密码必须保留，
    # 否则登录会退化成匿名构造，静默失败。
    for attempt in (
        kwargs,
        {k: v for k, v in kwargs.items() if k != "prompt_mfa"},
        {k: v for k, v in kwargs.items() if k not in ("prompt_mfa", "is_cn")},
        {},
    ):
        try:
            return Garmin(**attempt)
        except TypeError:
            continue
    return Garmin()


def get_client(settings):
    """拿一个已登录的客户端；没有令牌或刷新失败时抛 GarminAuthError。"""
    global _client
    with _client_lock:
        if _client is not None:
            return _client
        if not has_token(settings):
            recovered = _auto_relogin(settings)
            if recovered is not None:
                _client = recovered
                return _client
            raise GarminAuthError(
                "服务器上没有 Garmin 授权。请先执行 "
                "docker exec -it gpx2mbtiles python -m app.garmin_auth")
        client = new_client(settings)
        try:
            client.login(token_dir(settings))
        except Exception as exc:  # 令牌过期、被吊销、网络问题都会走到这里
            _client = None
            recovered = _auto_relogin(settings)
            if recovered is not None:
                _client = recovered
                return _client
            raise GarminAuthError(
                "Garmin 授权已失效，请重新执行 python -m app.garmin_auth") from exc
        _client = client
        return client


def _auto_relogin(settings):
    """令牌用不了时，用环境变量里的账号密码重登一次（默认关闭）。

    只在 GARMIN_AUTO_RELOGIN=1 且配了邮箱密码时生效；5 分钟冷却，
    避免密码错了之后疯狂重试把账号刷进风控。
    """
    global _last_relogin
    if not getattr(settings, "garmin_auto_relogin", False):
        return None
    email = getattr(settings, "garmin_email", "")
    password = getattr(settings, "garmin_password", "")
    if not email or not password:
        return None
    if time.monotonic() - _last_relogin < 300:
        raise GarminAuthError(
            "令牌失效且刚刚尝试过自动重登，请 5 分钟后再试，或手动执行 "
            "python -m app.garmin_auth --force")
    _last_relogin = time.monotonic()
    logger.warning("Garmin 令牌不可用，尝试用环境变量里的账号重新登录")
    client = new_client(settings, email=email, password=password)
    try:
        client.login(token_dir(settings))
    except Exception as exc:
        raise GarminAuthError(
            "自动重登失败（检查 GARMIN_EMAIL / GARMIN_PASSWORD / GARMIN_IS_CN）："
            f"{exc}") from exc
    return client


def reset_client() -> None:
    """丢弃缓存的客户端（令牌更新或测试用）。"""
    global _client
    with _client_lock:
        _client = None


# ---------------------------------------------------------------- 工具
def _number(value):
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None  # 排除 NaN


def _coord(value):
    """FIT 的 position_* 是 int32 半圆；已经是度数时原样返回。"""
    num = _number(value)
    if num is None:
        return None
    if abs(num) > 1_000_000:
        return num * (180.0 / (2 ** 31))
    return num


def _parse_dt(value):
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------- 活动列表
def list_activities(settings, days=None) -> list:
    """最近 N 天内的活动，归一化成页面直接可用的四个字段。"""
    window = int(days or getattr(settings, "garmin_days_default", 30))
    limit = int(getattr(settings, "garmin_activity_limit", 50))
    client = get_client(settings)
    try:
        raw = client.get_activities(0, limit) or []
    except Exception as exc:
        raise GarminUpstreamError(f"拉取活动列表失败：{exc}") from exc

    cutoff = datetime.now(timezone.utc) - timedelta(days=window)
    out = []
    for item in raw:
        started = _parse_dt(item.get("startTimeGMT") or item.get("startTimeLocal"))
        if started is not None and started < cutoff:
            continue
        kind = item.get("activityType") or {}
        out.append({
            "id": int(item.get("activityId")),
            "name": (item.get("activityName") or "").strip() or "未命名活动",
            "date": str(item.get("startTimeLocal") or "")[:16] or None,
            "distance_m": _number(item.get("distance")),
            "duration_s": _number(item.get("duration")),
            "type": kind.get("typeKey") if isinstance(kind, dict) else None,
        })
    return out


def _unwrap_fit(data: bytes) -> bytes:
    """Garmin 的「原始文件」接口回的是 zip（内含 .fit），不是裸 FIT。

    实测：download_activity(ORIGINAL) 返回 PK\x03\x04 开头的 zip。
    """
    if data[:2] != b"PK":
        return data
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = [n for n in archive.namelist() if n.lower().endswith(".fit")]
            if names:
                return archive.read(names[0])
    except (zipfile.BadZipFile, KeyError, OSError) as exc:
        logger.warning("活动压缩包解不开：%s", exc)
    return data


def _activity_meta(client, activity_id):
    try:
        info = client.get_activity(activity_id) or {}
    except Exception as exc:  # 元信息拿不到不该挡住出图
        logger.info("取活动 %s 元信息失败：%s", activity_id, exc)
        return {}
    return {
        "name": (info.get("activityName") or "").strip(),
        "start": info.get("startTimeLocal") or info.get("startTimeGMT"),
    }


# ---------------------------------------------------------------- 下载
def _download_bytes(client, activity_id) -> bytes:
    # 不同版本这个枚举挂的位置不一样，取不到就退回默认下载格式。
    fmt = None
    try:
        fmt = client.ActivityDownloadFormat.ORIGINAL
    except Exception:
        try:
            from garminconnect import Garmin
            fmt = Garmin.ActivityDownloadFormat.ORIGINAL
        except Exception:
            fmt = None
    try:
        if fmt is None:
            result = client.download_activity(activity_id)
        else:
            result = client.download_activity(activity_id, dl_fmt=fmt)
    except TypeError:
        result = client.download_activity(activity_id)
    except Exception as exc:
        raise GarminUpstreamError(f"下载活动 {activity_id} 失败：{exc}") from exc

    if isinstance(result, (bytes, bytearray)):
        return bytes(result)
    if isinstance(result, str) and os.path.isfile(result):
        with open(result, "rb") as fh:
            return fh.read()
    if hasattr(result, "read"):
        return result.read()
    raise GarminUpstreamError(f"活动 {activity_id} 的下载结果无法识别")


# ---------------------------------------------------------------- 解析
def normalize_records(records) -> list:
    """把 FIT record 字典列表归一化成轨迹点。纯函数，便于离线测试。

    缺字段一律 None；心率 0（胸带脱落）也算缺测；同一秒只保留第一个点。
    """
    points = []
    for rec in records or []:
        stamp = rec.get("timestamp")
        if isinstance(stamp, datetime):
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            ts = int(stamp.timestamp())
        else:
            ts = _number(stamp)
        lat = _coord(rec.get("position_lat"))
        lng = _coord(rec.get("position_long"))
        if ts is None or lat is None or lng is None:
            continue

        ele = _number(rec.get("enhanced_altitude"))
        if ele is None:
            ele = _number(rec.get("altitude"))

        hr = _number(rec.get("heart_rate"))
        if hr is not None and (hr <= 0 or hr > 300):
            hr = None

        cad = _number(rec.get("cadence"))
        if cad is not None and cad < 0:
            cad = None

        temp = _number(rec.get("temperature"))

        points.append({
            "t": int(ts),
            "lat": round(lat, 7),
            "lng": round(lng, 7),
            "ele": None if ele is None else round(ele, 1),
            "hr": None if hr is None else int(round(hr)),
            "cad": None if cad is None else int(round(cad)),
            "temp": None if temp is None else round(temp, 1),
        })

    points.sort(key=lambda p: p["t"])
    deduped, last = [], None
    for point in points:
        if point["t"] == last:
            continue
        deduped.append(point)
        last = point["t"]
    return deduped


def parse_fit(data: bytes) -> list:
    """解 FIT；解析器不认识的记录直接跳过，不让整页失败。"""
    try:
        from fitparse import FitFile
    except ImportError as exc:  # pragma: no cover - 依赖缺失时的明确报错
        raise GarminUpstreamError("缺少 fitparse 依赖，无法解析活动文件") from exc
    try:
        fit = FitFile(io.BytesIO(data))
        records = [{field.name: field.value for field in message}
                   for message in fit.get_messages("record")]
    except Exception as exc:
        logger.warning("FIT 解析失败：%s", exc)
        return []
    return normalize_records(records)


# ---------------------------------------------------------------- 缓存
def cache_dir(settings) -> str:
    path = os.path.join(settings.data_dir, "garmin")
    os.makedirs(path, exist_ok=True)
    return path


def cache_paths(settings, activity_id) -> tuple:
    base = cache_dir(settings)
    return (os.path.join(base, f"{activity_id}.fit"),
            os.path.join(base, f"{activity_id}.json"))


def _evict(settings) -> None:
    """按最近修改时间淘汰，直到总量回到上限以内。"""
    limit = int(getattr(settings, "garmin_cache_max_mb", 512)) * 1024 * 1024
    if limit <= 0:
        return
    base = cache_dir(settings)
    entries = []
    for name in os.listdir(base):
        path = os.path.join(base, name)
        try:
            stat = os.stat(path)
        except OSError:
            continue
        entries.append((stat.st_mtime, stat.st_size, path))
    total = sum(size for _, size, _ in entries)
    if total <= limit:
        return
    for _, size, path in sorted(entries):
        try:
            os.remove(path)
        except OSError:
            continue
        total -= size
        if total <= limit:
            break


def _enter_fetch(settings) -> None:
    if not _fetch_lock.acquire(blocking=False):
        raise GarminBusyError("正在拉取另一条活动，请稍后再试")
    try:
        gap = float(getattr(settings, "garmin_min_interval_seconds", 1.0))
        wait = gap - (time.monotonic() - _last_fetch)
        if wait > 0:
            time.sleep(min(wait, gap))
    except BaseException:
        _fetch_lock.release()
        raise


def _release_fetch() -> None:
    global _last_fetch
    _last_fetch = time.monotonic()
    if _fetch_lock.locked():
        _fetch_lock.release()


def load_activity(settings, activity_id, refresh=False) -> dict:
    """取一条活动：命中缓存直接返回，否则下载 FIT、解析、落盘。"""
    activity_id = int(activity_id)
    fit_path, json_path = cache_paths(settings, activity_id)
    if not refresh and os.path.isfile(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            logger.warning("活动 %s 的缓存损坏，重新拉取", activity_id)

    _enter_fetch(settings)
    try:
        client = get_client(settings)
        data = _unwrap_fit(_download_bytes(client, activity_id))
        with open(fit_path, "wb") as fh:
            fh.write(data)
        points = parse_fit(data)
        meta = _activity_meta(client, activity_id)
        payload = {
            "id": activity_id,
            "name": meta.get("name") or f"活动 {activity_id}",
            "start": meta.get("start"),
            "points": points,
            "partial": not points,
        }
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
        _evict(settings)
        return payload
    finally:
        _release_fetch()


def status(settings) -> dict:
    enabled = bool(getattr(settings, "garmin_enabled", True))
    return {
        "enabled": enabled,
        "authorized": has_token(settings) if enabled else False,
        "tokens_dir": token_dir(settings) if enabled else None,
        "days_default": int(getattr(settings, "garmin_days_default", 30)),
    }
