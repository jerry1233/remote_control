import base64
import cv2
import numpy as np

def show_stream_frame(msg, window_name="Client Stream"):
    img_data = base64.b64decode(msg["data"])
    nparr = np.frombuffer(img_data, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is not None:
        cv2.imshow(window_name, img)
        cv2.waitKey(1)
