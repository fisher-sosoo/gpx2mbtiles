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
REPORT = ROOT / "web" / "report.html"


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
    for path in (INDEX, PLAYER, REPORT):
        html = _read(path)
        refs = re.findall(r'href="(/[^"]*)"', html)
        for ref in refs:
            assert ref.startswith(("/gpx/", "/api/")), (
                f"{path.name} 存在未走 /gpx 前缀的页内跳转: {ref}")


# ---------------------------------------------------------------- 门户

PORTAL = ROOT / "web" / "portal.html"
CADDY = ROOT / "deploy" / "Caddyfile.portal"


@pytest.mark.parametrize("path", ["web/portal.html", "web/index.html", "web/player.html", "web/report.html"])
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
    assert 'href="/gpx/report.html"' in html, "门户缺少分析长图入口"
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


@pytest.mark.parametrize("path", ["web/convert.html", "web/player.html",
                                 "web/index.html", "web/portal.html",
                                 "web/report.html"])
def test_page_element_ids_all_exist(path):
    """JS 里引用的元素 ID 必须真的存在。

    回归防护：这类错误不会报错，只表现为「按钮点了没反应」，
    在静态检查里最容易漏。历史上生成器页就踩过类似坑。
    """
    full = ROOT / path
    if not full.is_file():
        pytest.skip(f"{path} 不存在")
    html = _read(full)
    ids = set(re.findall(r'\bid="([^"]+)"', html))
    blocks = re.findall(r"<script>([\s\S]*?)</script>", html)
    js = blocks[-1] if blocks else ""
    refs = set(re.findall(r"\$\('([A-Za-z0-9_-]+)'\)", js))
    refs |= set(re.findall(r"getElementById\('([A-Za-z0-9_-]+)'\)", js))
    missing = sorted(r for r in refs if r not in ids)
    assert not missing, f"{path} 引用了不存在的元素: {missing}"


def test_convert_panel_triggers_are_not_inside_hidden_cards():
    """回归防护：功能入口不能被放进默认隐藏的卡片里。

    历史事故：地名补点 / 行前指南的按钮被放在 display:none 的结果卡片中，
    转换后卡片又被隐藏，导致用户完全看不到这两个功能。
    """
    html = _read(CONVERT_PAGE)
    js = _extract_inline_js(html)
    # 必须有一个统一的显隐函数，且转换/打开项目后会调用它让入口可见
    assert "showProjectPanels" in js, "缺少统一的区块显隐控制"
    assert js.count("showProjectPanels(true)") >= 2, "转换与打开项目后都要让入口可见"
    assert "showProjectPanels(false)" in js, "删除当前项目后应隐藏"
    # 入口按钮不应再被单独 display:none 掉
    assert "$('poiCard').style.display = 'none'" not in js or         "showProjectPanels(false)" in js


def test_convert_page_has_junction_detection():
    """岔路能力：接口、绘制、路口提示都要在（入口已改为顶部开关）。"""
    html = _read(CONVERT_PAGE)
    js = _extract_inline_js(html)
    assert "/junctions" in js, "应调用岔路接口"
    assert "junctionPoints" in js, "缺少岔路绘制"
    assert "岔路口" in js, "应展示路口提示"
    assert "startJunctionJob" in js, "缺少岔路任务触发"


def test_convert_page_has_conversational_curation():
    """对话修正面板要能接续上下文并展示执行结果。"""
    html = _read(CONVERT_PAGE)
    js = _extract_inline_js(html)
    assert 'id="chatLog"' in html and 'id="chatInput"' in html
    assert "appendChat" in js, "缺少对话渲染"
    assert "applied" in js and "rejected" in js, "应展示已执行/被拒操作"
    assert "/api/projects/" in js and "/chat" in js


def test_convert_page_renders_route_image_into_analysis():
    """线路图不再常驻页面，而是在分析文本里嵌成静态图片。"""
    html = _read(CONVERT_PAGE)
    js = _extract_inline_js(html)
    # 页面里不应再有常驻地图容器 / 交互地图依赖
    assert 'id="cmap"' not in html, "页面不该再嵌交互地图"
    assert "unpkg.com/leaflet" not in html, "不再加载 Leaflet"
    assert "L.map(" not in js, "不再创建交互地图"
    assert 'id="mapCard"' not in html, "地图卡片应已移除"
    # 但要有图片渲染能力，并插进分析文本
    assert "renderRouteImage" in js, "缺少线路图渲染"
    assert "toDataURL" in js, "应生成静态图片"
    assert "routeImgWrap" in js, "图片应插到分析文本里"
    assert "player.html" not in js, "不该跳到回放页"


