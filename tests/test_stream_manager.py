import time
import types


class FakeVoice:
    def __init__(self):
        self.is_speaking = False
        self.current_speed = None
        self.current_pitch = None
        self.spoken = []
        self.stop_count = 0

    def stop(self):
        self.stop_count += 1

    def speak(self, text):
        self.spoken.append(text)


class FakeStateStore:
    def __init__(self, state=None):
        self.state = state
        self.saved = []

    def load(self):
        return self.state

    def save(self, state):
        self.state = state
        self.saved.append(state)


def make_manager(app_module):
    voice = FakeVoice()
    manager = app_module.StreamManager(
        capturer=types.SimpleNamespace(get_frame_bytes=lambda: None),
        ai=types.SimpleNamespace(generate_comment=lambda *_args, **_kwargs: None),
        voice=voice,
        tiktok=types.SimpleNamespace(current_patch_id="normal"),
    )
    return manager, voice


def make_manager_with_store(app_module, store):
    voice = FakeVoice()
    manager = app_module.StreamManager(
        capturer=types.SimpleNamespace(get_frame_bytes=lambda: None),
        ai=types.SimpleNamespace(generate_comment=lambda *_args, **_kwargs: None),
        voice=voice,
        tiktok=types.SimpleNamespace(current_patch_id="normal"),
        state_store=store,
    )
    return manager, voice


def test_add_log_appends_timestamped_entries_and_keeps_latest_50(app_module):
    manager, _voice = make_manager(app_module)

    for index in range(55):
        manager.add_log(f"message-{index}")

    assert len(app_module.dashboard_data["logs"]) == 50
    assert "message-0" not in app_module.dashboard_data["logs"][0]
    assert app_module.dashboard_data["logs"][0].endswith("message-5")
    assert app_module.dashboard_data["logs"][-1].endswith("message-54")


def test_session_logs_are_japanese(app_module):
    manager, _voice = make_manager(app_module)
    manager.start_tiktok_listener = lambda: None
    manager.start_event_loop = lambda: None

    assert manager.start_session() == {"status": "started"}
    assert app_module.dashboard_data["logs"][-1].endswith("配信セッション開始")

    assert manager.stop_session() == {"status": "stopped"}
    assert app_module.dashboard_data["logs"][-1].endswith("配信セッション停止")


def test_start_session_starts_event_loop(app_module):
    manager, _voice = make_manager(app_module)
    called = {}
    manager.start_tiktok_listener = lambda: None
    manager.start_event_loop = lambda: called.setdefault("event_loop", True)

    manager.start_session()

    assert called == {"event_loop": True}


def test_start_and_stop_session_are_persisted(app_module):
    store = FakeStateStore()
    manager, _voice = make_manager_with_store(app_module, store)
    manager.start_tiktok_listener = lambda: None
    manager.start_event_loop = lambda: None

    manager.start_session()
    assert store.saved[-1]["session_active"] is True

    manager.override_mode_id = "gal"
    manager.gift_queue.append(("metan", "viewer", "Ice Cream"))
    manager.stop_session()
    assert store.saved[-1]["session_active"] is False
    assert store.saved[-1]["gift_queue"] == []
    assert store.saved[-1]["override_mode_id"] is None


def test_stream_state_is_restored_on_new_manager(app_module, monkeypatch):
    state = {
        "session_active": True,
        "override_mode_id": "gal",
        "override_expiry": time.time() + 30,
        "gift_queue": [["metan", "viewer", "Ice Cream"]],
        "pending_context": "pending",
        "current_gen_id": 123,
    }
    store = FakeStateStore(state)
    monkeypatch.setattr(app_module.StreamManager, "start_event_loop", lambda self: None)

    manager, _voice = make_manager_with_store(app_module, store)

    assert manager.session_active is True
    assert manager.override_mode_id == "gal"
    assert manager.gift_queue == [("metan", "viewer", "Ice Cream")]
    assert manager.pending_context == "pending"
    assert manager.current_gen_id == 123
    assert app_module.dashboard_data["active_mode"] == manager.personality_library["gal"]["name"]
    assert app_module.dashboard_data["is_online"] is True


def test_gift_logs_are_japanese(app_module):
    manager, _voice = make_manager(app_module)

    manager.handle_gift_event({"user": "viewer", "gift_name": "Unknown Gift"})
    assert app_module.dashboard_data["logs"][-1].endswith(
        "ギフト受信: viewer さんから Unknown Gift"
    )

    manager.handle_gift_event({"user": "viewer", "gift_name": "Rose"})
    assert app_module.dashboard_data["logs"][-1].endswith(
        "ギフト予約: Rose (viewer さん)"
    )


