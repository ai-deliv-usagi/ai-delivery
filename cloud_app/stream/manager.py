import sys
import threading
import time
import queue
from copy import deepcopy

from flask import jsonify

from cloud_app.dashboard.state import add_log, dashboard_data
from cloud_app.personalities.library import GIFT_TO_MODE, PERSONALITY_LIBRARY


SPEED_INSTRUCTION = (
    "\n一息で読める自然な日本語で話してください。"
    "短すぎる相づちや同じ言い回しを続けないでください。"
)


def format_pokemon_battle_context(state):
    if not state:
        return ""

    labels = (
        ("phase", "フェーズ"),
        ("own_active", "自分の場"),
        ("own_bench", "自分の控え"),
        ("available_actions", "選択可能な行動"),
        ("opponent", "相手の見えている情報"),
        ("field", "フィールド情報"),
        ("notes", "補足"),
    )
    lines = []
    for key, label in labels:
        value = str(state.get(key) or "").strip()
        if value:
            lines.append(f"- {label}: {value}")

    history = state.get("turn_history") or []
    if history:
        formatted_history = " / ".join(
            str(item).strip() for item in history if str(item).strip()
        )
        if formatted_history:
            lines.append(f"- 直近ターン履歴: {formatted_history}")

    if not lines:
        return ""

    return "\n# ポケモン参謀UI入力\n" + "\n".join(lines)