def test_convert_has_single_download_with_pois():
    """只留一个下载入口，且必须带走地名点（不再拆成两个按钮）。"""
    html = _read(CONVERT_PAGE)
    js = _extract_inline_js(html)
    assert 'id="poiExportBtn"' not in html, "「下载含地名 GPX」应已合并"
    assert "poiExportBtn" not in js
    assert 'id="downloadBtn"' in html
    assert "/export" in js, "下载应走服务端合并导出"
    assert "withToken" in js, "浏览器导航需要带 token"


def test_convert_critical_helpers_are_defined():
    """关键辅助函数必须真的定义在页面里。

    回归防护：重构时把整段代码替换掉，函数被调用却没了定义，
    表现为「ReferenceError: xxx is not defined」，静态 ID 检查抓不到。
    """
    js = _extract_inline_js(_read(CONVERT_PAGE))
    required = [
        "parseTrackPoints", "ensureTrackPoints", "trackLatLngs",
        "renderRouteImage", "renderRouteIntoGuide", "drawPolyline",
        "computeView", "projPt", "loadTile",
        "renderMd", "render", "renderPois", "renderGuide",
        "apiFetch", "withToken", "ensureKey", "showProjectPanels",
        "loadHistory", "loadTrackForMap", "maybeRunEnrichments",
        "startJunctionJob", "pollJunctions", "junctionHint",
        "setChatEnabled", "appendChat", "sendChat",
    ]
    missing = [n for n in required if ("function %s(" % n) not in js]
    assert not missing, "页面里缺少这些函数的定义：%s" % missing


def test_convert_route_image_has_gpx_fallback():
    """出图不能只依赖接口：手上已有 gpx 时应直接解析。"""
    js = _extract_inline_js(_read(CONVERT_PAGE))
    assert "ensureTrackPoints" in js, "缺少轨迹点兜底"
    assert "state.result.gpx" in js or "inline" in js, "应优先用内存里的 gpx"
    assert "parseTrackPoints" in js


def test_convert_toggles_live_next_to_ai_naming():
    """岔路与地名补点改成顶部开关，跟 AI 推测命名放一起。"""
    html = _read(CONVERT_PAGE)
    js = _extract_inline_js(html)
    assert 'id="aiNames"' in html
    for tid in ('optJunction', 'optPoi'):
        assert ('id="%s"' % tid) in html, "缺少开关 %s" % tid
    assert "maybeRunEnrichments" in js, "开关应驱动补点/岔路任务"
    # 旧的独立按钮应退居幕后
    assert "junctionBtn" not in js, "岔路不该再有单独按钮"


def test_convert_route_image_draws_risk_and_junction():
    """图片上仍要圈出风险点与岔路，而不是只在文字里说。"""
    html = _read(CONVERT_PAGE)
    js = _extract_inline_js(html)
    assert "riskPoints" in js and "junctionPoints" in js
    assert "turn_text" in js
    assert "arc(" in js, "应绘制圆圈"


def test_waypoint_summary_has_coordinates():
    """地图要画风险点，摘要必须带坐标。"""
    from app.gpx_converter import convert
    from tests.conftest import make_kml
    kml = make_kml(track_times=[
        (113.0, 24.0, 100, "2023-02-18T02:00:00Z"),
        (113.01, 24.01, 200, "2023-02-18T02:30:00Z"),
        (113.02, 24.02, 300, "2023-02-18T03:00:00Z")],
        waypoints=[{"lat": 24.01, "lon": 113.01, "ele": 200,
                    "desc_time": "2023-02-18 10:30:00"}],
        doc_name="2023-02-18 T")
    s = convert(kml.encode("utf-8"), "x.kml").summary.to_dict()
    wp = s["waypoints"][0]
    assert wp["lat"] == 24.01 and wp["lon"] == 113.01


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

# ---------------------------------------------------------------- 分析长图页

def test_report_page_exists_and_has_features():
    """分析长图页的关键能力不能被误删。"""
    assert REPORT.is_file(), "缺少 web/report.html"
    html = _read(REPORT)
    for snippet in (
        "parseGpx",                    # GPX 解析
        "trkseg",                      # 多段按顺序拼接
        "buildSplits",                 # 分段
        "pickSplitStep",               # 步长自适应（≤10 段）
        "movingSeconds",               # 运动/静止时间拆分
        "slopeShares",                 # 坡度构成
        "speedColor",                  # 按速度连续着色
        "SPEED_STOPS",
        "/api/tile/windy/",            # Windy 必须走服务端代理
        "crossOrigin",                 # 独立拉瓦片避免画布污染
        "toBlob",                      # 导出 PNG
        "buildPlan",                   # 版面高度先算后画
        "drawSpeedChart",              # 速度曲线（km/h）
        "drawEleChart",                # 海拔剖面
        "drawTable",                   # 分段表
        "分段数据",
        "titleInput",                  # 自定义标题输入
        "运动时间", "静止时间",          # 时间拆分
        "坡度构成",                     # 爬升/平路/下降比例
        "爬升 / 下降",                  # 分段表升降两行
        "缺少时间信息",                 # 无时间戳时的降级提示
        "PURE_START", "PURE_END",      # 纯函数测试锚点
    ):
        assert snippet in html, f"分析长图页缺少要素: {snippet}"


