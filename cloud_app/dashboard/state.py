from datetime import datetime, timedelta, timezone


JST = timezone(timedelta(hours=9))


dashboard_data = {
    "active_mode": "Initializing...",
    "active_mode_id": "normal",
    "active_character": "",
    "character_image": "",
    "voicevox_speaker_id": None,
    "timer": 0,
    "queue": [],
    "logs": [],
    "is_online": False,
    "pokemon_battle_state": {
        "phase": "",
        "own_active": "",
        "own_bench": "",
        "available_actions": "",
        "opponent": "",
        "field": "",
        "turn_history": [],
        "notes": "",
    },
}


def add_log(msg):
    ts = datetime.now(JST).strftime("%H:%M:%S")
    log_entry = f"[{ts}] {msg}"
    dashboard_data["logs"].append(log_entry)
    if len(dashboard_data["logs"]) > 50:
        dashboard_data["logs"].pop(0)
