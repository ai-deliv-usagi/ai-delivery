import base64

import requests


class CloudApiClient:
    def __init__(self, base_url):
        self.base_url = base_url.rstrip("/")

    def send_frame(self, frame_bytes, playback_busy=False):
        data = {}
        if playback_busy:
            data["playback_busy"] = "1"

        response = requests.post(
            f"{self.base_url}/api/frames",
            files={"frame": ("frame.jpg", frame_bytes, "image/jpeg")},
            data=data,
            timeout=120,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("audio_base64"):
            payload["audio_bytes"] = base64.b64decode(payload["audio_base64"])
        return payload

    def send_events(self, events):
        if not events:
            return {"status": "skipped", "accepted": 0}

        response = requests.post(
            f"{self.base_url}/api/events",
            json={"events": events},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def start_session(self):
        response = requests.post(f"{self.base_url}/api/session/start", timeout=30)
        response.raise_for_status()
        return response.json()

    def stop_session(self):
        response = requests.post(f"{self.base_url}/api/session/stop", timeout=30)
        response.raise_for_status()
        return response.json()
