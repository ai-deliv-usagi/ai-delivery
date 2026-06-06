import queue


class FrameStore:
    def __init__(self):
        self._queue = queue.Queue(maxsize=1)

    def put(self, frame_bytes):
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        self._queue.put(frame_bytes)

    def get_frame_bytes(self):
        try:
            return self._queue.get_nowait()
        except queue.Empty:
            return None

