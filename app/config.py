import os
from dataclasses import dataclass


def _env_int(name: str, default: int, lo=None, hi=None) -> int:
    try:
        v = int(os.getenv(name, str(default)))
    except ValueError:
        v = default
    if lo is not None:
        v = max(lo, v)
    if hi is not None:
        v = min(hi, v)
    return v


def _env_float(name: str, default: float, lo=None, hi=None) -> float:
    try:
        v = float(os.getenv(name, str(default)))
    except ValueError:
        v = default
    if lo is not None:
        v = max(lo, v)
    if hi is not None:
        v = min(hi, v)
    return v


def _read_key_file(explicit_path: str = "") -> str:
    """读本机未入库的 apikey 文件。

    优先用 AI_API_KEY_FILE 指定的路径，否则找仓库根目录的 apikey。
    只是为了本地开发方便；线上用环境变量。文件不存在就当作没配。
    """
    candidates = []
    if explicit_path:
        candidates.append(explicit_path)
    candidates.append(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "apikey"))
    for path in candidates:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                value = fh.read().strip()
        except OSError:
            continue
        if value:
            return value
    return ""


DEFAULT_IPHONE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)


@dataclass
class TileProvider:
    """瓦片图层提供者：URL 模板、子域名轮询、UA/Referer、最大缩放。"""
    key: str
    label: str
    url_template: str
    subdomains: tuple = ()
    user_agent: str = DEFAULT_IPHONE_UA
    referer: str = ""
    max_zoom: int = 17


