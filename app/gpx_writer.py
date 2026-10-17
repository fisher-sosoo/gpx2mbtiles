"""GPX 1.1 输出。

只用标准元素承载坐标、海拔与时间，自定义内容放 <extensions>：
标准元素保证任何 App 都能读，扩展字段留给愿意读的工具。
"""
from __future__ import annotations

from datetime import datetime, timezone
from xml.sax.saxutils import escape, quoteattr

GPX_NS = "http://www.topografix.com/GPX/1/1"
GX_NS = "http://www.garmin.com/xmlschemas/GpxExtensions/v3"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"

# 坐标统一输出 6 位小数（约 0.1 米），与源数据精度一致
COORD_FMT = "{:.6f}"


def _cdata(text) -> str:
    """GPX 文本字段统一转义，避免中文与 <>& 被解析器吃掉。"""
    return escape(str(text or ""))


def _utc(dt: datetime | None) -> str:
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class GpxDocument:
    """流式拼装 GPX。"""

    def __init__(self, creator: str = "gpx2mbtiles-kml-converter"):
        self.creator = creator
        self._parts: list = []
        self._open = False

    def _ensure_open(self):
        if self._open:
            return
        self._parts.append(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<gpx xmlns="{GPX_NS}" xmlns:xsi="{XSI_NS}" xmlns:gx="{GX_NS}"'
            f' version="1.1" creator={quoteattr(self.creator)}>\n')
        self._open = True

    def metadata(self, name: str = "", desc: str = "", author: str = "",
                 time: datetime | None = None):
        self._ensure_open()
        lines = ["  <metadata>\n"]
        if name:
            lines.append(f"    <name>{_cdata(name)}</name>\n")
        if desc:
            lines.append(f"    <desc>{_cdata(desc)}</desc>\n")
        if author:
            lines.append("    <author>\n")
            lines.append(f"      <name>{_cdata(author)}</name>\n")
            lines.append("    </author>\n")
        if time is not None:
            lines.append(f"    <time>{_utc(time)}</time>\n")
        lines.append("  </metadata>\n")
        self._parts.extend(lines)

    def waypoint(self, lat: float, lon: float, ele: float | None,
                 time: datetime | None, name: str, desc: str = "",
                 cmt: str = "", sym: str = "", extensions: dict | None = None):
        self._ensure_open()
        self._parts.append(
            f'  <wpt lat={quoteattr(COORD_FMT.format(lat))}'
            f' lon={quoteattr(COORD_FMT.format(lon))}>\n')
        if ele is not None:
            self._parts.append(f"    <ele>{COORD_FMT.format(ele)}</ele>\n")
        if time is not None:
            self._parts.append(f"    <time>{_utc(time)}</time>\n")
        if name:
            self._parts.append(f"    <name>{_cdata(name)}</name>\n")
        if cmt:
            self._parts.append(f"    <cmt>{_cdata(cmt)}</cmt>\n")
        if desc:
            self._parts.append(f"    <desc>{_cdata(desc)}</desc>\n")
        if sym:
            self._parts.append(f"    <sym>{_cdata(sym)}</sym>\n")
        self._extensions(extensions, indent="    ")
        self._parts.append("  </wpt>\n")

    def track(self, name: str, points, desc: str = "",
              extensions: dict | None = None):
        """points: 可迭代的 (lat, lon, ele, time, desc) 元组。"""
        self._ensure_open()
        self._parts.append("  <trk>\n")
        if name:
            self._parts.append(f"    <name>{_cdata(name)}</name>\n")
        if desc:
            self._parts.append(f"    <desc>{_cdata(desc)}</desc>\n")
        if extensions:
            self._extensions(extensions, indent="    ", tag="extensions")
        self._parts.append("    <trkseg>\n")
        for lat, lon, ele, tm, pdesc in points:
            self._parts.append(
                f'      <trkpt lat={quoteattr(COORD_FMT.format(lat))}'
                f' lon={quoteattr(COORD_FMT.format(lon))}>\n')
            if ele is not None:
                self._parts.append(f"        <ele>{COORD_FMT.format(ele)}</ele>\n")
            if tm is not None:
                self._parts.append(f"        <time>{_utc(tm)}</time>\n")
            if pdesc:
                self._parts.append(f"        <desc>{_cdata(pdesc)}</desc>\n")
            self._parts.append("      </trkpt>\n")
        self._parts.append("    </trkseg>\n")
        self._parts.append("  </trk>\n")

    def _extensions(self, extensions: dict | None, indent: str,
                    tag: str = "extensions"):
        if not extensions:
            return
        items = [(k, v) for k, v in extensions.items() if v not in (None, "")]
        if not items:
            return
        self._parts.append(f"{indent}<{tag}>\n")
        for key, value in items:
            safe_key = _xml_name(key)
            self._parts.append(
                f"{indent}  <{safe_key}>{_cdata(value)}</{safe_key}>\n")
        self._parts.append(f"{indent}</{tag}>\n")

    def to_string(self) -> str:
        self._ensure_open()
        return "".join(self._parts) + "</gpx>\n"


def _xml_name(key: str) -> str:
    """把任意 key 变成合法的 XML 标签名。"""
    cleaned = "".join(ch if (ch.isalnum() or ch in "-_.") else "_" for ch in str(key))
    if not cleaned or not (cleaned[0].isalpha() or cleaned[0] == "_"):
        cleaned = "x_" + cleaned
    return cleaned