def test_gift_matching_accepts_case_and_japanese_aliases(app_module):
    manager, _voice = make_manager(app_module)

    manager.handle_gift_event({"user": "viewer", "gift_name": "rose"})
    manager.handle_gift_event({"user": "viewer", "gift_name": "フィンガーハート"})

    assert manager.gift_queue == [
        ("zundamon", "viewer", "rose"),
        ("tsumugi", "viewer", "フィンガーハート"),
    ]


def test_duplicate_gift_event_is_not_queued_twice(app_module):
    manager, _voice = make_manager(app_module)

    manager.handle_gift_event({"user": "viewer", "gift_name": "Rose"})
    manager.handle_gift_event({"user": "viewer", "gift_name": "Rose"})

    assert manager.gift_queue == [("zundamon", "viewer", "Rose")]


def test_duplicate_gift_event_expires_after_window(app_module, monkeypatch):
    manager, _voice = make_manager(app_module)
    now = [100.0]
    monkeypatch.setattr(time, "time", lambda: now[0])

    manager.handle_gift_event({"user": "viewer", "gift_name": "Rose"})
    now[0] += manager.gift_dedupe_seconds + 0.1
    manager.handle_gift_event({"user": "viewer", "gift_name": "Rose"})

    assert manager.gift_queue == [
        ("zundamon", "viewer", "Rose"),
        ("zundamon", "viewer", "Rose"),
    ]


def test_process_frame_drains_gift_events_even_when_busy(app_module):
    manager, voice = make_manager(app_module)
    manager.session_active = True
    voice.is_speaking = True
    manager.tiktok = types.SimpleNamespace(
        current_patch_id="normal",
        fetch_events=lambda: [{"type": "gift", "user": "viewer", "gift_name": "Rose"}],
    )

    result = manager.process_frame(b"image")

    assert result == {"status": "busy"}
    assert manager.gift_queue == [("zundamon", "viewer", "Rose")]


def test_mode_switch_logs_are_japanese(app_module):
    manager, _voice = make_manager(app_module)
    manager.gift_queue.append(("tsumugi", "viewer", "Finger Heart"))

    manager.activate_next_gift_mode(time.time())
    assert app_module.dashboard_data["logs"][-1].endswith(
        ">>> 人格切替: 春日部つむぎ (viewer さん)"
    )

    manager.return_to_normal_mode()
    assert app_module.dashboard_data["logs"][-1].endswith(
        ">>> ジャック終了: 標準OSに戻ります"
    )


def test_trigger_manual_jack_sets_override_and_stops_current_voice(app_module):
    manager, voice = make_manager(app_module)

    with app_module.app.app_context():
        response = manager.trigger_manual_jack("gal")

    payload = response.get_json()
    assert payload == {"status": "success", "mode": manager.personality_library["gal"]["name"]}
    assert manager.override_mode_id == "gal"
    assert manager.override_expiry > 0
    assert manager.current_gen_id > 0
    assert voice.is_speaking is False
    assert voice.stop_count == 1
    assert manager.personality_library["gal"]["name"] in manager.pending_context
    assert app_module.dashboard_data["logs"][-1].endswith(
        f"強制介入: {manager.personality_library['gal']['name']}"
    )


def test_trigger_manual_jack_rejects_unknown_mode(app_module):
    manager, _voice = make_manager(app_module)

    with app_module.app.app_context():
        response, status_code = manager.trigger_manual_jack("missing")

    assert status_code == 400
    assert response.get_json() == {"status": "error"}


def test_build_system_prompt_applies_voice_settings_and_falls_back_to_normal(app_module):
    manager, voice = make_manager(app_module)

    prompt = manager.build_system_prompt("unknown-mode")

    normal = manager.personality_library["normal"]
    assert prompt.startswith(normal["prompt"])
    assert "# 共通ルール" in prompt
    assert "出力は日本語のみ" in prompt
    assert voice.current_speed == normal["speed"]
    assert voice.current_pitch == normal["pitch"]
    assert voice.current_speaker_id == normal["speaker_id"]


def test_speed_instruction_discourages_too_short_replies(app_module):
    from cloud_app.stream.manager import SPEED_INSTRUCTION

    assert "一息で読める自然な日本語" in SPEED_INSTRUCTION
    assert "短すぎる相づち" in SPEED_INSTRUCTION
    assert "同じ言い回しを続けない" in SPEED_INSTRUCTION


