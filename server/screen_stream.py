import struct
import cv2
import numpy as np
from server import state

async def handle_stream(reader, client_id):
    """
    接收客户端桌面流并显示
    """
    state.streaming.add(client_id)
    window_name = f"VIEW - {client_id}"
    try:
        while True:
            raw_len = await reader.readexactly(4)
            frame_len = struct.unpack(">I", raw_len)[0]
            frame_data = await reader.readexactly(frame_len)

            img = cv2.imdecode(
                np.frombuffer(frame_data, np.uint8),
                cv2.IMREAD_COLOR
            )

            cv2.imshow(window_name, img)
            if cv2.waitKey(1) == 27:  # ESC 退出
                break
    except Exception:
        pass
    finally:
        state.streaming.discard(client_id)
        try:
            cv2.destroyWindow(window_name)
            cv2.waitKey(1)
        except Exception:
            pass