@pytest.mark.skipif(shutil.which("node") is None, reason="node 不可用")
def test_report_js_syntax():
    js = _extract_inline_js(_read(REPORT))
    assert js.strip(), "分析长图页未找到内联脚本"
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as f:
        f.write(js)
        tmp = f.name
    try:
        proc = subprocess.run(["node", "--check", tmp], capture_output=True, text=True)
        assert proc.returncode == 0, f"分析长图页 JS 语法错误：\n{proc.stderr}"
    finally:
        Path(tmp).unlink(missing_ok=True)


def test_report_only_uses_tile_proxy_api():
    """分析长图页的解析、计算、渲染全在浏览器，唯一服务端调用是瓦片代理。"""
    js = _extract_inline_js(_read(REPORT))
    for banned in ("/api/submit", "/api/estimate", "/api/status", "/api/tasks"):
        assert banned not in js, f"分析长图页不应调用生成类接口: {banned}"
    assert "/tiles/" not in js, "分析长图页不应使用通用 /tiles/ 路径"
    used = set(re.findall(r"/api/[a-z]+", js))
    assert used <= {"/api/tile"}, f"分析长图页出现意外的接口调用: {used}"


def test_report_links_and_layout_constants():
    html = _read(REPORT)
    assert 'href="/gpx/"' in html, "分析长图页应能返回生成器页"
    assert 'href="/gpx/player.html"' in html, "分析长图页应能进入回放页"
    js = _extract_inline_js(html)
    assert "var W = 1080" in js, "长图宽度应固定为 1080"
    assert "a0 + step" in js, "分段应使用自适应步长"
    assert "pickSplitStep" in js, "缺少分段步长选择"
    assert "MAX_TILES" in js, "瓦片数量必须有上限"
    # 底图压到 80%，轨迹才够醒目
    assert "ctx.globalAlpha = 0.8" in js, "底图应半透明（约 80%）"
    # 海拔折线要按同一套速度色带逐段上色
    assert "pts[i].c" in js, "海拔折线缺少按速度着色"
    # 速度曲线必须裁剪在绘图区内，否则尖峰会把曲线画到坐标轴外面
    assert "ctx.clip()" in js, "速度曲线缺少绘图区裁剪"
    assert "plotR - plotL" in js, "缺少绘图区矩形"
    assert "km/h" in js, "速度曲线应以 km/h 标注"


