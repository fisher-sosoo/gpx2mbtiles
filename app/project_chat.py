"""对话式修正：用自然语言增删改地名点。

设计边界（重要）：

* **模型不能直接改数据**。它只能输出受限的操作集合（删点/按类型保留/改名），
  由服务端校验后执行；不认识的 op、越界的名字一律丢弃。
* **多轮上下文**：历史落 chat.json，每轮把「当前状态 + 历史 + 新指令」交给模型，
  所以「再删掉刚才那两个」这种承接指代能work。
* **可撤销**：pois.json 里保留 original，随时恢复。
"""
from __future__ import annotations

import json
import logging
import re

from . import ai_naming

logger = logging.getLogger(__name__)

MAX_HISTORY = 12          # 带给模型的历史轮数上限
MAX_MESSAGE_CHARS = 400

# 只允许这几种操作，别的都丢弃
ALLOWED_OPS = ("drop_poi", "keep_kinds", "rename_poi", "reset")

SYSTEM = (
    "你是 GPX 路线助手的「地名点编辑」模块。用户会用自然语言要求增删改地名点。"
    "你只能输出受限操作，不能编造地名，不能修改轨迹坐标。"
)

TEMPLATE = """当前项目：{name}
路线：{overview}

当前地名点（序号|名称|类型|距轨迹|海拔）：
{pois}

可用类型：{kinds}

{history}
用户指令：{message}

请判断要执行的操作，只输出 JSON：
{{"reply": "一句话说明你做了什么", "ops": [...]}}

ops 只能是以下之一：
- {{"op": "drop_poi", "name": "要删除的地名"}}
- {{"op": "keep_kinds", "kinds": ["垭口", "营地"]}}
- {{"op": "rename_poi", "name": "原名", "new_name": "新名"}}
- {{"op": "reset"}}

规则：名称必须来自上面的列表；不确定就不输出该 op；没有可做的 ops 时输出空数组。
用户说「恢复/全部找回/还原」时用 reset。"""


class ChatError(RuntimeError):
    """对话失败。"""


def _poi_lines(items: list, limit: int = 60) -> str:
    rows = []
    for i, it in enumerate(items[:limit], start=1):
        ele = it.get("ele")
        rows.append("%d|%s|%s|%sm|%s" % (
            i, it.get("name") or "", it.get("type_label") or it.get("kind") or "",
            it.get("distance_m", "?"), ("%dm" % int(ele)) if ele else "-"))
    return "\n".join(rows) or "（无）"


def _history_text(history: list) -> str:
    if not history:
        return ""
    lines = []
    for m in history[-MAX_HISTORY:]:
        role = "用户" if m.get("role") == "user" else "助手"
        lines.append("%s：%s" % (role, (m.get("content") or "")[:200]))
    return "对话历史：\n" + "\n".join(lines) + "\n"


def _overview(summary: dict) -> str:
    if not summary:
        return "-"
    dist = (summary.get("distance_m") or 0) / 1000.0
    return "%.2f km，%d 个航点" % (dist, summary.get("waypoint_count") or 0)


def build_prompt(summary: dict, items: list, history: list, message: str,
                 original: list | None = None) -> str:
    tracks = (summary or {}).get("tracks") or [{}]
    kinds = sorted({it.get("type_label") for it in items if it.get("type_label")})
    # 当前为空但仍有快照时必须告诉模型，否则它会认为「没什么可恢复」而不发 reset
    note = ""
    if original is not None and len(original) != len(items):
        names = "、".join(it.get("name") or "" for it in original[:12])
        note = ("\n注意：筛选前共有 %d 个地名点（%s），可用 reset 恢复。\n"
                % (len(original), names))
    return TEMPLATE.format(
        name=tracks[0].get("name") or "未命名",
        overview=_overview(summary),
        pois=_poi_lines(items),
        kinds="、".join(kinds) or "无",
        history=_history_text(history) + note,
        message=(message or "")[:MAX_MESSAGE_CHARS],
    )