def test_refresh_dashboard_recalculates_timer(app_module):
    manager, _voice = make_manager(app_module)
    manager.override_mode_id = "tsumugi"
    manager.override_expiry = time.time() + 30

    manager.refresh_dashboard()

    assert app_module.dashboard_data["active_mode"] == manager.personality_library["tsumugi"]["name"]
    assert 0 < app_module.dashboard_data["timer"] <= 30


def test_refresh_dashboard_drains_pending_gift_events(app_module):
    manager, _voice = make_manager(app_module)
    manager.session_active = True
    manager.tiktok = types.SimpleNamespace(
        current_patch_id="normal",
        fetch_events=lambda: [{"type": "gift", "user": "viewer", "gift_name": "Rose"}],
    )

    manager.refresh_dashboard()

    assert app_module.dashboard_data["active_mode"] == manager.personality_library["zundamon"]["name"]
    assert app_module.dashboard_data["logs"][-1].endswith(
        ">>> 人格切替: ずんだもん (viewer さん)"
    )


def test_submit_events_accepts_external_events_and_updates_dashboard(app_module):
    manager, _voice = make_manager(app_module)
    manager.session_active = True

    result = manager.submit_events(
        [
            {"type": "gift", "user": "viewer", "gift_name": "Rose"},
            {"missing": "type"},
        ]
    )

    assert result == {"status": "accepted", "accepted": 1}
    assert manager.override_mode_id == "zundamon"
    assert app_module.dashboard_data["active_mode"] == manager.personality_library["zundamon"]["name"]


def test_submit_events_persists_gift_queue(app_module):
    store = FakeStateStore()
    manager, _voice = make_manager_with_store(app_module, store)
    manager.session_active = True

    manager.submit_events([{"type": "gift", "user": "viewer", "gift_name": "Rose"}])

    assert store.saved[-1]["override_mode_id"] == "zundamon"
    assert store.saved[-1]["session_active"] is True


def test_tiktok_status_event_is_logged(app_module):
    manager, _voice = make_manager(app_module)

    manager.handle_events(
        [
            {
                "type": "tiktok_status",
                "status": "error",
                "message": "TikTokLive接続エラー: boom",
            }
        ]
    )

    assert app_module.dashboard_data["logs"][-1].endswith(
        "TikTokLive [接続エラー] TikTokLive接続エラー: boom"
    )


def test_join_bulk_context_requests_varied_welcome(app_module):
    manager, _voice = make_manager(app_module)

    manager.handle_events(
        [{"type": "join_bulk", "count": 2, "users": "alice, bob"}]
    )

    assert "入室通知: 2人が入室しました。名前: alice, bob。" in manager.pending_context
    assert "みなさんいらっしゃい" in manager.pending_context
    assert "直近の発言と違う角度" in manager.pending_context
    assert "画面の状況に絡める" in manager.pending_context


def test_build_system_prompt_asks_to_avoid_repeated_phrasing(app_module):
    manager, _voice = make_manager(app_module)

    prompt = manager.build_system_prompt("normal")

    assert "目安は25〜70文字" in prompt
    assert "単語だけ、相づちだけ、挨拶だけで終わらせず" in prompt
    assert "Recent logs と同じ文や同じ言い回しを繰り返さず" in prompt
    assert "通知文をそのまま読まず" in prompt
    assert "入室が続く時も" in prompt
    assert "観察、感情、比喩、軽いツッコミ、期待、視聴者への呼びかけ" in prompt
    assert "画面に変化が少ない時" in prompt


def test_tick_events_advances_queued_mode_without_frame_or_status_request(app_module):
    manager, _voice = make_manager(app_module)
    manager.session_active = True
    manager.override_mode_id = "tsumugi"
    manager.override_expiry = time.time() - 1
    manager.gift_queue.append(("metan", "viewer", "Ice Cream"))

    manager.tick_events()

    assert manager.override_mode_id == "metan"
    assert app_module.dashboard_data["active_mode"] == manager.personality_library["metan"]["name"]
    assert app_module.dashboard_data["logs"][-1].endswith(
        ">>> 人格切替: 四国めたん (viewer さん)"
    )


def test_process_ai_task_speaks_generated_comment_and_resets_flag(app_module):
    manager, voice = make_manager(app_module)
    manager.is_generating = True
    calls = {}

    def generate_comment(frame, system_prompt, extra_context):
        calls["args"] = (frame, system_prompt, extra_context)
        return "generated comment"

    manager.ai = types.SimpleNamespace(generate_comment=generate_comment)

    manager.process_ai_task(b"image", "system", "speed", "context")

    assert calls["args"] == (b"image", "systemspeed", "context")
    assert voice.spoken == ["generated comment"]
    assert manager.is_generating is False
    assert app_module.dashboard_data["logs"][-1].endswith("generated comment")


