import requests


class CloudApiClient:
    def __init__(self, base_url):
        self.base_url = base_url.rstrip("/")

    def send_frame(self, frame_bytes):
        response = requests.post(
            f"{self.base_url}/api/frames",
            files={"frame": ("frame.jpg", frame_bytes, "image/jpeg")},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

