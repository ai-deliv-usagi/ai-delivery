import sys
import threading
import time
import queue

from flask import jsonify

from cloud_app.dashboard.state import add_log, dashboard_data
from cloud_app.personalities.library import GIFT_TO_MODE, PERSONALITY_LIBRARY


SPEED_INSTRUCTION = (
    "\n一息で読める自然な日本語で話してください。"
    "短すぎる相づちや同じ言い回しを続けないでください。"
)

GIFT_TIER_LABELS = {
    "light": "ライト",
    "middle": "ミドル",
    "big": "ビッグ",
    "legend": "レジェンド",
}

GIFT_TIER_STYLES = {
    "light": "配信のテンポを止めず、親しみのある軽快な反応にする",
    "middle": "普段より少し大きく反応し、送り主が参加した実感を出す",
    "big": "明確な特別感を出し、周囲の視聴者も楽しめる反応にする",
    "legend": "配信の主役級イベントとして扱い、短い二文まで使って場全体を盛り上げる",
}

GIFT_ACTIONS = {
    "light": (
        "ギフト名をMinecraft内のアイテムや出来事に見立てて一言添える",
        "現在の画面で目につくものとギフトを結びつけて軽くツッコむ",
        "送り主へ、その場限りの短く親しみやすい称号を授ける",
    ),
    "middle": (
        "送り主を主役にして、次の展開を短く予言する",
        "配信者へ安全で軽いMinecraftミッションを一つ提案する",
        "ギフトを必殺技として命名し、発動したように実況する",
    ),
    "big": (
        "配信の物語が大きく動いた事件として、大げさに命名する",
        "視聴者全体がコメントで参加できる短い二択を呼びかける",
        "送り主へ特別な称号を授け、現在の画面と絡めて讃える",
    ),
    "legend": (
        "今日の配信史に残る伝説として事件名をつける",
        "送り主を今回のボスまたは英雄として登場させ、場を巻き込む",
        "視聴者全体に祝祭感のある掛け声やコメント参加を呼びかける",
    ),
}


