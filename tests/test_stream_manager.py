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


def make_manager(app_module):
    voice = FakeVoice()
    manager = app_module.StreamManager(
        capturer=types.SimpleNamespace(get_frame_bytes=lambda: None),
        ai=types.SimpleNamespace(generate_comment=lambda *_args, **_kwargs: None),
        voice=voice,
        tiktok=types.SimpleNamespace(current_patch_id="normal"),
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

    assert manager.start_session() == {"status": "started"}
    assert app_module.dashboard_data["logs"][-1].endswith("配信セッション開始")

    assert manager.stop_session() == {"status": "stopped"}
    assert app_module.dashboard_data["logs"][-1].endswith("配信セッション停止")


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
        ("nechinechi", "viewer", "rose"),
        ("gal", "viewer", "フィンガーハート"),
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
    assert manager.gift_queue == [("nechinechi", "viewer", "Rose")]


def test_mode_switch_logs_are_japanese(app_module):
    manager, _voice = make_manager(app_module)
    manager.gift_queue.append(("gal", "viewer", "Finger Heart"))

    manager.activate_next_gift_mode(time.time())
    assert app_module.dashboard_data["logs"][-1].endswith(
        ">>> 人格切替: ギャルOS (viewer さん)"
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
