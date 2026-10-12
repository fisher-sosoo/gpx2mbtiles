"""瓦片代理与磁盘缓存。

为什么需要它
------------
浏览器直接向 Windy 请求瓦片会失败：Windy 的响应头同时带
    access-control-allow-credentials: true
    access-control-allow-origin: *
这两个头按 CORS 规范不能并存（通配符源不允许携带凭据），
Chrome 会把响应判为不可用并报 ERR_BLOCKED_BY_ORB，表现为底图整片空白。
服务端代取则不受此限制（服务器不做 CORS 校验），
同源返回给前端即可正常显示。

缓存策略
--------
- 按 layer/z/x/y 落盘，路径分片避免单目录文件过多
- 命中直接返回，不打上游（省流量、也避免被 Windy 限流）
- 总额超上限时按 mtime 做 LRU 清理
- 磁盘剩余低于阈值时停止写入（只读缓存，不影响已有瓦片）
"""
from __future__ import annotations

import logging
import math
import os
import time
from pathlib import Path

logger = logging.getLogger("gpx2mbtiles.tile_cache")


def tile_path(root: Path, layer: str, z: int, x: int, y: int) -> Path:
    """分片存放：root/<layer>/<z>/<x//1000>/<x>/<y>.<ext 后缀省略>"""
    return root / layer / str(z) / str(x // 1000) / str(x) / f"{y}.tile"


class TileCache:
    """磁盘瓦片缓存：读写 + LRU 淘汰 + 容量统计。"""

    def __init__(self, settings):
        self._s = settings
        self.root = Path(settings.data_dir) / "tilecache"
        self._bytes = 0
        self._count = 0
        self._scanned = False

    # ---------------------------------------------------------------- 统计
    def _scan(self):
        """首次使用时统计已用量（冷启动只扫一次）。"""
        total = 0
        count = 0
        if self.root.is_dir():
            for dirpath, _dirnames, filenames in os.walk(self.root):
                for fn in filenames:
                    if not fn.endswith(".tile"):
                        continue
                    try:
                        total += os.path.getsize(os.path.join(dirpath, fn))
                        count += 1
                    except OSError:
                        pass
        self._bytes = total
        self._count = count
        self._scanned = True
        logger.info("tile cache scanned: %d files, %.1f MB",
                    count, total / 1048576)

    def stats(self) -> dict:
        if not self._scanned:
            self._scan()
        return {
            "enabled": self._s.tile_cache_enabled,
            "files": self._count,
            "bytes": self._bytes,
            "mb": round(self._bytes / 1048576, 1),
            "max_bytes": self._s.tile_cache_max_bytes,
            "max_mb": round(self._s.tile_cache_max_bytes / 1048576, 1),
            "layers": list(self._s.tile_proxy_layers),
        }

    # ---------------------------------------------------------------- 读
    def get(self, layer: str, z: int, x: int, y: int) -> bytes | None:
        if not self._s.tile_cache_enabled:
            return None
        p = tile_path(self.root, layer, z, x, y)
        try:
            data = p.read_bytes()
        except (OSError, ValueError):
            return None
        if not data:
            return None
        # 更新访问时间，供 LRU 使用
        try:
            os.utime(p, None)
        except OSError:
            pass
        return data

    # ---------------------------------------------------------------- 写
    def _disk_ok(self) -> bool:
        try:
            st = os.statvfs(self.root if self.root.is_dir() else self.root.parent)
            return st.f_bavail * st.f_frsize >= self._s.disk_min_free_bytes
        except OSError:
            return True

    def put(self, layer: str, z: int, x: int, y: int, data: bytes):
        if not self._s.tile_cache_enabled:
            return
        if len(data) > self._s.tile_cache_max_tile_bytes:
            return
        if not self._disk_ok():
            return
        p = tile_path(self.root, layer, z, x, y)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            # 先写临时文件再原子替换，避免读到半截文件
            tmp = p.with_suffix(".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, p)
        except OSError as exc:
            logger.debug("tile cache write failed %s: %s", p, exc)
            return
        if not self._scanned:
            self._scan()
        self._bytes += len(data)
        self._count += 1
        if self._bytes > self._s.tile_cache_max_bytes:
            self.evict()

    # ---------------------------------------------------------------- 淘汰
    def evict(self, target_ratio: float = 0.85):
        """按 mtime 从旧到新删除，直到降到上限的 target_ratio 以下。"""
        if not self.root.is_dir():
            return 0
        target = int(self._s.tile_cache_max_bytes * target_ratio)
        entries = []
        for dirpath, _dirnames, filenames in os.walk(self.root):
            for fn in filenames:
                if not (fn.endswith(".tile") or fn.endswith(".tmp")):
                    continue
                fp = os.path.join(dirpath, fn)
                try:
                    st = os.stat(fp)
                except OSError:
                    continue
                entries.append((st.st_mtime, st.st_size, fp))
        entries.sort()  # 最旧的在前

        freed = 0
        removed = 0
        cur = self._bytes
        for _mtime, size, fp in entries:
            if cur <= target:
                break
            try:
                os.remove(fp)
                cur -= size
                freed += size
                removed += 1
            except OSError:
                pass
        self._bytes = max(0, cur)
        self._count = max(0, self._count - removed)
        if removed:
            logger.info("tile cache evicted %d files, freed %.1f MB",
                        removed, freed / 1048576)
        self._prune_empty_dirs()
        return removed

    def _prune_empty_dirs(self):
        """删掉因淘汰而变空的目录，避免留下大量空目录。"""
        try:
            for dirpath, dirnames, filenames in os.walk(self.root, topdown=False):
                if dirpath == str(self.root):
                    continue
                if not dirnames and not filenames:
                    try:
                        os.rmdir(dirpath)
                    except OSError:
                        pass
        except OSError:
            pass


# ---------------------------------------------------------------- XYZ 校验
def valid_xyz(z: int, x: int, y: int) -> bool:
    if not (0 <= z <= 22):
        return False
    n = 1 << z
    return 0 <= x < n and 0 <= y < n
