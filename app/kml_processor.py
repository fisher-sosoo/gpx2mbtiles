"""KML / KMZ 解析：把元素树转成与格式无关的中间结构。

设计要点（详见 openspec/changes/add-kml-to-gpx-converter/design.md）：

* 只认 Placemark/Point、Placemark/LineString、Placemark/gx:Track，
  其余要素（GroundOverlay 等）跳过并计数，绝不因陌生结构而整体失败。
* 一个 Placemark 可以同时有多个 Track/LineString（MultiGeometry），
  全部展开成独立轨迹段。

命名规则不在这里实现 —— 本模块只负责「如实取出源数据」。
"""
from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree as ET

KML_NS = "http://www.opengis.net/kml/2.2"
GX_NS = "http://www.google.com/kml/ext/2.2"


class KmlParseError(ValueError):
    """KML/KMZ 无法解析或内容无效。"""


@dataclass
class KmlPoint:
    """一个轨迹点或航点。"""

    lat: float
    lon: float
    ele: float | None = None
    time: datetime | None = None          # 已归一化为 UTC
    name: str = ""                        # <name>
    note: str = ""                        # ExtendedData 里的用户备注
    desc_time: datetime | None = None     # description 里「时间：...」解析值（UTC）
    attach_id: str = ""                   # 附件 id（照片）
    attach_name: str = ""                 # 附件原始文件名
    extras: dict = field(default_factory=dict)


@dataclass
class KmlTrack:
    """一条轨迹（一个 Track / LineString 的全部点）。"""

    points: list = field(default_factory=list)
    name: str = ""
    source_name: str = ""         # 轨迹名未经清洗的原值
    extras: dict = field(default_factory=dict)


@dataclass
class KmlResult:
    doc_name: str = ""
    tracks: list = field(default_factory=list)
    start_point: KmlPoint | None = None
    end_point: KmlPoint | None = None
    waypoints: list = field(default_factory=list)
    document_extras: dict = field(default_factory=dict)
    skipped: int = 0


def _local(tag: str) -> str:
    """去掉命名空间前缀。"""
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    if ":" in tag:
        return tag.split(":", 1)[1]
    return tag


def _children(el, *names):
    wanted = set(names)
    return [c for c in list(el) if _local(c.tag) in wanted]


def _child(el, name):
    for c in list(el):
        if _local(c.tag) == name:
            return c
    return None


def _text(el, name: str) -> str:
    c = _child(el, name)
    if c is None or c.text is None:
        return ""
    return c.text.strip()


ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$")


def parse_iso_utc(raw: str) -> datetime | None:
    """解析 2023-02-18T02:35:30Z，统一转成 UTC 时间。

    KML 的 <when> 正常带 Z；个别导出工具省略时区时按 UTC 处理。
    用正则而不用 fromisoformat：前者对 Z 与空格分隔都稳，也不受 Python 版本差异影响。
    """
    if not raw:
        return None
    m = ISO_RE.match(raw.strip())
    if not m:
        return None
    y, mo, d, h, mi, s = (int(m.group(i)) for i in range(1, 7))
    tz = m.group(8)
    try:
        dt = datetime(y, mo, d, h, mi, s, tzinfo=timezone.utc)
    except ValueError:
        return None
    if tz and tz != "Z":
        sign = 1 if tz[0] == "+" else -1
        digits = tz[1:].replace(":", "")
        offset = sign * (int(digits[:2]) * 60 + int(digits[2:4]))
        dt = dt - timedelta(minutes=offset)
    return dt


def _epoch_ms(value: str) -> datetime | None:
    """把 ExtendedData 里的毫秒 epoch 转成 UTC 时间。"""
    try:
        ms = float(value)
    except (TypeError, ValueError):
        return None
    if ms <= 0:
        return None
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)


DESC_TIME_RE = re.compile(r"时间[：:]\s*(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})")
# description 里的「时间」是本机钟点（两步路默认中文时区 UTC+8）。
# 解析时按 UTC 标号再减去偏移，得到的才是真实时刻 —— 实测这条记录 10:43:05
# 还原成 02:43:05Z，与该点 ExtendedData 的 epoch 完全一致。
DESC_CLOCK_UTC_OFFSET_S = 8 * 3600
DESC_LINE_RE = re.compile(r"<div[^>]*>(.*?)</div>", re.S | re.I)
TAG_RE = re.compile(r"<[^>]+>")

# 两步路在 description 里固定输出的四行信息，不算用户备注
_FIXED_LABELS = ("经度", "纬度", "海拔", "时间")


