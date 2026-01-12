import io
import base64
from mss import mss
from PIL import Image

def capture_frame(quality=40):
    with mss() as sct:
        monitor = sct.monitors[1]
        img = sct.grab(monitor)
        im = Image.frombytes("RGB", img.size, img.rgb)
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=quality)
        return base64.b64encode(buf.getvalue()).decode()