def test_process_ai_task_resets_flag_when_generation_fails(app_module):
    manager, _voice = make_manager(app_module)
    manager.is_generating = True

    def generate_comment(*_args, **_kwargs):
        raise RuntimeError("boom")

    manager.ai = types.SimpleNamespace(generate_comment=generate_comment)

    try:
        manager.process_ai_task(b"image", "system", "speed", "context")
    except RuntimeError:
        pass

    assert manager.is_generating is False


def test_mode_switch_resets_output_and_updates_character_dashboard(app_module):
    manager, voice = make_manager(app_module)
    manager.is_generating = True
    manager.gift_queue.append(("tsumugi", "viewer", "Finger Heart"))

    manager.activate_next_gift_mode(time.time())
    manager.update_dashboard("tsumugi", time.time())

    assert manager.is_generating is False
    assert voice.stop_count == 1
    assert app_module.dashboard_data["active_mode_id"] == "tsumugi"
    assert app_module.dashboard_data["character_image"] == manager.personality_library["tsumugi"]["character_image"]
    assert app_module.dashboard_data["voicevox_speaker_id"] == manager.personality_library["tsumugi"]["speaker_id"]


def test_stale_generation_is_discarded_after_character_reset(app_module):
    manager, voice = make_manager(app_module)
    manager.current_gen_id = 1
    manager.is_generating = True
    manager.ai = types.SimpleNamespace(generate_comment=lambda *_args, **_kwargs: "old comment")

    manager.process_ai_task(b"image", "system", "speed", "context", generation_id=0)

    assert voice.spoken == []
    assert manager.is_generating is False


def test_character_prompt_supports_pokemon_actions_and_viewer_interaction(app_module):
    manager, _voice = make_manager(app_module)

    prompt = manager.build_system_prompt("zundamon")

    assert "ずんだもん" in prompt
    assert "ポケモンバトル" in prompt
    assert "作戦を助言する参謀" in prompt
    assert "配信者が手動で選べる次の一手" in prompt
    assert "直接操作している" in prompt
    assert "ポケモン参謀UI入力" in prompt
    assert "画面OCRや推測よりもそのテキストを優先" in prompt
    assert manager.personality_library["zundamon"]["action_style"] in prompt
    assert "TikTok Liveでは視聴者交流を優先" in prompt


def test_dashboard_exposes_active_character_name(app_module):
    manager, _voice = make_manager(app_module)

    manager.update_dashboard("zundamon", time.time())

    assert app_module.dashboard_data["active_character"] == "ずんだもん"


def test_format_pokemon_battle_context_includes_manual_ui_state(app_module):
    from cloud_app.stream.manager import format_pokemon_battle_context

    context = format_pokemon_battle_context(
        {
            "phase": "move selection",
            "own_active": "Pikachu 80%",
            "available_actions": "Thunderbolt / Quick Attack",
            "field": "Electric Terrain",
            "turn_history": ["T1: switch", "T2: Thunderbolt"],
        }
    )

    assert "# ポケモン参謀UI入力" in context
    assert "- フェーズ: move selection" in context
    assert "- 選択可能な行動: Thunderbolt / Quick Attack" in context
    assert "- フィールド情報: Electric Terrain" in context
    assert "- 直近ターン履歴: T1: switch / T2: Thunderbolt" in context


def test_process_frame_appends_pokemon_battle_context(app_module):
    manager, _voice = make_manager(app_module)
    manager.session_active = True
    app_module.dashboard_data["pokemon_battle_state"] = {
        "phase": "move selection",
        "own_active": "Pikachu 80%",
        "own_bench": "",
        "available_actions": "Thunderbolt",
        "opponent": "Charizard 60%",
        "field": "sun",
        "turn_history": ["T1: switch"],
        "notes": "攻めたい",
    }
    calls = {}

    def generate_comment(frame, system_prompt, extra_context):
        calls["extra_context"] = extra_context
        return "10まんボルトが良さそう"

    manager.ai = types.SimpleNamespace(generate_comment=generate_comment)

    result = manager.process_frame(b"image")

    assert result["status"] == "ok"
    assert "# ポケモン参謀UI入力" in calls["extra_context"]
    assert "Thunderbolt" in calls["extra_context"]