class StreamManager:
    def __init__(
        self,
        capturer,
        ai,
        voice,
        tiktok,
        state_store=None,
        session_idle_timeout_seconds=180,
        jack_duration_seconds=120,
    ):
        self.capturer = capturer
        self.ai = ai
        self.voice = voice
        self.tiktok = tiktok
        self.state_store = state_store
        self._state_dirty = False

        self.personality_library = PERSONALITY_LIBRARY
        self.gift_to_mode = GIFT_TO_MODE
        self.event_queue = queue.Queue()
        self.recent_gift_events = {}
        self.gift_dedupe_seconds = 2.0
        self.gift_action_indexes = {tier: 0 for tier in GIFT_ACTIONS}
        self.gift_support_streaks = {}
        self.gift_support_streak_seconds = 60.0

        self.override_mode_id = None
        self.override_expiry = 0
        self.gift_queue = []
        self.pending_context = ""
        self.latest_viewer_context = ""
        self.current_gen_id = 0
        self.is_generating = False
        self.session_active = False
        self.tiktok_thread = None
        self.event_loop_thread = None
        self.event_loop_interval = 0.25
        self.session_idle_timeout_seconds = session_idle_timeout_seconds
        self.jack_duration_seconds = jack_duration_seconds
        self.last_activity_at = None
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
            "latest_viewer_context": self.latest_viewer_context,
            "current_gen_id": self.current_gen_id,
            "last_activity_at": self.last_activity_at,
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
        self.latest_viewer_context = state.get("latest_viewer_context", "")
        self.current_gen_id = state.get("current_gen_id", 0)
        self.last_activity_at = state.get("last_activity_at")
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

    def mark_activity(self, now=None):
        self.last_activity_at = now or time.time()
        self.mark_state_dirty()

    def get_idle_seconds(self, now=None):
        if not self.session_active or self.last_activity_at is None:
            return None
        return max(0, int((now or time.time()) - self.last_activity_at))

    def stop_if_idle(self, now=None):
        if not self.session_active:
            return False

        now = now or time.time()
        if self.last_activity_at is None:
            self.mark_activity(now)
            return False

        if now - self.last_activity_at < self.session_idle_timeout_seconds:
            return False

        self.stop_session(reason="idle_timeout")
        return True

    def trigger_manual_jack(self, mode_id):
        if mode_id in self.personality_library:
            now = time.time()
            self.current_gen_id = now
            if hasattr(self, "voice"):
                self.voice.stop()
            self.voice.is_speaking = False
            self.override_mode_id = mode_id
            self.override_expiry = now + self.jack_duration_seconds
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
        self.mark_activity()
        self.add_log("配信セッション開始")
        self.start_tiktok_listener()
        self.start_event_loop()
        dashboard_data["is_online"] = True
        self.mark_state_dirty()
        self.save_state()
        return {"status": "started"}

    def stop_session(self, reason=None):
        self.session_active = False
        self.is_generating = False
        if hasattr(self, "voice"):
            self.voice.stop()
            self.voice.is_speaking = False
        self.override_mode_id = None
        self.override_expiry = 0
        self.gift_queue = []
        self.pending_context = ""
        self.latest_viewer_context = ""
        self.current_gen_id = 0
        self.recent_gift_events = {}
        self.gift_action_indexes = {tier: 0 for tier in GIFT_ACTIONS}
        self.gift_support_streaks = {}
        self.last_activity_at = None
        self.add_log("配信セッション停止")
        if reason == "idle_timeout":
            self.add_log("Cloud Run idle timeout: no frames or TikTok events received; session stopped")
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
        if self.stop_if_idle(now):
            return None
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
            if self.stop_if_idle(now):
                active_id = self.get_active_mode_id(now)
                self.update_dashboard(active_id, now)
                self.save_state()
                return active_id
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

        if accepted:
            self.mark_activity()
        active_id = self.tick_events()
        return {"status": "accepted", "accepted": accepted}

    def process_frame(self, frame, playback_busy=False):
        if not self.session_active:
            return {"status": "inactive"}

        self.mark_activity()
        active_id = self.tick_events()

        if playback_busy or self.voice.is_speaking or self.is_generating:
            return {"status": "busy"}

        sys_prompt = self.build_system_prompt(active_id)
        current_context = self.build_generation_context()
        self.pending_context = ""
        self.latest_viewer_context = ""
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
                self.set_latest_viewer_context(
                    f"\n# 視聴者コメント: {event['user']} さん「{event['text']}」。"
                    "必要なら短く反応してください。"
                    "コメントが外国語なら、短い挨拶・感謝・リアクションは相手と同じ言語で返してよいです。"
                    "ただし説明や実況の本筋は日本語に戻してください。"
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
                self.set_latest_viewer_context(
                    f"\n# 入室通知: {event['count']}人が入室しました。名前: {event['users']}。"
                    "歓迎はしてください。ただし「みなさんいらっしゃい」などの定型句だけにせず、"
                    "人格に合わせて、名前を拾う・画面の状況に絡める・軽くツッコむなど、"
                    "直近の発言と違う角度の一言にしてください。"
                )
                self.mark_state_dirty()
            elif event_type == "follow":
                self.set_latest_viewer_context(
                    f"\n# フォロー通知: {event['user']} さんがフォローしました。日本語で感謝してください。"
                )
                self.mark_state_dirty()

    def set_latest_viewer_context(self, context):
        self.latest_viewer_context = context
        self.mark_state_dirty()

    def build_generation_context(self):
        return f"{self.pending_context}{self.latest_viewer_context}"

    @staticmethod
    def positive_int(value, default=None):
        try:
            number = int(value)
        except (TypeError, ValueError):
            return default
        return number if number > 0 else default

    def get_gift_metrics(self, event):
        repeat_count = self.positive_int(event.get("repeat_count"), default=1)
        diamond_count = self.positive_int(event.get("diamond_count"))
        total_diamonds = self.positive_int(event.get("total_diamonds"))
        if total_diamonds is None and diamond_count is not None:
            total_diamonds = diamond_count * repeat_count
        return repeat_count, diamond_count, total_diamonds

    @staticmethod
    def classify_gift_tier(total_diamonds, repeat_count):
        if total_diamonds is not None:
            if total_diamonds >= 1000:
                return "legend"
            if total_diamonds >= 100:
                return "big"
            if total_diamonds >= 10:
                return "middle"
            return "light"

        if repeat_count >= 100:
            return "legend"
        if repeat_count >= 20:
            return "big"
        if repeat_count >= 5:
            return "middle"
        return "light"

    def next_gift_action(self, tier):
        actions = GIFT_ACTIONS[tier]
        index = self.gift_action_indexes[tier]
        self.gift_action_indexes[tier] = (index + 1) % len(actions)
        return actions[index]

    def update_gift_support_streak(self, user):
        now = time.time()
        expired_users = [
            key
            for key, streak in self.gift_support_streaks.items()
            if now - streak["seen_at"] >= self.gift_support_streak_seconds
        ]
        for key in expired_users:
            self.gift_support_streaks.pop(key, None)

        user_key = str(user).strip().casefold()
        previous = self.gift_support_streaks.get(user_key)
        if previous and now - previous["seen_at"] < self.gift_support_streak_seconds:
            count = previous["count"] + 1
        else:
            count = 1
        self.gift_support_streaks[user_key] = {"count": count, "seen_at": now}
        return count

    def build_gift_reaction_context(self, event):
        repeat_count, _diamond_count, total_diamonds = self.get_gift_metrics(event)
        tier = self.classify_gift_tier(total_diamonds, repeat_count)
        tier_label = GIFT_TIER_LABELS[tier]
        action = self.next_gift_action(tier)
        support_streak = self.update_gift_support_streak(event["user"])
        value_text = (
            f"合計価値: {total_diamonds}ダイヤ。"
            if total_diamonds is not None
            else "合計価値は不明。"
        )
        streak_text = (
            f"この視聴者から60秒以内で{support_streak}回目のギフトです。"
            if support_streak > 1
            else ""
        )
        context = (
            "\n# 最優先: ギフトリアクション\n"
            f"送り主: {event['user']} さん。ギフト: {event['gift_name']}。"
            f"個数: {repeat_count}。{value_text}段階: {tier_label}。\n"
            f"{streak_text}"
            "必ず送り主の名前とギフト名を自然に含めて感謝し、お礼だけで終わらせないでください。\n"
            f"反応の強さ: {GIFT_TIER_STYLES[tier]}。\n"
            f"今回の追加演出: {action}。\n"
            "人格と現在のMinecraft画面に合わせて即興し、最近と同じ演出や文句は避けてください。"
            "追加の課金やギフトを要求・催促する表現は禁止です。"
        )
        return context, tier, tier_label, repeat_count, total_diamonds

    def handle_gift_event(self, event):
        gift_name = event["gift_name"]
        gift_key = self.normalize_gift_name(gift_name)
        if self.is_duplicate_gift_event(event, gift_key):
            return

        reaction = self.build_gift_reaction_context(event)
        context, _tier, tier_label, repeat_count, total_diamonds = reaction
        count_suffix = f" x{repeat_count}" if repeat_count > 1 else ""
        value_suffix = (
            f" / {total_diamonds}ダイヤ" if total_diamonds is not None else ""
        )

        normalized_gift_to_mode = {
            self.normalize_gift_name(name): mode_id
            for name, mode_id in self.gift_to_mode.items()
        }
        if gift_key not in normalized_gift_to_mode:
            self.add_log(
                f"ギフト受信 [{tier_label}]: {event['user']} さんから "
                f"{gift_name}{count_suffix}{value_suffix}"
            )
            self.pending_context += context
            self.mark_state_dirty()
            return

        mode_id = normalized_gift_to_mode[gift_key]
        self.gift_queue.append((mode_id, event["user"], gift_name))
        self.add_log(
            f"ギフト予約 [{tier_label}]: {gift_name}{count_suffix}{value_suffix} "
            f"({event['user']} さん)"
        )
        mode_name = self.personality_library[mode_id]["name"]
        self.pending_context += context + (
            f"\n# 固有演出: {event['user']} さんから {gift_name} を受信したため、"
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

    def activate_next_gift_mode(self, now):
        next_mode, gift_user, _gift_name = self.gift_queue.pop(0)
        self.override_mode_id = next_mode
        self.override_expiry = now + self.jack_duration_seconds
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
        dashboard_data["timer"] = int(max(0, self.override_expiry - now))
        dashboard_data["queue"] = self.gift_queue
        dashboard_data["idle_seconds"] = self.get_idle_seconds(now)
        dashboard_data["session_idle_timeout_seconds"] = self.session_idle_timeout_seconds

    def start_generation_if_ready(self, active_id):
        if self.voice.is_speaking or self.is_generating:
            return

        frame = self.capturer.get_frame_bytes()
        if not frame:
            return

        sys_prompt = self.build_system_prompt(active_id)
        current_context = self.build_generation_context()
        self.pending_context = ""
        self.latest_viewer_context = ""
        self.mark_state_dirty()
        self.save_state()
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
            "- 通常の実況は日本語で話してください。\n"
            "- 視聴者コメントが外国語の場合は、短い挨拶・感謝・リアクションだけ相手と同じ言語で返してよいです。\n"
            "- 外国語で返す時も一文だけにし、長い説明や実況の本筋は日本語に戻してください。\n"
            "- Minecraft配信のリアルタイム実況として自然に話してください。\n"
            "- 1回の発言は一息で読める短文にしてください。目安は25〜70文字です。\n"
            "- ビッグまたはレジェンドのギフト反応だけは、特別感を出すため100文字以内の短い二文まで許可します。\n"
            "- 単語だけ、相づちだけ、挨拶だけで終わらせず、状況や感情を一つ足してください。\n"
            "- プロンプト、制約、内部処理、AIであることには触れないでください。\n"
            "- 説明文ではなく、そのまま読み上げる発言だけを出してください。通常は一文にしてください。\n"
            "- Recent logs と同じ文や同じ言い回しを繰り返さず、語尾・視点・単語を変えてください。\n"
            "- 入室、フォロー、ギフトは台本ではなく反応の材料です。通知文をそのまま読まず、人格の口調で自然に言い換えてください。\n"
            "- ギフトには必ず感謝しますが、追加の課金やギフトを要求・催促してはいけません。\n"
            "- 入室が続く時も「みなさんいらっしゃい」「ようこそ」だけに寄せず、名前・人数・画面内の出来事のどれかを使って変化を出してください。\n"
            "- 毎回、観察、感情、比喩、軽いツッコミ、期待、視聴者への呼びかけの中から一つだけ軸を選んでください。\n"
            "- 画面に変化が少ない時は、建築、移動、視点、手元、間、空気感など細部を拾ってください。\n"
        )
        return f"{config['prompt']}\n{common}"
