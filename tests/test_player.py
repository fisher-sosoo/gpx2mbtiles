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
        "/api/tile/windy/",                         # Windy 经服务端代理（CORS 限制）
        "opentopomap.org",                          # OTM 底图
        "showLabel",                                # 轨迹名称标签开关
        "renderMarkLabels",                         # 标记名称常驻显示
        "data-act=\"mlabel\"",                   # 单个标记标签开关
        "btnAllMarkLbl", "btnMarkLblOff",           # 标记标签批量开关
        "data-act=\"opacity\"",                  # 单条轨迹不透明度
        "id=\"trOp\"",                           # 全局轨迹不透明度
        "data-act=\"visible\"",                  # 显示/隐藏
        "data-act=\"color\"",                    # 颜色选择
        "sampleByDistance",                         # 里程桩
        "buildEndpoints", "buildArrows",            # 起终点 / 方向箭头
        "updateWhenIdle", "keepBuffer",             # 瓦片延迟加载与缓冲收紧
        "localStorage",                             # 本地持久化
        "exportGpx", "exportJson",                  # 导出
        "drawLegendCanvas", "drawPolyline",         # PNG 截图（直接绘制到 canvas）
        "projectPoint",                             # 经纬度 -> 像素投影
        "errorTileUrl", "TRANSPARENT_TILE",         # 失败瓦片透明占位（重试已移到服务端）
    ):
        assert snippet in html, f"回放页缺少功能要素: {snippet}"


def test_default_basemap_is_otm():
    """默认底图必须是 OpenTopoMap。

    Windy 的响应头同时带 access-control-allow-credentials:true 和
    access-control-allow-origin:*（CORS 规范禁止的组合），Chrome 会把它
    判为 ERR_BLOCKED_BY_ORB，导致整片底图空白。实测：
        OTM  -> 32 个请求全 200，16/16 瓦片加载
        Windy-> ERR_BLOCKED_BY_ORB
    因此默认用 OTM，Windy 仅作为可选项保留并附警告。
    """
    html = _read(PLAYER)
    assert "base: 'otm'" in html, "默认底图应为 otm"
    assert 'value="otm" selected' in html, "底图下拉默认应选中 otm"
    # Windy 仍可作为可选项，但要有警告说明
    assert 'value="windy"' in html, "Windy 应保留为可选项"
    assert "ERR_BLOCKED_BY_ORB" in html, "Windy 选项旁应有 CORS 问题说明"


def test_tile_layer_does_not_force_cors():
    """底图不能设 crossOrigin。

    设了会让浏览器用 CORS 模式请求，Windy 在该模式下会被判失败
    （图片返回 200 但 onload 不触发），地图整片空白。
    PNG 导出改用独立 Image 拉取，不依赖页面上的瓦片元素。
    """
    html = _read(PLAYER)
    assert "opts.crossOrigin" not in html, "底图不应开启 crossOrigin"


def test_player_only_uses_tile_proxy_api():
    """回放页的解析/渲染/导出仍在浏览器完成，唯一的服务端调用是瓦片代理。

    Windy 响应头违反 CORS 规范（credentials:true 与 origin:* 并存），浏览器直连会
    ERR_BLOCKED_BY_ORB，因此必须走 /api/tile/windy/。除此之外不得调用任何任务类接口，
    也不得用本服务的通用 /tiles/ 路径。
    """
    html = _read(PLAYER)
    js = _extract_inline_js(html)
    for banned in ("/api/submit", "/api/estimate", "/api/status", "/api/tasks"):
        assert banned not in js, f"回放页不应调用生成类接口: {banned}"
    assert "/tiles/" not in js, "回放页不应使用通用 /tiles/ 路径"
    # 允许的 /api/ 调用只有瓦片代理与缓存统计
    import re as _re
    used = set(_re.findall(r"/api/[a-z]+", js))
    assert used <= {"/api/tile", "/api/tilecache"}, f"回放页出现意外的接口调用: {used}"


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


@pytest.mark.parametrize("path", ["web/portal.html", "web/index.html", "web/player.html"])
def test_html_is_valid_utf8_with_chinese(path):
    """所有页面的中文必须是合法 UTF-8。

    回归防护：曾因上传路径编码问题，中文全部被替换成 '?'，页面显示乱码，
    但 HTTP 仍返回 200 —— 只检查状态码无法发现这类损坏。
    """
    raw = (ROOT / path).read_bytes()
    text = raw.decode("utf-8")  # 非法 UTF-8 会直接抛异常
    assert text.count("\ufffd") == 0, f"{path} 含 U+FFFD 替换字符，编码已损坏"
    non_ascii = sum(1 for b in raw if b > 127)
    assert non_ascii > 0, f"{path} 不含任何非 ASCII 字节，中文疑似被替换为 '?'"
    assert any(k in text for k in ("服务门户", "离线地图", "轨迹")), (
        f"{path} 未找到预期中文内容，疑似编码损坏")


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
    # Leaflet CSS 与 JS 版本必须一致，否则会出现渲染错位
    assert html.count("leaflet@1.9.4") == 2
    # PNG 导出改为直接绘制到 canvas，不再引入 html2canvas
    assert "html2canvas.min.js" not in html, "不应再依赖 html2canvas"


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

