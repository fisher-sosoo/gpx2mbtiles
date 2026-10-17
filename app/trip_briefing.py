"""行前指南：把轨迹、地名点与天气合成一份出发前能读的分析。

设计取舍：

* **结构化先算，叙述后写**。里程、关键节点、天气窗口、风险标记全部由规则算出，
  模型只负责把这些事实写成通顺的分析。这样即使没有 AI，指南依然成立。
* **不臆造地名**。地名全部来自 OSM 查询结果，模型只能引用已有条目。
"""
from __future__ import annotations

import logging

from . import weather as weather_mod

logger = logging.getLogger(__name__)

# 关键节点优先级：行前最该知道的是垭口，其次是营地与过河
KEY_PRIORITY = {
    "saddle": 0, "mountain_pass": 0,
    "river": 1,
    "camp_site": 2, "alpine_hut": 2, "wilderness_hut": 2, "shelter": 2,
    "water": 3, "peak": 3, "viewpoint": 3,
}


def _fmt_m(v):
    if v is None:
        return "-"
    return "%.0f m" % v


def _fmt_km(v):
    if v is None:
        return "-"
    return "%.2f km" % v


def key_points(pois: list, limit: int = 14) -> list:
    """按里程排序的关键节点（垭口优先，同名去重）。"""
    items = [p for p in (pois or []) if p.get("km") is not None]
    items.sort(key=lambda p: (p.get("km") or 0))
    # 同名只留一次
    seen = set()
    out = []
    for p in items:
        key = (p.get("name"), p.get("kind"))
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    out.sort(key=lambda p: (KEY_PRIORITY.get(p.get("kind"), 9), p.get("km") or 0))
    out = out[:limit]
    out.sort(key=lambda p: p.get("km") or 0)
    return out


def elevation_profile(summary: dict) -> dict:
    """从摘要里提取海拔与强度信息。"""
    tracks = summary.get("tracks") or []
    dist_m = summary.get("distance_m") or 0.0
    return {
        "distance_km": round(dist_m / 1000.0, 2),
        "segments": len(tracks),
        "declared_distance_m": summary.get("declared_distance_m"),
        "sport": summary.get("sport") or "",
        "date": summary.get("date") or "",
    }


def build_risks(summary: dict, pois: list, weather: dict) -> list:
    """规则化的风险清单。"""
    risks = []
    points = pois or []

    passes = [p for p in points if p.get("kind") in ("saddle", "mountain_pass")]
    high = [p for p in passes if (p.get("ele") or 0) >= 4000]
    if high:
        names = "、".join("%s(%dm)" % (p["name"], int(p["ele"]))
                         for p in high[:3])
        risks.append("高海拔垭口 %d 个：%s。注意高反、天气突变与失温。"
                     % (len(high), names))
    elif passes:
        risks.append("沿途经过 %d 个垭口，翻越前后风大温低。" % len(passes))

    rivers = [p for p in points if p.get("kind") == "river"]
    if rivers:
        names = "、".join(p["name"] for p in rivers[:3])
        risks.append("需要过河 %d 处（%s）。雨后水位上涨，勿强行通过。"
                     % (len(rivers), names))

    dist = summary.get("distance_m") or 0
    if dist >= 30000:
        risks.append("全程 %.1f km，属长线，需评估单日强度或安排中途扎营。"
                     % (dist / 1000.0))

    days = (weather or {}).get("days") or []
    flagged = [(d, weather_mod.day_risk(d)) for d in days]
    flagged = [(d, r) for d, r in flagged if r]
    if flagged:
        # 报「风险条数最多」的那天，而不是第一天 —— 用户要避开的是最差窗口
        flagged.sort(key=lambda x: -len(x[1]))
        worst, worst_risks = flagged[0]
        label = "%s（%s）" % (worst.get("date"), worst.get("weather"))
        risks.append("%s 天气最差：%s。" % (label, "；".join(worst_risks)))
        if len(flagged) > 1:
            others = "、".join(d.get("date") for d, _ in flagged[1:4])
            risks.append("其余需留意：%s。" % others)
    return risks