class Settings:
    def __init__(self):
        data_dir = os.getenv("DATA_DIR", "./data")
        if not os.path.isabs(data_dir):
            data_dir = os.path.abspath(data_dir)

        tile_proxy = os.getenv("TILE_PROXY", "").strip()
        if not tile_proxy:
            tile_proxy = os.getenv("HTTPS_PROXY", os.getenv("https_proxy", "")).strip()
        if not tile_proxy:
            tile_proxy = os.getenv("HTTP_PROXY", os.getenv("http_proxy", "")).strip()

        self.data_dir = data_dir
        # Windy “Outdoor map”户外图层真实瓦片源（provider: Seznam.cz）。
        # 服务端实测瓦片覆盖 z0–z19；Windy 网页端地图 minZoom=3 / maxZoom=16。
        self.tile_url_template = os.getenv(
            "TILE_URL_TEMPLATE",
            "https://tiles.windy.com/v1/maptiles/outdoor/256/{z}/{x}/{y}/?lang=en",
        )
        self.tile_proxy = tile_proxy or None
        self.user_agent = os.getenv("TILE_USER_AGENT", DEFAULT_IPHONE_UA)
        self.referer = os.getenv("TILE_REFERER", "https://www.windy.com/")
        self.max_concurrency = _env_int("MAX_CONCURRENCY", 8, 1, 32)
        self.request_interval_ms = _env_int("REQUEST_INTERVAL_MS", 100, 0, 10000)
        self.tile_timeout_seconds = _env_float("TILE_TIMEOUT_SECONDS", 30.0, 1.0, 120.0)
        self.retry_max = _env_int("RETRY_MAX", 3, 0, 10)
        self.retry_backoff_base = _env_float("RETRY_BACKOFF_BASE", 0.5, 0.05, 10.0)
        self.block_pause_seconds = _env_float("BLOCK_PAUSE_SECONDS", 30.0, 1.0, 300.0)
        self.block_fail_min_count = _env_int("BLOCK_FAIL_MIN_COUNT", 15, 1, 10000)
        self.block_fail_ratio = _env_float("BLOCK_FAIL_RATIO", 0.25, 0.01, 1.0)
        self.block_consecutive_threshold = _env_int("BLOCK_CONSECUTIVE_THRESHOLD", 6, 2, 100)
        self.task_timeout_seconds = _env_int("TASK_TIMEOUT_SECONDS", 3600, 60, 86400)
        self.file_expiry_seconds = _env_int("FILE_EXPIRY_SECONDS", 259200, 60, 2592000)
        self.cleanup_interval_seconds = _env_int("CLEANUP_INTERVAL_SECONDS", 60, 5, 3600)
        self.max_running_tasks = _env_int("MAX_RUNNING_TASKS", 2, 1, 16)
        self.max_tiles_per_task = _env_int("MAX_TILES_PER_TASK", 60000, 100, 1000000)
        self.zoom_min_cap = _env_int("ZOOM_MIN_CAP", 3, 0, 22)
        self.zoom_max_cap = _env_int("ZOOM_MAX_CAP", 18, 0, 22)
        self.buffer_min = _env_float("BUFFER_MIN_METERS", 0.0, 0.0, 100000.0)
        self.buffer_max = _env_float("BUFFER_MAX_METERS", 10000.0, 0.0, 200000.0)
        self.max_gpx_bytes = _env_int("MAX_GPX_BYTES", 52428800, 1024, 1073741824)
        # KML → GPX 转换：输入上限比生成器更紧（转换是同步请求，大文件会拖住 worker）
        self.max_convert_bytes = _env_int("MAX_CONVERT_BYTES", 10485760, 1024, 104857600)

        # ---- AI 辅助命名（可选，默认关闭）----
        # 只有请求显式开启 ai_names 且配置了密钥才调用；失败自动回退规则命名。
        # 密钥来源：环境变量 AI_API_KEY，或仓库根目录下一个未入库的 apikey 文件。
        # 绝不硬编码，也绝不写进日志与响应。
        self.ai_api_key = (os.getenv("AI_API_KEY", "").strip()
                           or _read_key_file(os.getenv("AI_API_KEY_FILE", "")))
        self.ai_base_url = os.getenv("AI_BASE_URL", "https://api.deepseek.com").strip()
        self.ai_model = os.getenv("AI_MODEL", "deepseek-chat").strip()
        self.ai_timeout_seconds = _env_float("AI_TIMEOUT_SECONDS", 30.0, 3.0, 180.0)
        self.ai_max_tokens = _env_int("AI_MAX_TOKENS", 2000, 200, 8192)

        # ---- 项目空间（每次转换落一个目录 + 一条账本记录）----
        # 超出条数或超过保留天数时按最久未访问淘汰；原件最小，产物是 GPX 文本，
        # 单项目通常几十 KB，200 个项目也就几 MB。
        self.max_projects = _env_int("MAX_PROJECTS", 200, 0, 10000)
        self.project_retention_days = _env_int("PROJECT_RETENTION_DAYS", 30, 0, 3650)

        # ---- OSM 地名补点 ----
        # Overpass 是公共设施：查询慢（实测约 42 秒）、有配额，必须限流并缓存结果。
        # 查询走代理（墙内直连 DNS 解析失败），为空时复用 TILE_PROXY。
        self.poi_enabled = os.getenv("POI_ENABLED", "1").strip().lower()             not in ("0", "false", "no", "off")
        self.poi_proxy = os.getenv("POI_PROXY", "").strip()
        self.poi_timeout_seconds = _env_int("POI_TIMEOUT_SECONDS", 180, 10, 600)
        self.poi_bbox_pad_m = _env_float("POI_BBOX_PAD_METERS", 500.0, 0.0, 5000.0)
        self.poi_max_count = _env_int("POI_MAX_COUNT", 60, 1, 500)
        # Overpass 5xx 是常态，需要退避重试；4xx 不重试
        self.poi_retry_max = _env_int("POI_RETRY_MAX", 2, 0, 5)

        # ---- 行前指南（天气）----
        # Open-Meteo 免费无需 key，实测 2.6 秒；墙内需代理，为空时复用 TILE_PROXY。
        self.weather_proxy = os.getenv("WEATHER_PROXY", "").strip()
        self.weather_timeout_seconds = _env_int("WEATHER_TIMEOUT_SECONDS", 30, 5, 120)
        # 墙内服务器访问模型 API 必须走代理；为空时复用 TILE_PROXY
        self.ai_proxy = os.getenv("AI_PROXY", "").strip()
        # 低于此剩余空间时停止写缓存（默认 3GB；8G 缓存 + 3G 余量，40G 盘安全）
        self.disk_min_free_bytes = _env_int(
            "DISK_MIN_FREE_BYTES", 3221225472, 104857600, 1099511627776)
        self.auth_token = os.getenv("AUTH_TOKEN", "").strip()

        # ---- 瓦片代理缓存（/api/tile/...）----
        # 浏览器直接请求 Windy 会被 CORS 拦（响应头 credentials:true 与 origin:*
        # 并存，违反规范，Chrome 报 ERR_BLOCKED_BY_ORB）。改由服务端代取，
        # 同源返回并落盘缓存，重复浏览不再消耗流量。
        self.tile_cache_enabled = os.getenv("TILE_CACHE_ENABLED", "1").strip().lower()             not in ("0", "false", "no", "off")
        # 缓存总容量上限（默认 8GB；服务器 40G 盘、已用约 9G，
        # 留足余量给成品文件和系统）。瓦片是只读缓存，丢了会自动回源，可安全淘汰。
        self.tile_cache_max_bytes = _env_int(
            "TILE_CACHE_MAX_BYTES", 8589934592, 10485760, 107374182400)
        # 单张瓦片超过此大小不缓存（防止异常响应撑爆磁盘）
        self.tile_cache_max_tile_bytes = _env_int(
            "TILE_CACHE_MAX_TILE_BYTES", 5242880, 10240, 52428800)
        # 允许代理的图层：仅这些 key 可通过 /api/tile/ 访问
        self.tile_proxy_layers = tuple(
            x.strip() for x in os.getenv("TILE_PROXY_LAYERS", "windy").split(",") if x.strip()
        )

        # 瓦片图层注册表：windy 为默认（兼容现有 env 覆盖），opentopomap 为新增地形图
        self.tile_providers: dict[str, TileProvider] = {
            "windy": TileProvider(
                key="windy",
                label="Windy 户外",
                url_template=self.tile_url_template,
                user_agent=self.user_agent,
                referer=self.referer,
                max_zoom=18,
            ),
            "opentopomap": TileProvider(
                key="opentopomap",
                label="OpenTopoMap 地形图",
                url_template="https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
                subdomains=("a", "b", "c"),
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
                ),
                referer="https://opentopomap.org/",
                max_zoom=17,
            ),
        }
        self.default_tile_layer = "windy"

        # ---- Garmin 活动长图 ----
        # 只保存预授权得到的 OAuth 令牌，不保存账号密码。令牌目录独立于 DATA_DIR：
        # data/ 是给下载文件用的，任何"整体暴露 data/"的改动都不该顺带泄露账号。
        self.garmin_enabled = os.getenv("GARMIN_ENABLED", "1").strip().lower() \
            not in ("0", "false", "no", "off")
        self.garmin_tokens = os.getenv(
            "GARMINTOKENS", "").strip() or os.path.expanduser("~/.garminconnect")
        self.garmin_is_cn = os.getenv("GARMIN_IS_CN", "").strip().lower() \
            in ("1", "true", "yes", "on")
        self.garmin_days_default = _env_int("GARMIN_DAYS_DEFAULT", 30, 1, 365)
        self.garmin_activity_limit = _env_int("GARMIN_ACTIVITY_LIMIT", 50, 1, 500)
        self.garmin_cache_max_mb = _env_int("GARMIN_CACHE_MAX_MB", 512, 0, 10240)
        self.garmin_min_interval_seconds = _env_float(
            "GARMIN_MIN_INTERVAL_SECONDS", 1.0, 0.0, 60.0)
        self.garmin_timeout_seconds = _env_float("GARMIN_TIMEOUT_SECONDS", 60.0, 5.0, 300.0)
        # 容器内的出网出口：本机实测容器没有直连，全部走宿主机上的代理。
        # 不单独配时复用瓦片代理（同一台机器上通常就是那一个）。
        self.garmin_proxy = (os.getenv("GARMIN_PROXY", "").strip()
                             or self.tile_proxy or "")
        # 可选：令牌过期后自动用账号密码重登（默认关闭）。
        # 密码只从环境变量读，绝不写盘；开启后服务器上等于持有一份长期凭据。
        self.garmin_email = os.getenv("GARMIN_EMAIL", "").strip()
        self.garmin_password = os.getenv("GARMIN_PASSWORD", "")
        self.garmin_auto_relogin = os.getenv(
            "GARMIN_AUTO_RELOGIN", "").strip().lower() in ("1", "true", "yes", "on")


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
