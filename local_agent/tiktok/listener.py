import queue
import threading
import time

from TikTokLive import TikTokLiveClient
from TikTokLive.events import CommentEvent, ConnectEvent, FollowEvent, GiftEvent, JoinEvent


class LocalTikTokListener:
    def __init__(self, unique_id, log=None):
        self.unique_id = unique_id
        self.log = log or (lambda _message: None)
        self.client = TikTokLiveClient(unique_id=unique_id)
        self.event_queue = queue.Queue()
        self.join_buffer = []
        self.last_join_time = time.time()
        self.thread = None
        self._setup_events()

    @staticmethod
    def extract_gift_name(event):
        gift = getattr(event, "gift", None)
        if gift is None:
            return None

        for attr in ("name", "gift_name"):
            value = getattr(gift, attr, None)
            if value:
                return value

        info = getattr(gift, "info", None)
        if info is not None:
            value = getattr(info, "name", None)
            if value:
                return value

        return None

    def _setup_events(self):
        @self.client.on(ConnectEvent)
        async def on_connect(_event):
            self.log(f"TikTokLive connected: {self.unique_id}")

        @self.client.on(CommentEvent)
        async def on_comment(event):
            self.event_queue.put(
                {"type": "comment", "user": event.user.nickname, "text": event.comment}
            )

        @self.client.on(JoinEvent)
        async def on_join(event):
            self.join_buffer.append(event.user.nickname)

        @self.client.on(GiftEvent)
        async def on_gift(event):
            gift_name = self.extract_gift_name(event)
            if not gift_name:
                self.event_queue.put(
                    {
                        "type": "gift_unknown",
                        "user": event.user.nickname,
                        "raw": repr(getattr(event, "gift", None)),
                    }
                )
                return

            self.event_queue.put(
                {
                    "type": "gift",
                    "user": event.user.nickname,
                    "gift_name": gift_name,
                }
            )

        @self.client.on(FollowEvent)
        async def on_follow(event):
            self.event_queue.put({"type": "follow", "user": event.user.nickname})

    def start(self):
        if self.thread and self.thread.is_alive():
            return

        self.thread = threading.Thread(target=self.run_forever, daemon=True)
        self.thread.start()

    def run_forever(self):
        while True:
            try:
                self.client.run(fetch_gift_info=True)
            except TypeError:
                self.client.run()
            except Exception as exc:
                self.log(f"TikTokLive connection error: {exc}")
                time.sleep(15)

    def fetch_events(self):
        events = []

        while not self.event_queue.empty():
            events.append(self.event_queue.get_nowait())

        now = time.time()
        if self.join_buffer and (
            len(self.join_buffer) >= 3 or (now - self.last_join_time > 10)
        ):
            users = ", ".join(self.join_buffer)
            count = len(self.join_buffer)
            events.append({"type": "join_bulk", "users": users, "count": count})
            self.join_buffer = []
            self.last_join_time = now

        return events