def build_mistakes(summary: dict, pois: list, waypoints: list) -> list:
    """易错点：转向密集、过河、营地与水点位置。"""
    tips = []
    turns = [w for w in (waypoints or []) if w.get("turn_text")
             and w["turn_text"] != "直行"]
    if turns:
        # 给出里程位置，否则「4 处发卡弯」这种说法用户根本不知道在哪
        spots = []
        for t in turns[:6]:
            km = t.get("km")
            label = t.get("turn_text") or ""
            if km is None:
                spots.append(label)
            else:
                spots.append("%.1fkm %s" % (km, label))
        detail = "、".join(s for s in spots if s)
        hairpins = [t for t in turns if "发卡" in (t.get("turn_text") or "")]
        if hairpins:
            tips.append("折返/发卡弯 %d 处（%s），容易顺岔路下沟，注意沿主路走。"
                        % (len(hairpins), detail))
        else:
            tips.append("明显转向 %d 处（%s），岔路口注意辨认方向。" % (len(turns), detail))

    camps = [p for p in (pois or []) if p.get("kind") in
             ("camp_site", "alpine_hut", "wilderness_hut", "shelter")]
    if camps:
        tips.append("沿途 %d 处牛场/营地可作补给或应急扎营：%s。"
                    % (len(camps), "、".join(c["name"] for c in camps[:3])))

    waters = [p for p in (pois or []) if p.get("kind") == "water"]
    if waters:
        tips.append("湖泊水点 %d 处（%s），高海拔水点补给需自行净化。"
                    % (len(waters), "、".join(w["name"] for w in waters[:2])))
    return tips


def build_overview(summary: dict, pois: list, weather: dict) -> str:
    tracks = summary.get("tracks") or [{}]
    name = tracks[0].get("name") or "未命名路线"
    dist = (summary.get("distance_m") or 0) / 1000.0
    bits = ["%s 全程 %.2f km" % (name, dist)]
    if summary.get("sport"):
        bits.append(summary["sport"])
    if summary.get("date"):
        bits.append(summary["date"])
    if len(tracks) > 1:
        bits.append("%d 段" % len(tracks))
    peaks = [p for p in (pois or []) if p.get("kind") == "peak" and p.get("ele")]
    if peaks:
        top = max(peaks, key=lambda p: p["ele"])
        bits.append("最高可见峰 %s %s" % (top["name"], _fmt_m(top["ele"])))
    passes = [p for p in (pois or []) if p.get("kind") in ("saddle", "mountain_pass")]
    if passes:
        bits.append("途经 %d 个垭口" % len(passes))
    return "，".join(bits) + "。"


def render_markdown(brief: dict) -> str:
    """把结构化指南渲染成可直接存手机的 Markdown。"""
    lines = ["# 行前指南 · %s" % (brief.get("title") or "路线"), ""]
    if brief.get("range"):
        lines.append("**日期范围**：%s" % brief["range"])
        lines.append("")
    lines.append("## 路线概况")
    lines.append(brief.get("overview") or "-")
    lines.append("")

    kps = brief.get("key_points") or []
    if kps:
        lines.append("## 关键节点")
        lines.append("")
        lines.append("| 里程 | 名称 | 类型 | 海拔 |")
        lines.append("|---|---|---|---|")
        for p in kps:
            lines.append("| %.2f km | %s | %s | %s |" % (
                p.get("km") or 0, p.get("name") or "", p.get("type_label") or "",
                _fmt_m(p.get("ele")) if p.get("ele") else "-"))
        lines.append("")

    days = (brief.get("weather") or {}).get("days") or []
    if days:
        lines.append("## 天气")
        lines.append("")
        lines.append("| 日期 | 天气 | 温度 | 降水 | 概率 | 风速 |")
        lines.append("|---|---|---|---|---|---|")
        for d in days:
            lines.append("| %s | %s | %s~%s | %s mm | %s%% | %s km/h |" % (
                d.get("date"), d.get("weather"),
                _q(d.get("t_min")), _q(d.get("t_max")),
                _q(d.get("rain_mm")), _q(d.get("rain_p")), _q(d.get("wind_kmh"))))
        lines.append("")

    risks = brief.get("risks") or []
    if risks:
        lines.append("## 风险提示")
        for r in risks:
            lines.append("- %s" % r)
        lines.append("")

    mistakes = brief.get("mistakes") or []
    if mistakes:
        lines.append("## 易错点")
        for m in mistakes:
            lines.append("- %s" % m)
        lines.append("")

    if brief.get("ai_narrative"):
        lines.append("## 综合分析")
        lines.append(brief["ai_narrative"])
        lines.append("")

    if brief.get("ai_error"):
        lines.append("> 综合分析未生成：%s" % brief["ai_error"])
        lines.append("")
    return "\n".join(lines)


