import logging
import os

from dotenv import load_dotenv
from flask import Flask

from cloud_app.ai.gemini_commentator import AICommentator
from cloud_app.dashboard.routes import register_routes
from cloud_app.frames import FrameStore
from cloud_app.stream.manager import StreamManager
from cloud_app.tiktok.listener import TikTokListener
from cloud_app.voice.voicevox import VoicevoxOutput

load_dotenv()

app = Flask(__name__, template_folder="../templates")
logging.getLogger("werkzeug").setLevel(logging.ERROR)

frame_store = FrameStore()
stream_manager = None


def get_stream_manager():
    global stream_manager
    if stream_manager is None:
        stream_manager = create_stream_manager()
    return stream_manager


register_routes(app, get_stream_manager, frame_store)


def create_stream_manager():
    api_key = os.getenv("API_KEY")
    model_id = os.getenv("GEMINI_MODEL_ID", "gemini-2.5-flash-lite")
    tiktok_unique_id = os.getenv("TIKTOK_UNIQUE_ID")
    voicevox_url = os.getenv("VOICEVOX_URL", "http://127.0.0.1:50021")
    voicevox_speaker_id = int(os.getenv("VOICEVOX_SPEAKER_ID", "63"))

    ai = AICommentator(api_key, model_id)
    voice = VoicevoxOutput(voicevox_url, voicevox_speaker_id)
    tiktok = TikTokListener(unique_id=tiktok_unique_id)
    return StreamManager(frame_store, ai, voice, tiktok)


def main():
    port = int(os.getenv("PORT", "5000"))
    enable_debug_input = os.getenv("ENABLE_DEBUG_INPUT", "").lower() in {"1", "true", "yes"}
    get_stream_manager().run(
        flask_app=app,
        port=port,
        enable_debug_input=enable_debug_input,
    )


if __name__ == "__main__":
    main()
