from datetime import datetime, timedelta, timezone


JST = timezone(timedelta(hours=9))


dashboard_data = {
    "active_mode": "Initializing...",
    "timer": 0,
    "queue": [],
    "logs": [],
    "is_online": False,
    "idle_seconds": None,
    "session_idle_timeout_seconds": None,
}


def add_log(msg):
    ts = datetime.now(JST).strftime("%H:%M:%S")
    log_entry = f"[{ts}] {msg}"
    dashboard_data["logs"].append(log_entry)
    if len(dashboard_data["logs"]) > 50:
        dashboard_data["logs"].pop(0)