def _q(v):
    if v is None:
        return "-"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "-"
    return ("%.1f" % f).rstrip("0").rstrip(".") if f != int(f) else "%d" % f


def build(summary: dict, pois: dict, weather: dict, range_label: str = "") -> dict:
    """组装结构化指南（不含 AI 叙述）。"""
    items = (pois or {}).get("items") or []
    waypoints = summary.get("waypoints") or []
    tracks = summary.get("tracks") or [{}]
    brief = {
        "title": tracks[0].get("name") or "路线",
        "range": range_label,
        "overview": build_overview(summary, items, weather),
        "key_points": key_points(items),
        "weather": weather,
        "risks": build_risks(summary, items, weather),
        "mistakes": build_mistakes(summary, items, waypoints),
        "ai_narrative": "",
        "ai_error": "",
    }
    return brief


AI_SYSTEM = (
    "你是资深高海拔徒步向导，服务对象是个人徒步者。"
    "只依据给定事实分析，不编造地名、不虚构路况。"
    "语言简洁、具体、可执行，不要空话。"
)

AI_TEMPLATE = (
    "根据下面的真实数据，写一段 300 字以内的行前风险分析。\n\n"
    "路线：{overview}\n"
    "关键节点：{key_points}\n"
    "天气：{weather}\n"
    "已识别风险：{risks}\n"
    "易错点：{mistakes}\n"
    "用户补充：{context}\n\n"
    "硬性要求（务必遵守）：\n"
    "1. 只针对这条路线说话。禁止出现「导入手机」「保持离线可用」「提前下载轨迹」"
    "这类放之四海皆准的套话。\n"
    "2. 装备只在与天气/地形直接相关时才提。禁止罗列徒步鞋、登山杖、头灯、"
    "冲锋衣这种默认人人都带的东西。\n"
    "3. 只有在下列情况才提装备：降雪/结冰 -> 冰爪或防滑；降雨明显 -> 防水层与备换衣物；"
    "大风或高海拔低温 -> 防风保暖与失温防护；需要手脚并用的攀爬/碎石坡 -> 手套。\n"
    "4. 提到的每一个位置都必须能对应上面的关键节点，不要编造地名。\n"
    "5. 指出最需要注意的 2-3 件事，说明原因与可执行的判断依据"
    "（时间窗、撤返条件、绕行方式）。\n\n"
    "只输出分析正文，不要标题，不要复述表格内容。"
)


def make_ai_prompt(brief: dict, context: str = "") -> str:
    kps = brief.get("key_points") or []
    kp_text = "；".join("%.1fkm %s(%s)" % (p.get("km") or 0, p.get("name") or "",
                                          p.get("type_label") or "") for p in kps[:12])
    days = (brief.get("weather") or {}).get("days") or []
    w_text = "；".join("%s %s %s~%s°C 降水%smm" % (
        d.get("date"), d.get("weather"), _q(d.get("t_min")),
        _q(d.get("t_max")), _q(d.get("rain_mm"))) for d in days[:7])
    return AI_TEMPLATE.format(
        overview=brief.get("overview") or "",
        key_points=kp_text or "无",
        weather=w_text or "无预报",
        risks="；".join(brief.get("risks") or []) or "无",
        mistakes="；".join(brief.get("mistakes") or []) or "无",
        context=(context or "").strip()[:600] or "无",
    )