def _extract_json(text: str):
    if not text:
        return None
    fence = chr(96) * 3
    fenced = re.search(fence + "(?:json)?\\s*(.+?)" + fence, text, re.S)
    body = fenced.group(1) if fenced else text
    start, end = body.find("{"), body.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(body[start:end + 1])
    except json.JSONDecodeError:
        return None


def _clone(items):
    """深拷贝：操作绝不能改到调用方的数据（否则 reset 就恢复不回去了）。"""
    return json.loads(json.dumps(items or [], ensure_ascii=False))


def apply_ops(items: list, ops: list, original: list | None = None) -> tuple:
    """执行受限操作，返回 (新列表, 已执行描述, 被拒描述)。

    任何不认识或越界的操作都丢弃并记录，绝不让模型随意改数据。
    original 是筛选前的快照，reset 用它恢复；不传则退化为当前列表。
    """
    base = _clone(original if original is not None else items)
    current = _clone(items)
    applied = []
    rejected = []
    names = {it.get("name") for it in current}
    labels = {it.get("type_label") for it in current}

    for raw in ops or []:
        if not isinstance(raw, dict):
            rejected.append("非对象操作")
            continue
        op = raw.get("op")
        if op not in ALLOWED_OPS:
            rejected.append("不支持的操作 %s" % op)
            continue

        if op == "reset":
            current = _clone(base)
            applied.append("已恢复全部地名点")
            names = {it.get("name") for it in current}
            continue

        if op == "drop_poi":
            name = (raw.get("name") or "").strip()
            if name not in names:
                rejected.append("没有叫「%s」的地名点" % name)
                continue
            before = len(current)
            current = [it for it in current if it.get("name") != name]
            applied.append("删除「%s」（%d 个）" % (name, before - len(current)))
            names = {it.get("name") for it in current}
            continue

        if op == "keep_kinds":
            kinds = [str(k).strip() for k in (raw.get("kinds") or []) if str(k).strip()]
            valid = [k for k in kinds if k in labels]
            if not valid:
                rejected.append("没有可用的类型：%s" % "、".join(kinds))
                continue
            before = len(current)
            current = [it for it in current if it.get("type_label") in valid]
            applied.append("只保留 %s（去掉 %d 个）"
                           % ("、".join(valid), before - len(current)))
            names = {it.get("name") for it in current}
            labels = {it.get("type_label") for it in current}
            continue

        if op == "rename_poi":
            name = (raw.get("name") or "").strip()
            new_name = (raw.get("new_name") or "").strip()
            if name not in names:
                rejected.append("没有叫「%s」的地名点" % name)
                continue
            if not new_name or len(new_name) > 24:
                rejected.append("新名字不合法")
                continue
            for it in current:
                if it.get("name") == name:
                    it["name"] = new_name
                    it["renamed_from"] = name
            applied.append("把「%s」改名为「%s」" % (name, new_name))
            names = {it.get("name") for it in current}

    return current, applied, rejected


def run_turn(summary: dict, items: list, history: list, message: str,
             settings, original: list | None = None) -> dict:
    """执行一轮对话，返回 {reply, ops, items, applied, rejected}。"""
    if not ai_naming.is_configured(settings):
        raise ChatError("未配置 AI_API_KEY，无法使用对话修正")
    prompt = build_prompt(summary, items, history, message, original)
    try:
        text = ai_naming.chat(prompt, settings, SYSTEM)
    except ai_naming.AiNamingError as exc:
        raise ChatError(str(exc)) from exc

    parsed = _extract_json(text)
    if parsed is None:
        return {"reply": text.strip()[:400] or "（模型没有返回可执行的操作）",
                "ops": [], "items": items, "applied": [], "rejected": []}

    ops = parsed.get("ops") or []
    reply = (parsed.get("reply") or "").strip()[:400]
    new_items, applied, rejected = apply_ops(items, ops, original)
    if not reply:
        reply = "；".join(applied) if applied else "没有需要改动的点"
    return {"reply": reply, "ops": ops, "items": new_items,
            "applied": applied, "rejected": rejected}
