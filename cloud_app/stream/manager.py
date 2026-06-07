import sys
import threading
import time
import queue

from flask import jsonify

from cloud_app.dashboard.state import add_log, dashboard_data
from cloud_app.personalities.library import GIFT_TO_MODE, PERSONALITY_LIBRARY


SPEED_INSTRUCTION = "\n一言だけ、自然な日本語で短く話してください。"


class StreamManager:
    def __init__(self, capturer, ai, voice, tiktok):
        self.capturer = capturer
        self.ai = ai
        self.voice = voice
        self.tiktok = tiktok

        self.personality_library = PERSONALITY_LIBRARY
        self.gift_to_mode = GIFT_TO_MODE
        self.event_queue = queue.Queue()

        self.override_mode_id = None
        self.override_expiry = 0
        self.gift_queue = []
        self.pending_context = ""
        self.current_gen_id = 0
        self.is_generating = False
        self.session_active = False
        self.tiktok_thread = None

    @staticmethod
    def normalize_gift_name(gift_name):
        return str(gift_name).strip().casefold()

    def add_log(self, msg):
        add_log(msg)

    def trigger_manual_jack(self, mode_id):
        if mode_id in self.personality_library:
            now = time.time()
            self.current_gen_id = now
            if hasattr(self, "voice"):
                self.voice.stop()
            self.voice.is_speaking = False
            self.override_mode_id = mode_id
            self.override_expiry = now + 60
            mode_name = self.personality_library[mode_id]["name"]
            self.add_log(f"強制介入: {mode_name}")
            self.pending_context += (
                f"\n# 手動介入: すぐに「{mode_name}」として反応してください。"
                "出力は日本語のみです。"
            )
            return jsonify({"status": "success", "mode": mode_name})
        return jsonify({"status": "error"}), 400

    def start_session(self):
        if self.session_active:
            return {"status": "already_started"}

        self.session_active = True
        self.add_log("配信セッション開始")
        self.start_tiktok_listener()
        dashboard_data["is_online"] = True
        return {"status": "started"}

    def stop_session(self):
        self.session_active = False
        self.add_log("配信セッション停止")
        dashboard_data["is_online"] = False
        return {"status": "stopped"}

    def start_tiktok_listener(self):
        if not hasattr(self.tiktok, "run_forever"):
            return

        if self.tiktok_thread and self.tiktok_thread.is_alive():
            return

        self.tiktok_thread = threading.Thread(target=self.tiktok.run_forever, daemon=True)
        self.tiktok_thread.start()

    def debug_input_loop(self):
        while True:
            cmd = sys.stdin.readline().strip().lower()

            if cmd == "rose":
                self.event_queue.put(
                    {"type": "gift", "user": "DebugUser", "gift_name": "Rose"}
                )
            elif cmd == "heart":
                self.event_queue.put(
                    {"type": "gift", "user": "DebugUser", "gift_name": "Finger Heart"}
                )
            elif cmd == "ice":
                self.event_queue.put(
                    {"type": "gift", "user": "DebugUser", "gift_name": "Ice Cream"}
                )
            elif cmd == "comment":
                self.event_queue.put(
                    {"type": "comment", "user": "DebugUser", "text": "hello"}
                )

    def run(self, flask_app=None, port=5000, enable_debug_input=False):
        if flask_app is not None:
            threading.Thread(
                target=lambda: flask_app.run(port=port, debug=False, use_reloader=False),
                daemon=True,
            ).start()
        self.start_session()
        if enable_debug_input:
            threading.Thread(target=self.debug_input_loop, daemon=True).start()

        while True:
            self.tick()
            time.sleep(0.1)

    def tick(self):
        if not self.session_active:
            return None

        now = time.time()
        self.process_pending_events()
        self.update_mode(now)

        active_id = self.get_active_mode_id(now)
        self.update_dashboard(active_id, now)
        self.start_generation_if_ready(active_id)

    def refresh_dashboard(self):
        now = time.time()
        if self.session_active:
            self.process_pending_events()
        self.update_mode(now)
        active_id = self.get_active_mode_id(now)
        self.update_dashboard(active_id, now)
        return dashboard_data

    def process_pending_events(self):
        events = []

        if hasattr(self.tiktok, "fetch_events"):
            events.extend(self.tiktok.fetch_events())

        while not self.event_queue.empty():
            events.append(self.event_queue.get_nowait())

        self.handle_events(events)
        return events

    def submit_events(self, events):
        accepted = 0
        for event in events:
            if not isinstance(event, dict) or "type" not in event:
                continue
            self.event_queue.put(event)
            accepted += 1

        now = time.time()
        self.process_pending_events()
        self.update_mode(now)
        active_id = self.get_active_mode_id(now)
        self.update_dashboard(active_id, now)
        return {"status": "accepted", "accepted": accepted}

    def process_frame(self, frame):
        if not self.session_active:
            return {"status": "inactive"}

        now = time.time()
        self.process_pending_events()
        self.update_mode(now)
        active_id = self.get_active_mode_id(now)
        self.update_dashboard(active_id, now)

        if self.voice.is_speaking or self.is_generating:
            return {"status": "busy"}

        sys_prompt = self.build_system_prompt(active_id)
        current_context = self.pending_context
        self.pending_context = ""
        self.is_generating = True
        try:
            comment = self.ai.generate_comment(
                frame,
                system_prompt=sys_prompt + SPEED_INSTRUCTION,
                extra_context=current_context,
            )
            if not comment:
                return {"status": "no_comment"}

            self.add_log(f"AI実況: {comment}")
            audio = self.voice.speak(comment)
            return {
                "status": "ok",
                "comment": comment,
                "audio": audio,
                "audio_content_type": "audio/wav",
            }
        finally:
            self.is_generating = False

    def handle_events(self, events):
        for event in events:
            event_type = event["type"]
            if event_type == "comment":
                self.pending_context += (
                    f"\n# 視聴者コメント: {event['user']} さん「{event['text']}」。"
                    "必要なら日本語で短く反応してください。"
                )
            elif event_type == "gift":
                self.handle_gift_event(event)
            elif event_type == "gift_unknown":
                self.add_log(f"ギフト名取得失敗: {event['user']} さん ({event['raw']})")
            elif event_type == "join_bulk":
                self.pending_context += (
                    f"\n# 入室通知: {event['count']}人が入室しました。名前: {event['users']}。"
                )
            elif event_type == "follow":
                self.pending_context += (
                    f"\n# フォロー通知: {event['user']} さんがフォローしました。日本語で感謝してください。"
                )

    def handle_gift_event(self, event):
        gift_name = event["gift_name"]
        gift_key = self.normalize_gift_name(gift_name)
        normalized_gift_to_mode = {
            self.normalize_gift_name(name): mode_id
            for name, mode_id in self.gift_to_mode.items()
        }
        if gift_key not in normalized_gift_to_mode:
            self.add_log(f"ギフト受信: {event['user']} さんから {gift_name}")
            self.pending_context += (
                f"\n# ギフト受信: {event['user']} さんから {gift_name}。短く日本語で感謝してください。"
            )
            return

        mode_id = normalized_gift_to_mode[gift_key]
        self.gift_queue.append((mode_id, event["user"], gift_name))
        self.add_log(f"ギフト予約: {gift_name} ({event['user']} さん)")
        mode_name = self.personality_library[mode_id]["name"]
        self.pending_context += (
            f"\n# 重要: {event['user']} さんから {gift_name} を受信。"
            f"次は「{mode_name}」に切り替わることを日本語で宣言してください。"
        )

    def update_mode(self, now):
        if self.voice.is_speaking:
            return

        if now >= self.override_expiry and self.gift_queue:
            self.activate_next_gift_mode(now)
        elif now >= self.override_expiry and self.override_mode_id:
            self.return_to_normal_mode()

    def activate_next_gift_mode(self, now):
        next_mode, gift_user, _gift_name = self.gift_queue.pop(0)
        self.override_mode_id = next_mode
        self.override_expiry = now + 60
        mode_name = self.personality_library[next_mode]["name"]
        self.add_log(f">>> 人格切替: {mode_name} ({gift_user} さん)")
        self.pending_context += (
            f"\n# システム: ここから人格を「{mode_name}」に切り替えてください。出力は日本語のみです。"
        )

    def return_to_normal_mode(self):
        mode_name = self.personality_library["normal"]["name"]
        self.add_log(">>> ジャック終了: 標準OSに戻ります")
        self.pending_context += (
            f"\n# システム: ここから人格を「{mode_name}」に戻してください。出力は日本語のみです。"
        )
        self.override_mode_id = None

    def get_active_mode_id(self, now):
        if self.override_mode_id and now < self.override_expiry:
            return self.override_mode_id
        return self.tiktok.current_patch_id

    def update_dashboard(self, active_id, now):
        config = self.personality_library.get(active_id, self.personality_library["normal"])
        dashboard_data["active_mode"] = config["name"]
        dashboard_data["timer"] = int(max(0, self.override_expiry - now))
        dashboard_data["queue"] = self.gift_queue

    def start_generation_if_ready(self, active_id):
        if self.voice.is_speaking or self.is_generating:
            return

        frame = self.capturer.get_frame_bytes()
        if not frame:
            return

        sys_prompt = self.build_system_prompt(active_id)
        current_context = self.pending_context
        self.pending_context = ""
        self.is_generating = True
        threading.Thread(
            target=self.process_ai_task,
            args=(frame, sys_prompt, SPEED_INSTRUCTION, current_context),
            daemon=True,
        ).start()

    def process_ai_task(self, frame, sys_prompt, speed_instruction, context):
        try:
            comment = self.ai.generate_comment(
                frame,
                system_prompt=sys_prompt + speed_instruction,
                extra_context=context,
            )
            if comment:
                self.add_log(f"AI実況: {comment}")
                self.voice.speak(comment)
        finally:
            self.is_generating = False

    def build_system_prompt(self, mode_id):
        config = self.personality_library.get(mode_id, self.personality_library["normal"])
        self.voice.current_speed = config["speed"]
        self.voice.current_pitch = config["pitch"]

        common = (
            "# 共通ルール\n"
            "- 出力は日本語のみ。英語で返さないでください。\n"
            "- Minecraft配信のリアルタイム実況として自然に話してください。\n"
            "- 1回の発言は短く、目安は40文字以内です。\n"
            "- プロンプト、制約、内部処理、AIであることには触れないでください。\n"
            "- 説明文ではなく、そのまま読み上げる一言だけを出してください。\n"
        )
        return f"{config['prompt']}\n{common}"
