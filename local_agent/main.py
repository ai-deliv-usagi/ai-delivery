import os
import time
import tempfile

from dotenv import load_dotenv
import pygame

from local_agent.capture.minecraft import MinecraftCapturer
from local_agent.client.cloud_api import CloudApiClient
from local_agent.tiktok.listener import LocalTikTokListener


def log(message):
    print(f"[local_agent] {message}", flush=True)


def play_audio(audio_bytes):
    if not audio_bytes:
        return

    log(f"Playing audio ({len(audio_bytes)} bytes)")
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
    window_title = os.getenv("MINECRAFT_WINDOW_TITLE", "Minecraft")
    tiktok_unique_id = os.getenv("TIKTOK_UNIQUE_ID", "").strip()

    log(f"Starting with CLOUD_APP_URL={cloud_url}")
    log(f"Capture interval: {interval}s, window title: {window_title}")

    capturer = MinecraftCapturer(window_title=window_title)
    client = CloudApiClient(cloud_url)
    pygame.mixer.init()

    start_result = client.start_session()
    log(f"Session start: {start_result}")

    tiktok_listener = None
    if tiktok_unique_id:
        tiktok_listener = LocalTikTokListener(unique_id=tiktok_unique_id, log=log)
        tiktok_listener.start()
        log(f"TikTokLive listener started: {tiktok_unique_id}")
    else:
        log("TIKTOK_UNIQUE_ID is not set. TikTokLive listener is disabled.")

    last_no_frame_log = 0
    frame_count = 0
    try:
        while True:
            if tiktok_listener:
                events = tiktok_listener.fetch_events()
                if events:
                    try:
                        event_result = client.send_events(events)
                        log(f"Sent TikTok events: {event_result}")
                    except Exception as exc:
                        log(f"Failed to send TikTok events: {exc}")

            frame = capturer.get_frame_bytes()
            if frame:
                frame_count += 1
                log(f"Sending frame #{frame_count} ({len(frame)} bytes)")
                result = client.send_frame(frame)
                log(f"Cloud response: {result.get('status')}, comment={result.get('comment')!r}")
                play_audio(result.get("audio_bytes"))
            elif time.time() - last_no_frame_log >= 10:
                log("No Minecraft frame captured. Is the window visible and not minimized?")
                last_no_frame_log = time.time()
            time.sleep(interval)
    finally:
        stop_result = client.stop_session()
        log(f"Session stop: {stop_result}")


if __name__ == "__main__":
    main()
