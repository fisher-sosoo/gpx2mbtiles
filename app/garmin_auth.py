"""Garmin 预授权 CLI（一次性交互登录，只保存 OAuth 令牌）。

容器内用法：
    docker exec -it gpx2mbtiles python -m app.garmin_auth
    docker exec -it gpx2mbtiles python -m app.garmin_auth --verify

账号密码只在这次登录里用一次，不写入磁盘、不进环境变量之外的地方。
"""
from __future__ import annotations

import argparse
import getpass
import os
import shutil
import sys

from . import garmin_source
from .config import get_settings


def _email() -> str:
    return os.getenv("GARMIN_EMAIL", "").strip() or input("Garmin 邮箱：").strip()


def _password() -> str:
    value = os.getenv("GARMIN_PASSWORD", "")
    return value if value else getpass.getpass("Garmin 密码（不回显）：")


def _mfa() -> str:
    return input("MFA 验证码（未开启直接回车）：").strip()


def verify(settings) -> int:
    if not garmin_source.has_token(settings):
        print(f"未找到令牌目录：{garmin_source.token_dir(settings)}")
        print("请先运行 python -m app.garmin_auth 完成一次授权。")
        return 2
    try:
        client = garmin_source.get_client(settings)
    except garmin_source.GarminAuthError as exc:
        print(f"授权不可用：{exc}")
        return 1
    name = ""
    try:
        name = client.get_full_name() or ""
    except Exception:  # 取名字失败不代表授权不可用
        pass
    print("授权可用" + (f"：{name}" if name else ""))
    return 0


def login(settings, force: bool = False) -> int:
    directory = garmin_source.token_dir(settings)
    if force and os.path.isdir(directory):
        shutil.rmtree(directory, ignore_errors=True)
    os.makedirs(directory, exist_ok=True)

    email, password = _email(), _password()
    if not email or not password:
        print("邮箱或密码为空，已中止。", file=sys.stderr)
        return 1

    client = garmin_source.new_client(
        settings, email=email, password=password, prompt_mfa=_mfa)
    try:
        client.login(directory)
    except Exception as exc:
        print(f"登录失败：{exc}", file=sys.stderr)
        print("若已开启 MFA，请确认验证码；令牌损坏可加 --force 重新登录。",
              file=sys.stderr)
        return 1

    if not garmin_source.has_token(settings):
        # 个别版本 login() 不落盘，这里补一次。
        try:
            client.garth.dump(directory)
        except Exception:
            pass

    if not garmin_source.has_token(settings):
        print("登录似乎成功了，但没有写出令牌文件；请加 --force 重试。", file=sys.stderr)
        return 1

    garmin_source.reset_client()
    print(f"授权成功，令牌已保存到 {directory}")
    print("现在可以打开 /gpx/garmin.html 选择活动出图了。")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Garmin 一次性预授权")
    parser.add_argument("--verify", action="store_true", help="只校验现有令牌，不登录")
    parser.add_argument("--force", action="store_true", help="清掉旧令牌后重新登录")
    args = parser.parse_args(argv)

    settings = get_settings()
    if args.verify:
        return verify(settings)
    return login(settings, force=args.force)


if __name__ == "__main__":
    raise SystemExit(main())
