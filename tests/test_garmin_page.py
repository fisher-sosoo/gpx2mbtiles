"""Garmin 活动页的静态断言，以及共享渲染内核的「防漂移」检查。

不启动浏览器：只做 HTML 断言、node 语法检查、以及把 report.html 的纯函数段
与 report-core.js 逐行比对。旧页必须保持零改动，所以这里也守住它的独立性。
"""
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "web" / "garmin.html"
CORE = ROOT / "web" / "report-core.js"
REPORT = ROOT / "web" / "report.html"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _inline_js(html: str) -> str:
    """提取最后一个无 src 的 <script> 块。"""
    blocks = []
    start = 0
    while True:
        i = html.find("<script>", start)
        if i == -1:
            break
        j = html.find("</script>", i)
        if j == -1:
            break
        blocks.append(html[i + len("<script>"):j])
        start = j + len("</script>")
    assert blocks, "页面里没有内联脚本"
    return blocks[-1]


def _pure_block(text: str) -> list:
    match = re.search(r"/\* PURE_START \*/(.*?)/\* PURE_END \*/", text, re.S)
    assert match, "缺少 PURE_START / PURE_END 锚点"
    return [line.strip() for line in match.group(1).splitlines() if line.strip()]


def test_page_and_core_exist():
    assert PAGE.is_file(), "缺少 web/garmin.html"
    assert CORE.is_file(), "缺少 web/report-core.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="node 不可用")
def test_inline_js_syntax():
    js = _inline_js(_read(PAGE))
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as fh:
        fh.write(js)
        path = fh.name
    result = subprocess.run(["node", "--check", path], capture_output=True, text=True)
    assert result.returncode == 0, f"页面内联 JS 语法错误：{result.stderr}"


@pytest.mark.skipif(shutil.which("node") is None, reason="node 不可用")
def test_core_syntax():
    result = subprocess.run(["node", "--check", str(CORE)],
                            capture_output=True, text=True)
    assert result.returncode == 0, f"report-core.js 语法错误：{result.stderr}"


def test_shared_core_has_not_drifted_from_old_page():
    """共享内核必须与旧页的纯函数段逐行一致，否则两页会悄悄算出不同结果。"""
    old = _pure_block(_read(REPORT))
    new = _pure_block(_read(CORE))
    assert old == new, "report-core.js 与 report.html 的纯函数段已分叉，请同步后再提交"


def test_old_page_stays_independent():
    """旧页必须保持原样：不引用共享内核，纯函数段仍在自己的文件里。"""
    html = _read(REPORT)
    assert "report-core" not in html, "report.html 不应引用共享内核（旧页要保持零改动）"
    assert "/* PURE_START */" in html and "/* PURE_END */" in html


def test_only_garmin_and_tile_endpoints_are_called():
    js = _inline_js(_read(PAGE))
    endpoints = re.findall(r"['\"\`](/api/[^'\"\`\s?]*)", js)
    assert endpoints, "页面没有调用任何接口？"
    for url in endpoints:
        assert url.startswith("/api/garmin/") or url.startswith("/api/tile/"), \
            f"Garmin 页不应调用 {url}"


def test_no_generation_endpoints():
    js = _inline_js(_read(PAGE))
    for forbidden in ("/api/submit", "/api/convert", "/api/projects", "/api/tasks"):
        assert forbidden not in js, f"Garmin 页不应调用 {forbidden}"


def test_key_elements_present():
    html = _read(PAGE)
    for element_id in ("daysSel", "list", "btnReload", "btnRender",
                       "btnDownload", "status", "authState", "preview"):
        assert 'id="' + element_id + '"' in html, f"缺少 #{element_id}"


def test_page_loads_shared_core():
    html = _read(PAGE)
    assert 'src="/gpx/report-core.js"' in html, "页面应引用共享内核"


def test_physiology_columns_and_wording():
    js = _inline_js(_read(PAGE))
    for word in ("心率", "步频", "温度", "设备"):
        assert word in js, f"生理表缺少「{word}」相关列或说明"
    assert "设备温度" in _read(PAGE), "温度必须写明是设备温度，不能表述成气温"
    assert "enrichSplits" in js, "生理聚合应在页面内实现（不进共享内核）"

def _page_pure_block() -> str:
    match = re.search(r"/\* PURE_START \*/(.*?)/\* PURE_END \*/",
                      _read(PAGE), re.S)
    assert match, "页面缺少 PURE_START/PURE_END 锚点"
    return match.group(1)


@pytest.mark.skipif(shutil.which("node") is None, reason="node 不可用")
def test_enrich_splits_excludes_missing_values():
    """0 值/缺测不参与均值；最高心率与温度区间要正确。"""
    driver = _page_pure_block() + """
var rows = [{ dist: 1 }];
var pts = [
  { hr: 120, cad: 80, temp: 10 },
  { hr: null, cad: 0, temp: 12 },
  { hr: 140, cad: 90, temp: 8 }
];
enrichSplits(pts, [0, 500, 1000], rows);
var empty = [{ dist: 1 }];
enrichSplits([{ hr: null, cad: null, temp: null }], [0], empty);
console.log(JSON.stringify({ full: rows[0], empty: empty[0] }));
"""
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(driver)
        path = fh.name
    try:
        proc = subprocess.run(["node", path], capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr
        import json
        out = json.loads(proc.stdout.strip().splitlines()[-1])
    finally:
        Path(path).unlink(missing_ok=True)

    full = out["full"]
    assert full["hrAvg"] == pytest.approx(130.0)
    assert full["hrMax"] == 140
    assert full["cadAvg"] == pytest.approx(85.0)
    assert full["tempAvg"] == pytest.approx(10.0)
    assert full["tempMin"] == 8 and full["tempMax"] == 12

    empty = out["empty"]
    assert empty["hrAvg"] is None and empty["hrMax"] is None
    assert empty["cadAvg"] is None and empty["tempAvg"] is None
