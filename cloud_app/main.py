import logging
import os
import types

from dotenv import load_dotenv
from flask import Flask

from cloud_app.ai.gemini_commentator import AICommentator
from cloud_app.dashboard.routes import register_routes
from cloud_app.frames import FrameStore
from cloud_app.stream.manager import StreamManager
from cloud_app.stream.state_store import GcsStreamStateStore, NullStreamStateStore, SafeStreamStateStore
from cloud_app.voice.voicevox import VoicevoxOutput

load_dotenv()

app = Flask(__name__, template_folder="../templates")
logging.getLogger("werkzeug").setLevel(logging.ERROR)

frame_store = FrameStore()
stream_manager = None


def get_stream_manager(create=True):
    global stream_manager
    if stream_manager is None and create:
        stream_manager = create_stream_manager()
    return stream_manager


register_routes(app, get_stream_manager, frame_store)


def clean_env_value(value):
    if value is None:
        return None
    return value.lstrip("\ufeff").strip()


def create_stream_manager():
    model_id = clean_env_value(os.getenv("GEMINI_MODEL_ID", "gemini-2.5-flash-lite"))
    project_id = clean_env_value(
        os.getenv("GCP_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT")
    )
    vertex_ai_location = clean_env_value(os.getenv("VERTEX_AI_LOCATION", "global"))
    voicevox_url = clean_env_value(os.getenv("VOICEVOX_URL", "http://127.0.0.1:50021"))
    voicevox_speaker_id = int(os.getenv("VOICEVOX_SPEAKER_ID", "63"))
    voicevox_max_text_chars = int(os.getenv("VOICEVOX_MAX_TEXT_CHARS", "240"))
    audio_bucket_name = clean_env_value(os.getenv("AUDIO_BUCKET_NAME"))
    session_idle_timeout_seconds = int(os.getenv("SESSION_IDLE_TIMEOUT_SECONDS", "180"))
    jack_duration_seconds = int(os.getenv("JACK_DURATION_SECONDS", "120"))

    ai = AICommentator(model_id, project_id, vertex_ai_location)
    voice = VoicevoxOutput(voicevox_url, voicevox_speaker_id, voicevox_max_text_chars)
    tiktok = types.SimpleNamespace(current_patch_id="normal")
    state_store = NullStreamStateStore()
    if audio_bucket_name:
        state_store = SafeStreamStateStore(GcsStreamStateStore(audio_bucket_name))
    return StreamManager(
        frame_store,
        ai,
        voice,
        tiktok,
        state_store=state_store,
        session_idle_timeout_seconds=session_idle_timeout_seconds,
        jack_duration_seconds=jack_duration_seconds,
    )


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
