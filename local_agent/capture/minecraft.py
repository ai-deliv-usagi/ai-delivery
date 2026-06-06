import io
import os

import pygetwindow as gw
from mss import mss
from PIL import Image


class MinecraftCapturer:
    def __init__(self, window_title="Minecraft", save_dir="captured_images"):
        self.sct = mss()
        self.window_title = window_title
        self.save_dir = save_dir

        if not os.path.exists(self.save_dir):
            os.makedirs(self.save_dir)

    def get_frame_bytes(self):
        try:
            targets = [w for w in gw.getWindowsWithTitle(self.window_title) if w.visible]
            if not targets:
                return None

            win = targets[0]
            if win.isMinimized:
                return None

            monitor = {
                "top": win.top,
                "left": win.left,
                "width": win.width,
                "height": win.height,
            }
            sct_img = self.sct.grab(monitor)
            img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
            img = img.resize((640, 360))

            buf = io.BytesIO()
            img.save(buf, format="JPEG")
            return buf.getvalue()
        except Exception as exc:
            print(f"Capture error: {exc}")
            return None

