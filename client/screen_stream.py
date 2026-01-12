import asyncio
from utils import capture_frame
from protocol import encode

async def stream_desktop(writer, fps=2):
    interval = 1/fps
    while True:
        img_b64 = capture_frame()
        writer.write(encode({"type":"screen_stream","data":img_b64}))
        await writer.drain()
        await asyncio.sleep(interval)