def _html_to_lines(html: str) -> list:
    """把富文本 description 拆成纯文本行，跳过 HTML 与图片。"""
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    parts = DESC_LINE_RE.findall(text) or [text]
    out = []
    for p in parts:
        clean = TAG_RE.sub("", p)
        clean = re.sub(r"&nbsp;", " ", clean).strip()
        if clean:
            out.append(clean)
    return out


def _parse_extended_data(el) -> dict:
    out = {}
    ext = _child(el, "ExtendedData")
    if ext is None:
        return out
    for data in ext.iter():
        if _local(data.tag) != "Data":
            continue
        key = data.get("name") or ""
        if not key:
            continue
        value_el = _child(data, "value")
        out[key] = (value_el.text or "").strip() if value_el is not None else ""
    return out


def _point_from_placemark(pm) -> KmlPoint | None:
    point_el = _child(pm, "Point")
    if point_el is None:
        return None
    coords = _child(point_el, "coordinates")
    if coords is None or not (coords.text or "").strip():
        return None
    first = coords.text.strip().split()[0]
    parts = first.split(",")
    if len(parts) < 2:
        return None
    try:
        lon, lat = float(parts[0]), float(parts[1])
        ele = float(parts[2]) if len(parts) > 2 and parts[2] else None
    except ValueError:
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None

    extras = _parse_extended_data(pm)
    # ExtendedData 里的坐标/海拔更精确，也能补上 coordinates 缺海拔的情况
    for key in ("Latitude", "Longtitude", "Longitude", "Altitude"):
        if key in extras and extras[key]:
            try:
                val = float(extras[key])
            except ValueError:
                continue
            if key == "Latitude":
                lat = val
            elif key in ("Longtitude", "Longitude"):
                lon = val
            else:
                ele = val

    desc_html = _text(pm, "description")
    desc_time = None
    m = DESC_TIME_RE.search(desc_html)
    if m:
        walclock = parse_iso_utc(m.group(1).replace(" ", "T") + "Z")
        if walclock is not None:
            # 本地钟点 → 真实时刻
            desc_time = walclock - timedelta(seconds=DESC_CLOCK_UTC_OFFSET_S)

    note = extras.get("description", "").strip()
    if not note:
        note = " ".join(
            line for line in _html_to_lines(desc_html)
            if not any(line.startswith(label) for label in _FIXED_LABELS))

    time_value = _epoch_ms(extras.get("Time", ""))
    if time_value is None:
        when = _child(pm, "TimeStamp")
        when_t = _child(when, "TimeInstant") if when is not None else None
        if when_t is not None:
            time_value = parse_iso_utc(_text(when_t, "when"))

    return KmlPoint(
        lat=lat, lon=lon, ele=ele, time=time_value,
        name=_text(pm, "name"), note=note, desc_time=desc_time,
        attach_id=extras.get("FileId", ""), attach_name=extras.get("FileName", ""),
        extras=extras,
    )


def _parse_coordinates(text: str) -> list:
    out = []
    for token in (text or "").split():
        parts = token.split(",")
        if len(parts) < 2:
            continue
        try:
            lon, lat = float(parts[0]), float(parts[1])
            ele = float(parts[2]) if len(parts) > 2 and parts[2] else None
        except ValueError:
            continue
        if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0:
            out.append(KmlPoint(lat=lat, lon=lon, ele=ele))
    return out


def _parse_gx_track(el) -> list:
    """gx:Track 的 <when> 与 <gx:coord> 是平行数组。

    两者长度可能不一致（导出工具各有毛病），按较长的循环、缺啥补空 ——
    绝不因长度不等而整条丢弃。
    """
    # 注意：c 本身就是 <when> / <gx:coord> 元素，直接取 text，不能再用 _text(c, "when")
    whens = [(c.text or "").strip() for c in _children(el, "when")]
    coords = [(c.text or "").strip() for c in _children(el, "coord")]
    points = []
    for i in range(max(len(whens), len(coords))):
        coord = coords[i] if i < len(coords) else ""
        parts = coord.split()
        if len(parts) < 2:
            continue
        try:
            lon, lat = float(parts[0]), float(parts[1])
            ele = float(parts[2]) if len(parts) > 2 else None
        except ValueError:
            continue
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            continue
        raw_when = whens[i] if i < len(whens) else ""
        points.append(KmlPoint(lat=lat, lon=lon, ele=ele,
                               time=parse_iso_utc(raw_when) if raw_when else None))
    return points


