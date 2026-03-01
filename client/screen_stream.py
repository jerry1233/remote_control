import asyncio
import struct
import cv2
from client import utils, config

async def start_stream(client_id, stop_event):
    writer = None
    while not stop_event.is_set():
        try:
            reader, writer = await asyncio.open_connection(
                config.SERVER_HOST,
                config.STREAM_PORT
            )
            writer.write(f"{client_id}\n".encode())
            await writer.drain()
            break
        except Exception:
            await asyncio.sleep(5)  # server 没启动时重试

    try:
        while not stop_event.is_set():
            frame = utils.capture_screen()
            frame = cv2.resize(frame, (1280, 720))
            _, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            data = encoded.tobytes()

            if writer is None:
                await asyncio.sleep(0.1)
                continue

            writer.write(struct.pack(">I", len(data)) + data)
            await writer.drain()
            await asyncio.sleep(0.1)
    finally:
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
