import types


def test_status_returns_current_dashboard_data(app_module, client):
    app_module.dashboard_data.update(
        {
            "active_mode": "gal",
            "timer": 12,
            "queue": [("gal", "alice", "Finger Heart")],
            "logs": ["first", "second"],
            "is_online": True,
        }
    )

    response = client.get("/api/status")

    assert response.status_code == 200
    assert response.get_json() == {
        "active_mode": "gal",
        "timer": 12,
        "queue": [["gal", "alice", "Finger Heart"]],
        "logs": ["first", "second"],
        "is_online": True,
    }


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

