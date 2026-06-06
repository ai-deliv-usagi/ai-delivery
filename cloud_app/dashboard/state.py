from datetime import datetime


dashboard_data = {
    "active_mode": "Initializing...",
    "timer": 0,
    "queue": [],
    "logs": [],
    "is_online": False,
}


def add_log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    log_entry = f"[{ts}] {msg}"
    dashboard_data["logs"].append(log_entry)
    if len(dashboard_data["logs"]) > 50:
        dashboard_data["logs"].pop(0)

