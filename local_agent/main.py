import os
import time
import tempfile

from dotenv import load_dotenv
import pygame

from local_agent.capture.minecraft import MinecraftCapturer
from local_agent.client.cloud_api import CloudApiClient


def play_audio(audio_bytes):
    if not audio_bytes:
        return

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as audio_file:
        audio_file.write(audio_bytes)
        audio_path = audio_file.name

    pygame.mixer.music.load(audio_path)
    pygame.mixer.music.play()
    while pygame.mixer.music.get_busy():
        time.sleep(0.05)
    pygame.mixer.music.unload()
    os.remove(audio_path)


def main():
    load_dotenv()
    cloud_url = os.getenv("CLOUD_APP_URL", "http://127.0.0.1:5000")
    interval = float(os.getenv("CAPTURE_INTERVAL_SECONDS", "1.0"))

    capturer = MinecraftCapturer()
    client = CloudApiClient(cloud_url)
    pygame.mixer.init()

    client.start_session()
    try:
        while True:
            frame = capturer.get_frame_bytes()
            if frame:
                result = client.send_frame(frame)
                play_audio(result.get("audio_bytes"))
            time.sleep(interval)
    finally:
        client.stop_session()


if __name__ == "__main__":
    main()
