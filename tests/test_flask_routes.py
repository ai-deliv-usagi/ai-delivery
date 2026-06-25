import io
import types


def test_status_returns_current_dashboard_data(app_module, client):
    app_module.dashboard_data.update(
        {
            "active_mode": "gal",
            "active_mode_id": "gal",
            "active_character": "春日部つむぎ",
            "character_image": "/static/characters/tsumugi.png",
            "voicevox_speaker_id": 8,
            "timer": 12,
            "queue": [("gal", "alice", "Finger Heart")],
            "logs": ["first", "second"],
            "is_online": True,
            "pokemon_battle_state": {
                "phase": "move selection",
                "own_active": "Pikachu 80%",
                "own_bench": "",
                "available_actions": "Thunderbolt",
                "opponent": "Charizard 60%",
                "field": "sun",
                "turn_history": ["T1: switch"],
                "notes": "",
            },
        }
    )

    response = client.get("/api/status")

    assert response.status_code == 200
    assert response.get_json() == {
        "active_mode": "gal",
        "active_mode_id": "gal",
        "active_character": "春日部つむぎ",
        "character_image": "/static/characters/tsumugi.png",
        "voicevox_speaker_id": 8,
        "timer": 12,
        "queue": [["gal", "alice", "Finger Heart"]],
        "logs": ["first", "second"],
        "is_online": True,
        "pokemon_battle_state": {
            "phase": "move selection",
            "own_active": "Pikachu 80%",
            "own_bench": "",
            "available_actions": "Thunderbolt",
            "opponent": "Charizard 60%",
            "field": "sun",
            "turn_history": ["T1: switch"],
            "notes": "",
        },
    }


def test_status_refreshes_dashboard_when_stream_manager_exists(app_module, client):
    called = {}

    def refresh_dashboard():
        called["refresh"] = True
        app_module.dashboard_data["timer"] = 7

    app_module.stream_manager = types.SimpleNamespace(refresh_dashboard=refresh_dashboard)

    response = client.get("/api/status")

    assert response.status_code == 200
    assert response.get_json()["timer"] == 7
    assert called == {"refresh": True}


def test_force_jack_returns_500_when_stream_manager_is_missing(client):
    response = client.get("/api/force_jack/gal")

    assert response.status_code == 500
    assert response.get_json() == {"status": "error"}


def test_force_jack_delegates_to_stream_manager(app_module, client):
    called = {}

    def trigger_manual_jack(mode_id):
        called["mode_id"] = mode_id
        return app_module.jsonify({"status": "success", "mode": mode_id})

    app_module.stream_manager = types.SimpleNamespace(trigger_manual_jack=trigger_manual_jack)

    response = client.get("/api/force_jack/samurai")

    assert response.status_code == 200
    assert response.get_json() == {"status": "success", "mode": "samurai"}
    assert called == {"mode_id": "samurai"}


def test_controller_renders_personality_buttons(app_module, client):
    app_module.stream_manager = types.SimpleNamespace(
        personality_library={
            "normal": {"name": "Normal OS"},
            "gal": {"name": "Gal OS"},
        }
    )

    response = client.get("/controller")

    assert response.status_code == 200
    assert "Normal OS" in response.get_data(as_text=True)
    assert "Gal OS" in response.get_data(as_text=True)


def test_session_start_delegates_to_stream_manager(app_module, client):
    app_module.stream_manager = types.SimpleNamespace(start_session=lambda: {"status": "started"})

    response = client.post("/api/session/start")

    assert response.status_code == 200
    assert response.get_json() == {"status": "started"}


def test_session_stop_delegates_to_stream_manager(app_module, client):
    app_module.stream_manager = types.SimpleNamespace(stop_session=lambda: {"status": "stopped"})

    response = client.post("/api/session/stop")

    assert response.status_code == 200
    assert response.get_json() == {"status": "stopped"}


def test_receive_frame_returns_audio_base64_when_generated(app_module, client):
    app_module.stream_manager = types.SimpleNamespace(
        process_frame=lambda frame: {
            "status": "ok",
            "comment": "hello",
            "audio": b"wav-bytes",
            "audio_content_type": "audio/wav",
        }
    )

    response = client.post(
        "/api/frames",
        data={"frame": (io.BytesIO(b"frame"), "frame.jpg")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "status": "ok",
        "comment": "hello",
        "audio_base64": "d2F2LWJ5dGVz",
        "audio_content_type": "audio/wav",
        "audio_encoding": "base64",
    }


def test_receive_events_requires_event_list(client):
    response = client.post("/api/events", json={"events": "gift"})

    assert response.status_code == 400
    assert response.get_json() == {"status": "error", "message": "events must be a list"}


def test_receive_events_delegates_to_stream_manager(app_module, client):
    called = {}

    def submit_events(events):
        called["events"] = events
        return {"status": "accepted", "accepted": len(events)}

    app_module.stream_manager = types.SimpleNamespace(submit_events=submit_events)

    response = client.post(
        "/api/events",
        json={"events": [{"type": "gift", "user": "alice", "gift_name": "Rose"}]},
    )

    assert response.status_code == 200
    assert response.get_json() == {"status": "accepted", "accepted": 1}
    assert called == {
        "events": [{"type": "gift", "user": "alice", "gift_name": "Rose"}]
    }


def test_character_overlay_renders_browser_source(app_module, client):
    app_module.stream_manager = types.SimpleNamespace(refresh_dashboard=lambda: None)

    response = client.get("/character-overlay")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "/api/status" in html
    assert "character_image" in html
    assert "active_character" in html


def test_pokemon_state_api_saves_structured_text(app_module, client):
    response = client.post(
        "/api/pokemon/state",
        json={
            "phase": " move selection ",
            "own_active": "Pikachu 80% paralyzed",
            "available_actions": "Thunderbolt / Quick Attack",
            "field": "Electric Terrain",
            "turn_history": "T1: opponent switched\nT2: Pikachu used Thunderbolt",
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "saved"
    assert payload["pokemon_battle_state"]["phase"] == "move selection"
    assert payload["pokemon_battle_state"]["turn_history"] == [
        "T1: opponent switched",
        "T2: Pikachu used Thunderbolt",
    ]

    response = client.get("/api/pokemon/state")

    assert response.status_code == 200
    assert response.get_json()["available_actions"] == "Thunderbolt / Quick Attack"


def test_pokemon_control_renders_manual_state_panel(client):
    response = client.get("/pokemon-control")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "/api/pokemon/state" in html
    assert "turn_history" in html
    assert "available_actions" in html
