import mss
import numpy as np

sct = mss.mss()

def capture_screen():
    monitor = sct.monitors[1]
    img = np.array(sct.grab(monitor))
    return img[:, :, :3]
