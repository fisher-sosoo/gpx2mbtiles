"""回放页（web/player.html）的前端回归测试。

这些测试不启动浏览器，只做静态检查 + 用 Node 打桩跑纯函数，
目的是防止「改了 HTML 却把内联 JS 改出语法错误」这类问题重演
（生成器页面历史上就踩过一次多行字符串导致提交按钮失效的坑）。
"""
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PLAYER = ROOT / "web" / "player.html"
INDEX = ROOT / "web" / "index.html"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _extract_inline_js(html: str) -> str:
    """提取最后一个无 src 的 <script> 块（与生成器页面同一套规则）。"""
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


def test_player_exists():
    assert PLAYER.is_file(), "缺少 web/player.html"


@pytest.mark.skipif(shutil.which("node") is None, reason="node 不可用")
def test_player_js_syntax():
    """回放页内联 JS 必须语法正确。"""
    js = _extract_inline_js(_read(PLAYER))
    assert js.strip(), "未找到内联脚本"
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as f:
        f.write(js)
        tmp = f.name
    try:
        proc = subprocess.run(["node", "--check", tmp],
                              capture_output=True, text=True)
        assert proc.returncode == 0, f"回放页 JS 语法错误：\n{proc.stderr}"
    finally:
        Path(tmp).unlink(missing_ok=True)


def test_player_has_core_features():
    """关键功能不能被误删。"""
    html = _read(PLAYER)
    for snippet in (
        "parseGpx", "parseKml", "parseKmz",        # 三种格式
        "DecompressionStream",                      # KMZ 解压
        "gx:Track", "gx:coord",                     # Google 扩展轨迹
        "kmlColorToHex",                            # KML aabbggrr 颜色
        "tiles.windy.com",                          # Windy 底图
        "opentopomap.org",                          # OTM 底图
        "showLabel",                                # 名称标签开关
        "data-act=\"visible\"",                  # 显示/隐藏
        "data-act=\"color\"",                    # 颜色选择
        "sampleByDistance",                         # 里程桩
        "buildEndpoints", "buildArrows",            # 起终点 / 方向箭头
        "localStorage",                             # 本地持久化
        "exportGpx", "exportJson",                  # 导出
        "html2canvas",                              # PNG 截图
    ):
        assert snippet in html, f"回放页缺少功能要素: {snippet}"


def test_player_does_not_touch_server_api():
    """回放页必须是纯前端：不得向本服务端请求瓦片或调用 /api/。"""
    html = _read(PLAYER)
    js = _extract_inline_js(html)
    assert "/api/" not in js, "回放页不应调用服务端 /api/ 接口"
    # 瓦片只能直连外部源，不能走自己的域名
    assert "/tiles/" not in js, "回放页不应通过本服务端代理瓦片"


def test_index_links_to_player():
    """生成器页 → 回放页的入口（生产环境经 Caddy 的 /gpx 前缀）。"""
    html = _read(INDEX)
    assert '/gpx/player.html' in html, "生成器页面缺少进入回放页的入口"


def test_player_links_back_to_generator():
    html = _read(PLAYER)
    assert 'href="/gpx/"' in html, "回放页应能返回生成器页（/gpx/）"


def test_frontend_uses_gpx_prefix_consistently():
    """页内跳转必须带 /gpx 前缀：生产环境根路径被门户主页占用。

    例外：/api/* 是接口调用（Caddy 单独反代），CDN 是外部绝对地址。
    """
    for path in (INDEX, PLAYER):
        html = _read(path)
        refs = re.findall(r'href="(/[^"]*)"', html)
        for ref in refs:
            assert ref.startswith(("/gpx/", "/api/")), (
                f"{path.name} 存在未走 /gpx 前缀的页内跳转: {ref}")


# ---------------------------------------------------------------- 门户

PORTAL = ROOT / "web" / "portal.html"
CADDY = ROOT / "deploy" / "Caddyfile.portal"


def test_portal_exists_and_links_services():
    """门户主页必须存在并能进入两个服务。"""
    assert PORTAL.is_file(), "缺少门户主页 web/portal.html"
    html = _read(PORTAL)
    assert 'href="/gpx/"' in html, "门户缺少 GPX 工具入口"
    assert ":3000" in html, "门户缺少 Stronghold 游戏入口"


def test_caddyfile_routes_are_correct():
    """Caddy 配置必须把门户放根路径、gpx 工具放 /gpx。"""
    assert CADDY.is_file(), "缺少 deploy/Caddyfile.portal"
    cfg = _read(CADDY)
    assert "handle /gpx/*" in cfg, "缺少 /gpx 路由"
    assert "strip_prefix /gpx" in cfg, "/gpx 路由必须先剥离前缀再反代"
    assert "handle /api/*" in cfg, "缺少 /api 路由（前端 fetch 走根路径）"
    assert "127.0.0.1:8000" in cfg, "反代目标应为容器端口 8000"
    assert "/srv/portal" in cfg, "门户静态目录应为 /srv/portal"
    # 性能相关
    assert "encode zstd gzip" in cfg, "缺少压缩配置"


def test_main_mounts_both_prefixes():
    """FastAPI 必须同时提供 / 与 /gpx，兼顾直连与反代。"""
    src = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert 'app.mount("/gpx"' in src, "缺少 /gpx 静态挂载"
    assert 'app.mount("/"' in src, "缺少 / 静态挂载"


def test_player_libraries_from_official_cdn():
    """依赖库必须走官方 CDN，不用来路不明的第三方镜像。"""
    html = _read(PLAYER)
    assert "unpkg.com/leaflet@1.9.4" in html
    assert "cdn.jsdelivr.net/npm/html2canvas" in html
    # Leaflet CSS 与 JS 版本必须一致，否则会出现渲染错位
    assert html.count("leaflet@1.9.4") == 2


@pytest.mark.skipif(shutil.which("node") is None, reason="node 不可用")
def test_kml_color_conversion():
    """KML 的 aabbggrr 颜色必须转成 CSS 的 #rrggbb。"""
    js = _extract_inline_js(_read(PLAYER))
    m = re.search(r"function kmlColorToHex\(c\) \{[\s\S]*?\n  \}", js)
    assert m, "找不到 kmlColorToHex 实现"
    script = m.group(0) + "\nconsole.log(JSON.stringify([" + \
        "kmlColorToHex('ff0000ff'), kmlColorToHex('ffff0000')," + \
        "kmlColorToHex('7f00ff00'), kmlColorToHex('bad')]));"
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as f:
        f.write(script)
        tmp = f.name
    try:
        proc = subprocess.run(["node", tmp], capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr
        got = json.loads(proc.stdout.strip())
        assert got == ["#ff0000", "#0000ff", "#00ff00", None], got
    finally:
        Path(tmp).unlink(missing_ok=True)
