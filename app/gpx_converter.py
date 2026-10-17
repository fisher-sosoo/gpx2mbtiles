"""KML/KMZ → GPX 的转换流程：解析 → 定位 → 命名 → 输出。

对外只暴露 convert()，返回 GPX 文本与可直接展示的摘要。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import ai_naming
from . import kml_naming as naming
from .gpx_writer import GpxDocument
from .kml_processor import KmlParseError, KmlResult, parse_any

# 摘要里扩展字段的上限：太多只会让页面难看
MAX_EXTRA_FIELDS = 12
# 轨迹级扩展字段里，这些键已经在 name/desc 里体现，不再重复输出
_TRACK_EXTRA_SKIP = {"name", "Position", "color"}


@dataclass
class ConvertSummary:
    doc_name: str = ""
    source_name: str = ""
    tracks: list = field(default_factory=list)     # [{name, points, distance_m}]
    waypoints: list = field(default_factory=list)  # [{name, source, km, elapsed_s, ele}]
    start_point: dict | None = None
    end_point: dict | None = None
    name_sources: dict = field(default_factory=dict)
    point_count: int = 0
    waypoint_count: int = 0
    skipped: int = 0
    distance_m: float = 0.0
    declared_distance_m: float | None = None
    sport: str = ""
    date: str = ""
    degraded: list = field(default_factory=list)
    ai_used: bool = False
    ai_named: int = 0
    ai_error: str = ""

    def to_dict(self) -> dict:
        return {
            "doc_name": self.doc_name,
            "source_name": self.source_name,
            "tracks": self.tracks,
            "waypoints": self.waypoints,
            "start_point": self.start_point,
            "end_point": self.end_point,
            "name_sources": self.name_sources,
            "point_count": self.point_count,
            "waypoint_count": self.waypoint_count,
            "skipped": self.skipped,
            "distance_m": round(self.distance_m, 1),
            "declared_distance_m": self.declared_distance_m,
            "sport": self.sport,
            "date": self.date,
            "degraded": self.degraded,
            "ai_used": self.ai_used,
            "ai_named": self.ai_named,
            "ai_error": self.ai_error,
        }


@dataclass
class ConvertResult:
    gpx: str
    filename: str
    summary: ConvertSummary


def _declared_distance(result: KmlResult) -> float | None:
    """文件自报的里程（两步路写在 Document 的 ExtendedData 里）。"""
    for key in ("Distance", "Mileage"):
        raw = (result.document_extras or {}).get(key, "")
        try:
            val = float(raw)
        except (TypeError, ValueError):
            continue
        if val > 0:
            return val
    return None


def _extra_fields(extras: dict, limit: int = MAX_EXTRA_FIELDS) -> dict:
    """把 Source 的扩展字段整理成可写入 GPX extensions 的扁平 kv。"""
    out = {}
    for key, value in (extras or {}).items():
        if key in _TRACK_EXTRA_SKIP or not value:
            continue
        # 附件 id 之类纯数字且超长的字段仍保留 —— 用户可能需要回溯原图
        out[key] = value
        if len(out) >= limit:
            break
    return out


def _apply_ai_names(result: KmlResult, wp_names: list, summary: ConvertSummary,
                    stats, settings) -> None:
    """把模型给的名字写进那些「没有人工名称」的航点。

    人工名称（文件里的 <name> / 用户备注）永远优先，AI 只填空缺。
    失败时把原因写进摘要，页面据此提示，转换照常继续。
    """
    if settings is None or not ai_naming.is_configured(settings):
        summary.ai_error = "未配置 AI_API_KEY"
        return
    candidates = []
    for idx, (point, named) in enumerate(zip(result.waypoints, wp_names)):
        # 只给「位置名称」或「附件名」这类机器生成的航点起名
        if named.source in ("name", "note"):
            continue
        candidates.append({
            "seq": idx + 1,
            "km": named.km or 0.0,
            "elapsed_s": named.elapsed_s,
            "ele": point.ele,
            "turn": named.turn,
            "turn_text": named.turn_text,
        })
    if not candidates:
        # 全部航点都已有原始名称 —— 正常情况，不算错误
        summary.ai_used = False
        return
    try:
        names = ai_naming.suggest_names(candidates, summary, stats.distance_m, settings)
    except ai_naming.AiNamingError as exc:
        summary.ai_error = str(exc)
        return
    except Exception as exc:                       # 兜底：任何意外都不能拖垮转换
        summary.ai_error = f"AI 命名异常：{exc}"
        return

    applied = 0
    for seq, ai_name in names.items():
        named = wp_names[seq - 1]
        named.text = f"{named.text.split(' ')[0]} {ai_name}"
        named.source = "ai"
        applied += 1
    summary.ai_used = applied > 0
    summary.ai_named = applied


def safe_filename(name: str, fallback: str = "track") -> str:
    """文件名只留安全字符；中文保留（iOS 文件 App 完全支持）。"""
    cleaned = "".join(
        ch for ch in (name or "")
        if ch.isalnum() or ch in "-_ .（）()·"
    ).strip().strip(".")
    cleaned = cleaned.replace("/", "_").replace("\\", "_")
    return (cleaned or fallback)[:80]


def convert(data: bytes, filename: str = "", custom_name: str = "",
            ai_names: bool = False, settings=None) -> ConvertResult:
    """字节流 → GPX。异常统一抛 KmlParseError。

    ai_names=True 且配置了密钥时，额外调一次模型给「没有名字的航点」起语义名称；
    任何失败都只记录原因（ai_error），不影响转换本身。
    """
    result = parse_any(data, filename)
    if not result.tracks and not result.waypoints \
            and result.start_point is None and result.end_point is None:
        raise KmlParseError("文件中未找到任何轨迹或点要素")

    source_label = filename.rsplit(".", 1)[0] if filename else ""
    summary = ConvertSummary(
        doc_name=result.doc_name,
        source_name=source_label,
        skipped=result.skipped,
    )

    track_names = naming.track_names(result, source_label, custom_name)

    # 主轨迹：点数最多的一条，用来给航点定位（沿用文件中第一条也没有更优的判据）
    main_points = []
    for track in result.tracks:
        if len(track.points) > len(main_points):
            main_points = track.points

    stats = naming.track_stats(main_points) if main_points else naming.TrackStats()
    # 航点定位用的轨迹。无轨迹时退化为「航点首尾连线」，
    # 但只在达到 2 个点以上才算数 —— 单个点连不成折线，里程恒为 0，
    # 此时位置名称没有任何信息量，应交回附件/时间兜底。
    locate_points = main_points
    if not locate_points:
        chain = [p for p in ([result.start_point] if result.start_point else [])
                 + list(result.waypoints)
                 + ([result.end_point] if result.end_point else []) if p]
        if len(chain) >= 2:
            locate_points = chain
            stats = naming.track_stats(chain)
            summary.degraded.append("no_track")

    wp_names = naming.name_waypoints(result, locate_points, stats)

    if ai_names:
        _apply_ai_names(result, wp_names, summary, stats, settings)

    summary.distance_m = stats.distance_m
    summary.declared_distance_m = _declared_distance(result)
    summary.sport = naming.sport_label(result)
    summary.date = naming.start_date(result.tracks, source_label or result.doc_name)

    doc = GpxDocument()
    first_time = None
    for track in result.tracks:
        for p in track.points:
            if p.time is not None:
                first_time = p.time
                break
        if first_time is not None:
            break

    meta_desc = ""
    if summary.sport:
        meta_desc = f"运动类型：{summary.sport}"
    doc.metadata(name=track_names[0] if track_names else source_label,
                 desc=meta_desc,
                 author=(result.document_extras or {}).get("CreaterName", ""),
                 time=first_time)

    doc_extras = _extra_fields(result.document_extras)

    def _wpt(point, name, desc, sym):
        doc.waypoint(
            lat=point.lat, lon=point.lon, ele=point.ele,
            time=point.desc_time or point.time,
            name=name, desc=desc,
            sym=sym,
        )

    # 起点 / 终点：分别命名，不占普通航点序号
    for label, point, sym in (
            ("起点", result.start_point, "Flag, Green"),
            ("终点", result.end_point, "Flag, Red")):
        if point is None:
            continue
        km = None
        if locate_points:
            km = naming.along_distance_m(locate_points, stats, point) / 1000.0
        desc_lines = []
        if km is not None:
            desc_lines.append(f"已走 {naming.fmt_distance(km)}")
        if point.ele is not None:
            desc_lines.append(f"海拔 {int(round(point.ele))} m")
        _wpt(point, label, " · ".join(desc_lines), sym)
        info = {"name": label, "km": round(km, 2) if km is not None else None}
        if label == "起点":
            summary.start_point = info
        else:
            summary.end_point = info

    for point, named in zip(result.waypoints, wp_names):
        elapsed = named.elapsed_s
        desc_lines = []
        # 备注写进 desc：只展示描述字段的 App 也能看到用户写的话
        if named.note:
            desc_lines.append(f"备注：{named.note}")
        if named.km is not None:
            desc_lines.append(f"已走 {naming.fmt_distance(named.km)}")
        if elapsed is not None:
            desc_lines.append(f"累计 {naming.fmt_seconds(elapsed)}")
        if point.ele is not None:
            desc_lines.append(f"海拔 {int(round(point.ele))} m")
        if named.turn_text and named.turn_text != "直行":
            desc_lines.append(f"转向 {named.turn_text}")
        if named.orig_name and named.orig_name not in named.text:
            desc_lines.append(f"原名称：{named.orig_name}")
        if point.attach_id:
            desc_lines.append(f"附件 ID：{point.attach_id}")
        # cmt 放备注原文，方便在 App 的注释栏里直接读到
        cmt = named.note or (named.orig_name
                             if named.orig_name and named.orig_name not in named.text else "")
        doc.waypoint(
            lat=point.lat, lon=point.lon, ele=point.ele,
            time=point.desc_time or point.time,
            name=named.text,
            desc=" · ".join(desc_lines),
            cmt=cmt,
            sym="Flag, Blue",
        )
        summary.waypoints.append({
            "name": named.text,
            "source": named.source,
            "km": round(named.km, 2) if named.km is not None else None,
            "elapsed_s": round(elapsed) if elapsed is not None else None,
            "ele": round(point.ele, 1) if point.ele is not None else None,
            "note": named.note,
            "turn": round(named.turn, 1) if named.turn is not None else None,
            "turn_text": named.turn_text,
            # 坐标给前端在地图上圈风险点用
            "lat": round(point.lat, 6),
            "lon": round(point.lon, 6),
        })
        summary.name_sources[named.source] = summary.name_sources.get(named.source, 0) + 1

    # 轨迹：逐点写入累计里程与累计耗时，只显示 desc 的 App 也能看出进度
    for idx, track in enumerate(result.tracks):
        name = track_names[idx] if idx < len(track_names) else track_names[0]
        tstats = naming.track_stats(track.points)
        start = next((p.time for p in track.points if p.time is not None), None)
        rows = []
        for i, p in enumerate(track.points):
            piece = ""
            if tstats.distance_m > 0:
                piece = (f"已走 {naming.fmt_distance(tstats.cum[i] / 1000.0)}")
                if start is not None and p.time is not None:
                    delta = (p.time - start).total_seconds()
                    if delta >= 0:
                        piece += f" · 累计 {naming.fmt_seconds(delta)}"
            rows.append((p.lat, p.lon, p.ele, p.time, piece))
        doc.track(
            name=name,
            points=rows,
            desc=f"里程 {naming.fmt_distance(tstats.distance_m / 1000.0)}"
                 if tstats.distance_m > 0 else "",
            extensions=doc_extras,
        )
        summary.tracks.append({
            "name": name,
            "points": len(track.points),
            "distance_m": round(tstats.distance_m, 1),
        })

    summary.waypoint_count = len(result.waypoints)
    summary.point_count = sum(len(t.points) for t in result.tracks) + \
        len(result.waypoints) + (1 if result.start_point else 0) + \
        (1 if result.end_point else 0)

    if summary.declared_distance_m and summary.distance_m:
        ratio = summary.distance_m / summary.declared_distance_m
        if not (0.9 <= ratio <= 1.1):
            summary.degraded.append("distance_mismatch")

    base = summary.tracks[0]["name"] if summary.tracks else (
        track_names[0] if track_names else source_label or "track")
    return ConvertResult(gpx=doc.to_string(),
                         filename=f"{safe_filename(base, 'track')}.gpx",
                         summary=summary)


def extract_points(data: bytes, filename: str = ""):
    """给生成器页复用：从 GPX 之外的格式里取轨迹点与名称。

    返回 (points[(lat, lon)], name, extra_points)；extra_points 是航点，
    生成器把它们也算进瓦片覆盖范围（与原 GPX 行为一致）。
    """
    result = parse_any(data, filename)
    points = []
    for track in result.tracks:
        for p in track.points:
            points.append((p.lat, p.lon))
    extra = []
    for p in ([result.start_point] if result.start_point else []) \
            + list(result.waypoints) + ([result.end_point] if result.end_point else []):
        extra.append((p.lat, p.lon))

    source_label = filename.rsplit(".", 1)[0] if filename else ""
    names = naming.track_names(result, source_label, "")
    return points, (names[0] if names else source_label or "track"), extra
