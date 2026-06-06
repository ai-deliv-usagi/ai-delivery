import os
import time

from dotenv import load_dotenv

from local_agent.capture.minecraft import MinecraftCapturer
from local_agent.client.cloud_api import CloudApiClient


def main():
    load_dotenv()
    cloud_url = os.getenv("CLOUD_APP_URL", "http://127.0.0.1:5000")
    interval = float(os.getenv("CAPTURE_INTERVAL_SECONDS", "1.0"))

    capturer = MinecraftCapturer()
    client = CloudApiClient(cloud_url)

    while True:
        frame = capturer.get_frame_bytes()
        if frame:
            client.send_frame(frame)
        time.sleep(interval)


if __name__ == "__main__":
    main()

