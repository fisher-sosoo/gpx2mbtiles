import asyncio
import os
import sys

from aiohttp import web

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c6360000002000150cbe9ee0000000049454e44ae426082"
)


async def tile(request):
    delay = float(os.environ.get("TILE_DELAY", "0"))
    if delay:
        await asyncio.sleep(delay)
    return web.Response(body=PNG, content_type="image/png")


app = web.Application()
app.router.add_get("/tiles/{z}/{x}/{y}.png", tile)

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 18199
    web.run_app(app, host="127.0.0.1", port=port)