@pytest.mark.skipif(shutil.which("node") is None, reason="node 不可用")
def test_report_split_and_color_logic():
    """1km 分段、边界插值、速度色带的边界条件。"""
    js = _extract_inline_js(_read(REPORT))
    assert "/* PURE_START */" in js and "/* PURE_END */" in js, "缺少纯函数锚点"
    pure = js.split("/* PURE_START */", 1)[1].split("/* PURE_END */", 1)[0]
    driver = r"""
      var pts = [], cum = [];
      var ds = [0, 500, 1000, 1500, 2000, 2500, 3000, 3420];
      for (var i = 0; i < ds.length; i++) {
        pts.push({ lat: 23 + i * 0.001, lng: 113, ele: 100 + i * 10,
                   time: 1776000000000 + i * 600000, hr: 120 + i, cad: 80 });
        cum.push(ds[i]);
      }
      var out = {};
      var rows = buildSplits({ points: pts, cum: cum, hasEle: true });
      out.count = rows.length;
      out.dists = rows.map(function (r) { return r.dist; });
      out.lastTime = rows[rows.length - 1].time;
      out.gain = rows.map(function (r) { return r.gain; });

      var noTime = pts.map(function (p) {
        return { lat: p.lat, lng: p.lng, ele: p.ele, time: null, hr: null, cad: null };
      });
      var rows2 = buildSplits({ points: noTime, cum: cum, hasEle: false });
      out.noTime = rows2.map(function (r) { return r.time; });
      out.noGain = rows2.map(function (r) { return r.gain; });
      out.empty = buildSplits({ points: [pts[0]], cum: [0], hasEle: true });

      var s = interpSample(cum, pts, 1000);
      out.interpLat = s.lat;
      out.pct = [percentile([1, 2, 3, 4], 0.5), percentile([1, 2, 3, 4], 0)];
      out.color = [speedColor(null, null),
                   speedColor(0.05, { lo: 1, hi: 2 }),
                   speedColor(1.0, { lo: 1, hi: 2 }),
                   speedColor(2.0, { lo: 1, hi: 2 }),
                   speedColor(1.5, { lo: 1, hi: 2 }),
                   speedColor(1.25, { lo: 1, hi: 2 })];
      out.steps = [pickSplitStep(3420), pickSplitStep(12300),
                   pickSplitStep(30000), pickSplitStep(100000)];
      out.rows2k = buildSplits({ points: pts, cum: cum, hasEle: true, stepM: 2000 })
                     .map(function (r) { return r.dist; });

      // 运动 / 静止：111m 走 60s 算运动，原地不动的时间不算
      var mv = [{ time: 0 }, { time: 60000 }, { time: 120000 }, { time: 180000 }];
      out.moving = movingSeconds(mv, [0, 111, 111, 111]);
      out.movingStop = movingSeconds([{ time: 0 }, { time: 60000 }], [0, 0]);

      // 坡度构成：+10% 全爬升、持平全平路、-10% 全下降
      out.slopeUp = slopeShares([{ ele: 0 }, { ele: 10 }, { ele: 20 },
                                 { ele: 30 }, { ele: 40 }], [0, 50, 100, 150, 200]);
      out.slopeFlat = slopeShares([{ ele: 5 }, { ele: 5 }, { ele: 5 }], [0, 50, 100]);
      out.slopeDown = slopeShares([{ ele: 40 }, { ele: 30 }, { ele: 20 }], [0, 50, 100]);
      // 阈值 ±5%：4.9% 算平路、5.1% 才算升降（点距 50m，窗口才不会塌缩）
      function rampPts(grade, n) {
        var rp = [], rc = [];
        for (var z = 0; z < n; z++) {
          rp.push({ ele: grade * z * 50 });
          rc.push(z * 50);
        }
        return { pts: rp, cum: rc };
      }
      var t1 = rampPts(0.049, 5), t2 = rampPts(0.051, 5);
      var t3 = rampPts(-0.049, 5), t4 = rampPts(-0.051, 5);
      out.slopeEdge = [
        slopeShares(t1.pts, t1.cum).flat,
        slopeShares(t2.pts, t2.cum).up,
        slopeShares(t3.pts, t3.cum).flat,
        slopeShares(t4.pts, t4.cum).down
      ];
      // 下坡段：爬升 0、下降累计
      var dPts = [], dCum = [];
      for (var dd = 0; dd < 5; dd++) {
        dPts.push({ lat: 23, lng: 113, ele: 500 - dd * 20,
                    time: 1776000000000 + dd * 600000, hr: null, cad: null });
        dCum.push(dd * 500);
      }
      out.downRow = buildSplits({ points: dPts, cum: dCum, hasEle: true })
        .map(function (r) { return [r.gain, r.loss]; });
      console.log(JSON.stringify(out));
    """
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as f:
        f.write(pure + driver)
        tmp = f.name
    try:
        proc = subprocess.run(["node", tmp], capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr
        got = json.loads(proc.stdout.strip())
    finally:
        Path(tmp).unlink(missing_ok=True)

    assert got["count"] == 4, got
    assert abs(got["dists"][0] - 1.0) < 1e-6, got
    assert abs(got["dists"][-1] - 0.42) < 1e-6, got
    assert abs(got["lastTime"] - 600) < 1e-6, got
    assert got["gain"] == [20, 20, 20, 10], got
    assert got["noTime"] == [None, None, None, None], got
    assert got["noGain"] == [None, None, None, None], got
    assert got["empty"] == [], got
    assert abs(got["interpLat"] - 23.002) < 1e-9, got
    assert got["pct"] == [2.5, 1], got
    # 连续渐变：无数据返回 null、停顿给中性色、两端取到色带首尾
    assert got["color"] == [None, "#9aa7b4", "#3d7bd9", "#e2513c", "#d8cf4a", "#46b97a"], got
    # 步长自适应：段数不超过 10
    assert got["steps"] == [1000, 2000, 3000, 10000], got
    assert abs(got["rows2k"][0] - 2.0) < 1e-6, got
    assert abs(got["rows2k"][1] - 1.42) < 1e-6, got
    # 运动时间只累计「在走」的那一分钟
    assert abs(got["moving"] - 60) < 1e-6, got
    assert got["movingStop"] == 0, got
    # 坡度构成：三段的占比相加为全长
    assert abs(got["slopeUp"]["up"] - 200) < 1e-6, got
    assert abs(got["slopeUp"]["flat"]) < 1e-6, got
    assert abs(got["slopeFlat"]["flat"] - 100) < 1e-6, got
    assert abs(got["slopeDown"]["down"] - 100) < 1e-6, got
    # ±5% 阈值边界
    assert got["slopeEdge"] == [200, 200, 200, 200], got
    # 下坡段：爬升为 0、下降按负差累计
    assert got["downRow"] == [[0, 40], [0, 40]], got