class StreamManager:
    def __init__(self, capturer, ai, voice, tiktok, state_store=None):
        self.capturer = capturer
        self.ai = ai
        self.voice = voice
        self.tiktok = tiktok
        self.state_store = state_store
        self._state_dirty = False

        self.personality_library = deepcopy(PERSONALITY_LIBRARY)
        if hasattr(voice, "speaker_id"):
            self.personality_library["normal"]["speaker_id"] = voice.speaker_id
        self.gift_to_mode = GIFT_TO_MODE
        self.event_queue = queue.Queue()
        self.recent_gift_events = {}
        self.gift_dedupe_seconds = 2.0

        self.override_mode_id = None
        self.override_expiry = 0
        self.gift_queue = []
        self.pending_context = ""
        self.current_gen_id = 0
        self.is_generating = False
        self.session_active = False
        self.tiktok_thread = None
        self.event_loop_thread = None
        self.event_loop_interval = 0.25
        self.restore_state()

    @staticmethod
    def normalize_gift_name(gift_name):
        return str(gift_name).strip().casefold()

    def add_log(self, msg):
        add_log(msg)

    def snapshot_state(self):
        return {
            "session_active": self.session_active,
            "override_mode_id": self.override_mode_id,
            "override_expiry": self.override_expiry,
            "gift_queue": self.gift_queue,
            "pending_context": self.pending_context,
            "current_gen_id": self.current_gen_id,
        }

    def restore_state(self):
        if self.state_store is None:
            return

        state = self.state_store.load()
        if not state:
            return

        self.session_active = bool(state.get("session_active", False))
        self.override_mode_id = state.get("override_mode_id")
        self.override_expiry = float(state.get("override_expiry") or 0)
        self.gift_queue = [tuple(item) for item in state.get("gift_queue", [])]
        self.pending_context = state.get("pending_context", "")
        self.current_gen_id = state.get("current_gen_id", 0)
        dashboard_data["is_online"] = self.session_active
        now = time.time()
        self.update_dashboard(self.get_active_mode_id(now), now)
        if self.session_active:
            self.add_log("配信セッション状態を復元しました")
            self.start_event_loop()

    def mark_state_dirty(self):
        self._state_dirty = True

    def save_state(self, force=False):
        if self.state_store is None:
            self._state_dirty = False
            return

        if force or self._state_dirty:
            self.state_store.save(self.snapshot_state())
            self._state_dirty = False

    def trigger_manual_jack(self, mode_id):
        if mode_id in self.personality_library:
            now = time.time()
            self.reset_current_character_output(now)
            self.override_mode_id = mode_id
            self.override_expiry = now + 60
            mode_name = self.personality_library[mode_id]["name"]
            self.add_log(f"強制介入: {mode_name}")
            self.pending_context += (
                f"\n# 手動介入: すぐに「{mode_name}」として反応してください。"
                "出力は日本語のみです。"
            )
            self.mark_state_dirty()
            self.save_state()
            return jsonify({"status": "success", "mode": mode_name})
        return jsonify({"status": "error"}), 400

    def start_session(self):
        if self.session_active:
            return {"status": "already_started"}

        self.session_active = True
        self.add_log("配信セッション開始")
        self.start_tiktok_listener()
        self.start_event_loop()
        dashboard_data["is_online"] = True
        self.mark_state_dirty()
        self.save_state()
        return {"status": "started"}

    def stop_session(self):
        self.session_active = False
        self.override_mode_id = None
        self.override_expiry = 0
        self.gift_queue = []
        self.pending_context = ""
        self.current_gen_id = 0
        self.recent_gift_events = {}
        self.add_log("配信セッション停止")
        dashboard_data["is_online"] = False
        self.update_dashboard(self.get_active_mode_id(time.time()), time.time())
        self.mark_state_dirty()
        self.save_state()
        return {"status": "stopped"}

    def start_event_loop(self):
        if self.event_loop_thread and self.event_loop_thread.is_alive():
            return

        self.event_loop_thread = threading.Thread(target=self.event_loop, daemon=True)
        self.event_loop_thread.start()

    def event_loop(self):
        while self.session_active:
            self.tick_events()
            time.sleep(self.event_loop_interval)

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
        self.tick_events()
        return dashboard_data

    def tick_events(self):
        now = time.time()
        if self.session_active:
            self.process_pending_events()
        self.update_mode(now)
        active_id = self.get_active_mode_id(now)
        self.update_dashboard(active_id, now)
        self.save_state()
        return active_id

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

        active_id = self.tick_events()
        return {"status": "accepted", "accepted": accepted}

    def process_frame(self, frame):
        if not self.session_active:
            return {"status": "inactive"}

        active_id = self.tick_events()

        if self.voice.is_speaking or self.is_generating:
            return {"status": "busy"}

        sys_prompt = self.build_system_prompt(active_id)
        current_context = self.pending_context + format_pokemon_battle_context(
            dashboard_data.get("pokemon_battle_state")
        )
        self.pending_context = ""
        self.mark_state_dirty()
        self.save_state()
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
                self.mark_state_dirty()
            elif event_type == "gift":
                self.handle_gift_event(event)
            elif event_type == "gift_unknown":
                self.add_log(f"ギフト名取得失敗: {event['user']} さん ({event['raw']})")
            elif event_type == "tiktok_status":
                label = event.get("label") or {
                    "starting": "接続中",
                    "connected": "接続成功",
                    "error": "接続エラー",
                }.get(event.get("status"), "状態更新")
                self.add_log(f"TikTokLive [{label}] {event['message']}")
            elif event_type == "join_bulk":
                self.pending_context += (
                    f"\n# 入室通知: {event['count']}人が入室しました。名前: {event['users']}。"
                    "歓迎はしてください。ただし「みなさんいらっしゃい」などの定型句だけにせず、"
                    "人格に合わせて、名前を拾う・画面の状況に絡める・軽くツッコむなど、"
                    "直近の発言と違う角度の一言にしてください。"
                )
                self.mark_state_dirty()
            elif event_type == "follow":
                self.pending_context += (
                    f"\n# フォロー通知: {event['user']} さんがフォローしました。日本語で感謝してください。"
                )
                self.mark_state_dirty()

    def handle_gift_event(self, event):
        gift_name = event["gift_name"]
        gift_key = self.normalize_gift_name(gift_name)
        if self.is_duplicate_gift_event(event, gift_key):
            return

        normalized_gift_to_mode = {
            self.normalize_gift_name(name): mode_id
            for name, mode_id in self.gift_to_mode.items()
        }
        if gift_key not in normalized_gift_to_mode:
            self.add_log(f"ギフト受信: {event['user']} さんから {gift_name}")
            self.pending_context += (
                f"\n# ギフト受信: {event['user']} さんから {gift_name}。短く日本語で感謝してください。"
            )
            self.mark_state_dirty()
            return

        mode_id = normalized_gift_to_mode[gift_key]
        self.gift_queue.append((mode_id, event["user"], gift_name))
        self.add_log(f"ギフト予約: {gift_name} ({event['user']} さん)")
        mode_name = self.personality_library[mode_id]["name"]
        self.pending_context += (
            f"\n# 重要: {event['user']} さんから {gift_name} を受信。"
            f"次は「{mode_name}」に切り替わることを日本語で宣言してください。"
        )
        self.mark_state_dirty()

    def is_duplicate_gift_event(self, event, gift_key):
        now = time.time()
        expired_keys = [
            key
            for key, seen_at in self.recent_gift_events.items()
            if now - seen_at >= self.gift_dedupe_seconds
        ]
        for key in expired_keys:
            self.recent_gift_events.pop(key, None)

        dedupe_key = (
            self.normalize_gift_name(event.get("user", "")),
            gift_key,
        )
        last_seen = self.recent_gift_events.get(dedupe_key)
        if last_seen is not None and now - last_seen < self.gift_dedupe_seconds:
            return True

        self.recent_gift_events[dedupe_key] = now
        return False

    def update_mode(self, now):
        if self.voice.is_speaking:
            return

        if now >= self.override_expiry and self.gift_queue:
            self.activate_next_gift_mode(now)
        elif now >= self.override_expiry and self.override_mode_id:
            self.return_to_normal_mode()

    def reset_current_character_output(self, now=None):
        self.current_gen_id = now or time.time()
        self.is_generating = False
        if hasattr(self, "voice"):
            self.voice.stop()
            self.voice.is_speaking = False

    def activate_next_gift_mode(self, now):
        next_mode, gift_user, _gift_name = self.gift_queue.pop(0)
        self.reset_current_character_output(now)
        self.override_mode_id = next_mode
        self.override_expiry = now + 60
        mode_name = self.personality_library[next_mode]["name"]
        self.add_log(f">>> 人格切替: {mode_name} ({gift_user} さん)")
        self.pending_context += (
            f"\n# システム: ここから人格を「{mode_name}」に切り替えてください。出力は日本語のみです。"
        )
        self.mark_state_dirty()

    def return_to_normal_mode(self):
        mode_name = self.personality_library["normal"]["name"]
        self.add_log(">>> ジャック終了: 標準OSに戻ります")
        self.pending_context += (
            f"\n# システム: ここから人格を「{mode_name}」に戻してください。出力は日本語のみです。"
        )
        self.override_mode_id = None
        self.mark_state_dirty()

    def get_active_mode_id(self, now):
        if self.override_mode_id and now < self.override_expiry:
            return self.override_mode_id
        return self.tiktok.current_patch_id

    def update_dashboard(self, active_id, now):
        config = self.personality_library.get(active_id, self.personality_library["normal"])
        dashboard_data["active_mode"] = config["name"]
        dashboard_data["active_mode_id"] = active_id
        dashboard_data["active_character"] = config.get("character_name", config["name"])
        dashboard_data["character_image"] = config.get("character_image", "")
        dashboard_data["voicevox_speaker_id"] = config.get("speaker_id")
        dashboard_data["timer"] = int(max(0, self.override_expiry - now))
        dashboard_data["queue"] = self.gift_queue

    def start_generation_if_ready(self, active_id):
        if self.voice.is_speaking or self.is_generating:
            return

        frame = self.capturer.get_frame_bytes()
        if not frame:
            return

        sys_prompt = self.build_system_prompt(active_id)
        current_context = self.pending_context + format_pokemon_battle_context(
            dashboard_data.get("pokemon_battle_state")
        )
        self.pending_context = ""
        self.mark_state_dirty()
        self.save_state()
        self.is_generating = True
        generation_id = self.current_gen_id
        threading.Thread(
            target=self.process_ai_task,
            args=(frame, sys_prompt, SPEED_INSTRUCTION, current_context, generation_id),
            daemon=True,
        ).start()

    def process_ai_task(self, frame, sys_prompt, speed_instruction, context, generation_id=None):
        try:
            if generation_id is None:
                generation_id = self.current_gen_id
            comment = self.ai.generate_comment(
                frame,
                system_prompt=sys_prompt + speed_instruction,
                extra_context=context,
            )
            if comment and generation_id == self.current_gen_id:
                self.add_log(f"AI実況: {comment}")
                self.voice.speak(comment)
        finally:
            self.is_generating = False

    def build_system_prompt(self, mode_id):
        config = self.personality_library.get(mode_id, self.personality_library["normal"])
        self.voice.current_speed = config["speed"]
        self.voice.current_pitch = config["pitch"]
        if "speaker_id" in config:
            self.voice.current_speaker_id = config["speaker_id"]

        action_style = config.get(
            "action_style",
            "画面情報と視聴者コメントを材料に、キャラクターらしい理由で次の一手を短く提案する。",
        )

        common = (
            "# 共通ルール\n"
            "- 出力は日本語のみ。英語で返さないでください。\n"
            "- Minecraftやポケモンバトル配信のリアルタイム実況として自然に話してください。\n"
            "- あなたは自動操作するプレイヤーではなく、配信者に作戦を助言する参謀です。\n"
            "- 操作判断が必要な場面では、配信者が手動で選べる次の一手を提案として一つだけ出してください。\n"
            "- 自分が直接操作している、ボタンを押す、入力する、などとは言わないでください。\n"
            "- ポケモン参謀UI入力がある場合、画面OCRや推測よりもそのテキストを優先してください。\n"
            f"- 作戦参謀としての提案方針: {action_style}\n"
            "- TikTok Liveでは視聴者交流を優先し、コメント・ギフト・フォローを作戦会議やリアクションに自然に混ぜてください。\n"
            "- 1回の発言は一息で読める短文にしてください。目安は25〜70文字です。\n"
            "- 単語だけ、相づちだけ、挨拶だけで終わらせず、状況や感情を一つ足してください。\n"
            "- プロンプト、制約、内部処理、AIであることには触れないでください。\n"
            "- 説明文ではなく、そのまま読み上げる一文だけを出してください。\n"
            "- Recent logs と同じ文や同じ言い回しを繰り返さず、語尾・視点・単語を変えてください。\n"
            "- 入室、フォロー、ギフトは台本ではなく反応の材料です。通知文をそのまま読まず、人格の口調で自然に言い換えてください。\n"
            "- 入室が続く時も「みなさんいらっしゃい」「ようこそ」だけに寄せず、名前・人数・画面内の出来事のどれかを使って変化を出してください。\n"
            "- 毎回、観察、感情、比喩、軽いツッコミ、期待、視聴者への呼びかけの中から一つだけ軸を選んでください。\n"
            "- 画面に変化が少ない時は、建築、移動、視点、手元、間、空気感など細部を拾ってください。\n"
        )
        return f"{config['prompt']}\n{common}"