def test_windy_tile_throttling_present():
    """瓦片请求必须延迟加载并收紧缓冲。

    历史教训：Leaflet 默认在拖动/缩放动画期间持续请求瓦片、并预取视口外 2 圈，
    很容易被瓦片源判定为爬取而返回 403。

    注意：前端不再自己做队列限速 —— 按 tile-proxy-cache 规范，限速只作用于
    「服务端 → 上游」，浏览器请求的是本站，命中磁盘缓存时根本不回源。
    """
    js = _extract_inline_js(_read(PLAYER))
    assert "updateWhenIdle" in js, "应开启瓦片延迟加载"
    assert "keepBuffer" in js, "应显式设置缓冲圈数"
    # 前端不应再自行排队限速（会白白拖慢命中缓存的请求）
    assert "function pump()" not in js, "前端不应恢复队列式限速"

# ---------------------------------------------------------------- 转换页

CONVERT_PAGE = ROOT / "web" / "convert.html"


def test_convert_page_exists_and_has_features():
    assert CONVERT_PAGE.is_file(), "缺少 web/convert.html"
    html = _read(CONVERT_PAGE)
    for snippet in (
        "/api/convert",              # 走服务端转换
        'accept=".kml,.kmz"',        # 只收 KML/KMZ
        "dataTransfer",              # 支持拖拽
        "track_name",                # 自定义轨迹名
        "download",                  # 下载按钮
        "name_sources",              # 命名来源统计
        "累计耗时",                   # 航点表头
        "里程",                       # 航点表头
        "/api/projects",             # 历史项目列表
        "loadHistory",               # 历史加载
        "reconvert",                 # 重转
        "historyTotal",              # 历史计数
        "/pois",                     # 地名补点
        "renderPois",                # 地名列表渲染
        "/export",                   # 含地名导出
        "/guide",                    # 行前指南
        "renderGuide",               # 指南渲染
        "guideStart",                # 日期范围输入
        "/chat",                     # 对话式修正
        "sendChat",                  # 发送对话
        "chatInput",                 # 对话输入框
    ):
        assert snippet in html, f"转换页缺少要素: {snippet}"


@pytest.mark.skipif(shutil.which("node") is None, reason="node 不可用")
def test_convert_page_js_syntax():
    js = _extract_inline_js(_read(CONVERT_PAGE))
    assert js.strip(), "转换页未找到内联脚本"
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as f:
        f.write(js)
        tmp = f.name
    try:
        proc = subprocess.run(["node", "--check", tmp], capture_output=True, text=True)
        assert proc.returncode == 0, f"转换页 JS 语法错误：\n{proc.stderr}"
    finally:
        Path(tmp).unlink(missing_ok=True)


def test_convert_page_does_not_call_task_api():
    """转换页只做同步转换，不该提交生成任务。"""
    js = _extract_inline_js(_read(CONVERT_PAGE))
    assert "/api/submit" not in js
    assert "/api/estimate" not in js


def test_convert_page_has_project_history():
    """历史项目要能回看、重转、删除。"""
    html = _read(CONVERT_PAGE)
    js = _extract_inline_js(html)
    for snippet in ('data-act="open"', 'data-act="reai"',
                    'data-act="dl"', 'data-act="del"'):
        assert snippet in html, f"历史项缺少操作: {snippet}"
    assert "DELETE" in js, "缺少删除调用"
    assert "/reconvert" in js, "缺少重转调用"
    assert "/download" in js, "缺少下载调用"


def test_convert_page_has_conversational_curation():
    """对话修正面板要能接续上下文并展示执行结果。"""
    html = _read(CONVERT_PAGE)
    js = _extract_inline_js(html)
    assert 'id="chatLog"' in html and 'id="chatInput"' in html
    assert "appendChat" in js, "缺少对话渲染"
    assert "applied" in js and "rejected" in js, "应展示已执行/被拒操作"
    assert "/api/projects/" in js and "/chat" in js


def test_convert_page_hands_off_to_player_for_png():
    """出图交给回放页：用 sessionStorage 交接，避免在转换页重造地图。"""
    html = _read(CONVERT_PAGE)
    js = _extract_inline_js(html)
    assert 'id="guideMap"' in html, "缺少「在地图上查看并出图」按钮"
    assert "sessionStorage.setItem" in js, "应通过 sessionStorage 交接"
    assert "gpx2mbtiles_handoff" in js
    assert "/gpx/player.html" in js, "应跳转到回放页"


def test_player_picks_up_handoff_without_calling_api():
    """回放页要能接住交接数据，但仍必须保持纯前端。"""
    html = _read(PLAYER)
    js = _extract_inline_js(html)
    assert "pickUpHandoff" in js, "缺少交接接收逻辑"
    assert "gpx2mbtiles_handoff" in js
    assert "sessionStorage.removeItem" in js, "接到后应清理，避免重复导入"
    # 仍然不允许调用生成类接口
    import re as _re
    used = set(_re.findall(r"/api/[a-z]+", js))
    assert used <= {"/api/tile", "/api/tilecache"}, f"回放页出现意外调用: {used}"


def test_convert_page_has_trip_briefing():
    """行前指南要支持日期区间与 AI 开关。"""
    html = _read(CONVERT_PAGE)
    js = _extract_inline_js(html)
    assert 'id="guideStart"' in html and 'id="guideEnd"' in html, "缺少日期区间输入"
    assert 'id="guideAi"' in html, "缺少 AI 开关"
    assert "start_date" in js and "end_date" in js
    assert "use_ai" in js
    assert "复制文本" in html and "下载 Markdown" in html


def test_convert_page_linked_from_all_pages():
    assert 'href="/gpx/convert.html"' in _read(INDEX)
    assert 'href="/gpx/convert.html"' in _read(PLAYER)
    assert 'href="/gpx/convert.html"' in _read(PORTAL)


def test_index_accepts_kml_upload():
    html = _read(INDEX)
    assert 'accept=".gpx,.xml,.kml,.kmz"' in html
    assert "KML" in html
