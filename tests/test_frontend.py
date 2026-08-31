import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest


def _extract_inline_js(html: str) -> str:
    """提取最后一个 <script>（无 src）块的内容。"""
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
    return blocks[-1]


@pytest.mark.skipif(shutil.which("node") is None, reason="node 不可用")
def test_frontend_js_syntax():
    """前端内联 JS 必须语法正确（防回归：多行字符串曾导致提交按钮失效）。"""
    html = Path(__file__).resolve().parent.parent.joinpath(
        "web/index.html").read_text(encoding="utf-8")
    js = _extract_inline_js(html)
    assert js.strip(), "未找到内联脚本"
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
        f.write(js)
        tmp = f.name
    try:
        proc = subprocess.run(
            ["node", "--check", tmp], capture_output=True, text=True)
        assert proc.returncode == 0, (
            f"前端 JS 语法错误：\n{proc.stderr}")
    finally:
        Path(tmp).unlink(missing_ok=True)


def test_frontend_has_expected_defaults():
    html = Path(__file__).resolve().parent.parent.joinpath(
        "web/index.html").read_text(encoding="utf-8")
    for snippet in (
        'id="buffer" value="2500"',
        'id="minZoom" value="8"',
        'id="maxZoom" value="17"',
        "/api/estimate",
        "allow_oversize",
        "history.pushState",
        'id="historyList"',
        "invalidateSize",  # 隐藏容器显示后重算尺寸，防预览视图错乱
    ):
        assert snippet in html, f"缺少前端要素: {snippet}"
    # 预览初始化顺序：先 display=block 再 L.map（Leaflet 隐藏容器 bug 回归防护）
    js = _extract_inline_js(html)
    assert js.index("style.display = 'block'") < js.index("L.map(")
