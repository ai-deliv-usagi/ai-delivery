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

    def enqueue_status(self, status, message):
        labels = {
            "starting": "接続中",
            "connected": "接続成功",
            "error": "接続エラー",
        }
        self.event_queue.put(
            {
                "type": "tiktok_status",
                "status": status,
                "label": labels.get(status, "状態更新"),
                "message": message,
            }
        )

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

    @staticmethod
    def extract_gift_type(event):
        gift = getattr(event, "gift", None)
        if gift is None:
            return None

        for attr in ("type", "gift_type"):
            value = getattr(gift, attr, None)
            if value is not None:
                return value

        info = getattr(gift, "info", None)
        if info is not None:
            value = getattr(info, "type", None)
            if value is not None:
                return value

        return None

    @staticmethod
    def extract_repeat_count(event):
        value = getattr(event, "repeat_count", None)
        if value is not None:
            return LocalTikTokListener.normalize_positive_int(value, default=1)

        gift = getattr(event, "gift", None)
        if gift is not None:
            value = getattr(gift, "repeat_count", None)
            if value is not None:
                return LocalTikTokListener.normalize_positive_int(value, default=1)

        return 1

    @staticmethod
    def normalize_positive_int(value, default=None):
        try:
            number = int(value)
        except (TypeError, ValueError):
            return default
        return number if number > 0 else default

    @classmethod
    def extract_diamond_count(cls, event):
        gift = getattr(event, "gift", None)
        if gift is None:
            return None

        for source in (gift, getattr(gift, "info", None)):
            if source is None:
                continue
            diamond_count = cls.normalize_positive_int(
                getattr(source, "diamond_count", None)
            )
            if diamond_count is not None:
                return diamond_count

        return None

    @classmethod
    def is_streak_in_progress(cls, event):
        streaking = getattr(event, "streaking", None)
        if streaking is not None:
            return bool(streaking)

        gift_type = cls.extract_gift_type(event)
        repeat_end = getattr(event, "repeat_end", None)
        if repeat_end is None:
            gift = getattr(event, "gift", None)
            repeat_end = getattr(gift, "repeat_end", None) if gift is not None else None

        if str(gift_type) == "1" and repeat_end is not None:
            return str(repeat_end).lower() in {"0", "false"}

        return False

    def _setup_events(self):
        @self.client.on(ConnectEvent)
        async def on_connect(_event):
            message = f"TikTokLiveに接続しました: {self.unique_id}"
            self.log(message)
            self.enqueue_status("connected", message)

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
            if self.is_streak_in_progress(event):
                return

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

            repeat_count = self.extract_repeat_count(event)
            diamond_count = self.extract_diamond_count(event)
            self.event_queue.put(
                {
                    "type": "gift",
                    "user": event.user.nickname,
                    "gift_name": gift_name,
                    "repeat_count": repeat_count,
                    "diamond_count": diamond_count,
                    "total_diamonds": (
                        diamond_count * repeat_count
                        if diamond_count is not None
                        else None
                    ),
                }
            )

        @self.client.on(FollowEvent)
        async def on_follow(event):
            self.event_queue.put({"type": "follow", "user": event.user.nickname})

    def start(self):
        if self.thread and self.thread.is_alive():
            return

        self.enqueue_status("starting", f"TikTokLiveへ接続しています: {self.unique_id}")
        self.thread = threading.Thread(target=self.run_forever, daemon=True)
        self.thread.start()

    def run_forever(self):
        while True:
            try:
                self.client.run(fetch_gift_info=True)
            except TypeError:
                self.client.run()
            except Exception as exc:
                message = f"TikTokLive接続エラー: {exc}"
                self.log(message)
                self.enqueue_status(
                    "error",
                    f"{message}。15秒後に再接続します。",
                )
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
