"""AI 辅助命名：模型依据海拔剖面与节奏为航点起语义名称。

规则名称（#07 3.07km · 1:08）解决了「没有名字」，但回答不了「走到哪了」。
模型能读出「连续急升 → 山脊 → 登顶 → 下撤」这样的地形叙述，正好补上这一层。

约束（见 design.md D8）：

* 只有显式开启才调用，默认零外部请求。
* 输入是结构化摘要，不是原始点云；30 个航点约 770 tokens。
* 输出只当候选名：序号对不上、空串、超长、纯标点一律丢弃并回退规则命名。
* 任何异常都只记录原因，绝不让转换失败。
"""
from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

# 名称长度上限：太长会挤爆 App 的列表与地图标签
MAX_NAME_CHARS = 12
MIN_NAME_CHARS = 2

_SYSTEM_PROMPT = (
    "你是资深徒步领队，擅长读海拔变化判断路况。"
    "你只根据给定的里程、海拔、升降和时间间隔做判断，不臆造具体地名。"
)

_INSTRUCTION = (
    "请为一条徒步轨迹的每个照片航点起中文名。\n"
    "轨迹概况：{overview}\n"
    "航点按行进顺序，列格式：序号|累计里程km|海拔m|比上一点升降m|距上一点km|距上一点分钟\n"
    "{rows}\n"
    "要求：\n"
    "1. 每个名字 2-6 个汉字，要具体、彼此不同，避免都叫爬升或下坡。\n"
    "2. 大幅上升写陡坡/碎石坡，久留写休整/垭口/观景，接近最高点写登顶，之后写下撤。\n"
    "3. 不要编造具体地名（村名、山名、溪名），只描述地形与动作。\n"
    "4. 名字要让人一看就知道走到哪了。\n"
    "只输出 JSON 数组，形如 [{\"i\": 1, \"name\": \"起步山径\"}]，不要任何其它文字。"
)


class AiNamingError(RuntimeError):
    """AI 命名失败（调用或解析）。"""


def is_configured(settings) -> bool:
    return bool(getattr(settings, "ai_api_key", ""))


def _overview(summary, elevation, distance_m: float) -> str:
    track = (summary.tracks or [{}])[0]
    parts = [track.get("name") or "未命名轨迹"]
    if summary.date:
        parts.append(summary.date)
    if summary.sport:
        parts.append(summary.sport)
    total_km = (distance_m or 0) / 1000.0
    if total_km:
        parts.append("全程 %.2fkm" % total_km)
    if elevation:
        parts.append("最低海拔 %dm，最高点 %dm" % (int(min(elevation)), int(max(elevation))))
        gain = sum(max(0, b - a) for a, b in zip(elevation, elevation[1:]))
        if gain:
            parts.append("累计爬升约 %dm" % int(gain))
    return "，".join(parts)


def build_prompt(waypoints, summary, distance_m: float) -> str:
    """把航点序列压成一张紧凑表格交给模型。"""
    elevation = [w["ele"] for w in waypoints if w.get("ele") is not None]
    rows = []
    prev_km = None
    prev_min = None
    prev_ele = None
    for w in waypoints:
        km = w.get("km") or 0.0
        minutes = int(round((w.get("elapsed_s") or 0) / 60.0))
        ele = w.get("ele")
        d_km = ""
        d_min = ""
        if prev_km is not None:
            d_km = "%.2f" % (km - prev_km)
            d_min = str(minutes - prev_min)
        d_ele = ""
        if ele is not None and prev_ele is not None:
            d_ele = "%+.0f" % (ele - prev_ele)
        ele_txt = str(int(ele)) if ele is not None else "-"
        rows.append("%d|%.2f|%s|%s|%s|%s" % (w["seq"], km, ele_txt, d_ele, d_km, d_min))
        prev_km = km
        prev_min = minutes
        if ele is not None:
            prev_ele = ele
    # 用 replace 而不是 str.format：示例里的 {"i": 1} 会被当成占位符报 KeyError
    return (_INSTRUCTION
            .replace("{overview}", _overview(summary, elevation, distance_m))
            .replace("{rows}", "\n".join(rows)))


def _post(settings, prompt: str) -> dict:
    payload = {
        "model": getattr(settings, "ai_model", "deepseek-chat"),
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": getattr(settings, "ai_max_tokens", 2000),
        "temperature": 0.4,
    }
    url = getattr(settings, "ai_base_url", "https://api.deepseek.com").rstrip("/") + "/chat/completions"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "Authorization": "Bearer " + settings.ai_api_key,
        "Content-Type": "application/json",
    })
    timeout = getattr(settings, "ai_timeout_seconds", 30.0)
    # 服务器在墙内，api.deepseek.com 必须走 mihomo 代理（与瓦片源共用 TILE_PROXY）
    proxy = getattr(settings, "ai_proxy", "") or getattr(settings, "tile_proxy", "")
    if proxy:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"https": proxy, "http": proxy}))
    else:
        opener = urllib.request.build_opener()
    try:
        with opener.open(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise AiNamingError("模型返回 %s：%s" % (exc.code, detail)) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise AiNamingError("模型请求失败：%s" % exc) from exc
    except json.JSONDecodeError as exc:
        raise AiNamingError("模型响应不是合法 JSON：%s" % exc) from exc


def _extract_json_array(text: str):
    """从可能带 ```json 包裹或前后缀说明的回复里抠出 JSON 数组。"""
    if not text:
        return None
    fenced = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    body = fenced.group(1) if fenced else text
    start = body.find("[")
    end = body.rfind("]")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(body[start:end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, list) else None


_BAD_NAME_RE = re.compile(r"^[\W_]+$")


def clean_name(raw) -> str:
    """只留下像人话的短名称；不合格返回空串。"""
    if not isinstance(raw, str):
        return ""
    name = raw.strip().strip("\"\'`“”「」").strip()
    name = re.sub(r"\s+", "", name)
    if len(name) < MIN_NAME_CHARS or len(name) > MAX_NAME_CHARS:
        return ""
    if _BAD_NAME_RE.match(name):
        return ""
    return name


def parse_names(text: str, seqs) -> dict:
    """把模型回复解析成 {seq: name}，只保留序号对得上且名称合格的条目。"""
    items = _extract_json_array(text)
    if not items:
        return {}
    valid = set(seqs)
    out = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            seq = int(item.get("i"))
        except (TypeError, ValueError):
            continue
        if seq not in valid:
            continue
        name = clean_name(item.get("name"))
        if name:
            out[seq] = name
    return out


def suggest_names(waypoints, summary, distance_m: float, settings) -> dict:
    """返回 {seq: name}。失败抛 AiNamingError，由调用方决定如何回退。

    waypoints 每项需要：seq（从 1 开始）、km、elapsed_s、ele。
    """
    if not waypoints:
        return {}
    if not is_configured(settings):
        raise AiNamingError("未配置 AI_API_KEY")
    prompt = build_prompt(waypoints, summary, distance_m)
    started = time.monotonic()
    body = _post(settings, prompt)
    elapsed = time.monotonic() - started
    choices = body.get("choices") or [{}]
    content = (choices[0].get("message") or {}).get("content", "")
    names = parse_names(content, [w["seq"] for w in waypoints])
    logger.info("ai naming: %d/%d names in %.1fs", len(names), len(waypoints), elapsed)
    return names