def _iter_geometry_points(pm):
    """展开 Placemark 下的所有折线，产出点列表。"""
    for child in list(pm):
        name = _local(child.tag)
        if name == "Track":
            pts = _parse_gx_track(child)
            if len(pts) >= 2:
                yield pts
        elif name == "LineString":
            coords = _child(child, "coordinates")
            if coords is None:
                continue
            pts = _parse_coordinates(coords.text or "")
            if len(pts) >= 2:
                yield pts
        elif name in ("MultiGeometry", "MultiTrack"):
            for sub in list(child):
                if _local(sub.tag) == "Track":
                    pts = _parse_gx_track(sub)
                    if len(pts) >= 2:
                        yield pts
                elif _local(sub.tag) == "LineString":
                    coords = _child(sub, "coordinates")
                    if coords is None:
                        continue
                    pts = _parse_coordinates(coords.text or "")
                    if len(pts) >= 2:
                        yield pts


def _special_kind(pm, element_id: str) -> str:
    """识别起终点标记。"""
    if element_id == "startPoint":
        return "start"
    if element_id == "endPoint":
        return "end"
    name = _text(pm, "name")
    if name in ("起点", "起点位置"):
        return "start"
    if name in ("终点", "终点位置"):
        return "end"
    return ""


def decode_text(data: bytes) -> str:
    """尽量保守地解码：先 UTF-8，再 GB18030，最后 latin-1 兜底不抛异常。"""
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace")


def parse_kml_text(text: str) -> KmlResult:
    """解析 KML 文本。"""
    if not text or not text.strip():
        raise KmlParseError("KML 文件为空")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise KmlParseError(f"KML 解析失败：{exc}") from exc
    if _local(root.tag) != "kml":
        raise KmlParseError("不是有效的 KML 文件（根元素不是 <kml>）")

    result = KmlResult()
    doc = None
    for child in list(root):
        if _local(child.tag) in ("Document", "Folder"):
            doc = child
            break
    if doc is None:
        doc = root
    result.doc_name = _text(doc, "name")
    result.document_extras = _parse_extended_data(doc)

    # 遍历顺序即文件顺序 —— 航点序号、起终点判定都依赖它
    for pm in doc.iter():
        if _local(pm.tag) != "Placemark":
            continue
        pid = pm.get("id") or ""
        kind = _special_kind(pm, pid)
        track_points = list(_iter_geometry_points(pm))
        if track_points:
            for pts in track_points:
                result.tracks.append(KmlTrack(
                    points=pts,
                    name=_text(pm, "name"),
                    source_name=_text(pm, "name"),
                    extras=_parse_extended_data(pm),
                ))
            continue
        if _child(pm, "Point") is not None:
            point = _point_from_placemark(pm)
            if point is None:
                result.skipped += 1
                continue
            if kind == "start" and result.start_point is None:
                result.start_point = point
            elif kind == "end" and result.end_point is None:
                result.end_point = point
            else:
                result.waypoints.append(point)
            continue
        result.skipped += 1

    if not result.tracks and not result.waypoints \
            and result.start_point is None and result.end_point is None:
        raise KmlParseError("KML 中未找到任何轨迹或点要素")
    return result


def parse_kml_bytes(data: bytes) -> KmlResult:
    """解析 KML 字节流。"""
    if not data or not data.strip():
        raise KmlParseError("KML 文件为空")
    return parse_kml_text(decode_text(data))


def parse_kmz_bytes(data: bytes) -> KmlResult:
    """解 KMZ：优先 doc.kml，否则取第一个 .kml。"""
    if not data or not data.strip():
        raise KmlParseError("KMZ 文件为空")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise KmlParseError(f"KMZ 解压失败（不是有效的 ZIP）：{exc}") from exc
    try:
        target = None
        for n in zf.namelist():
            if n.lower().endswith("doc.kml"):
                target = n
                break
        if target is None:
            for n in zf.namelist():
                if n.lower().endswith(".kml"):
                    target = n
                    break
        if target is None:
            raise KmlParseError("KMZ 中没有找到 .kml 文件")
        return parse_kml_bytes(zf.read(target))
    finally:
        zf.close()


def looks_like_kmz(data: bytes) -> bool:
    return data[:2] == b"PK"


def parse_any(data: bytes, filename: str = "") -> KmlResult:
    """按内容嗅探 KML / KMZ，文件名只用于辅助判断。"""
    low = (filename or "").lower()
    if low.endswith(".kmz"):
        return parse_kmz_bytes(data)
    if low.endswith(".kml"):
        return parse_kml_bytes(data)
    if looks_like_kmz(data):
        return parse_kmz_bytes(data)
    return parse_kml_bytes(data)
