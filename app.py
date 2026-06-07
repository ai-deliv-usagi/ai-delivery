import logging

from dotenv import load_dotenv
from flask import Flask, jsonify

from cloud_app.ai.gemini_commentator import AICommentator
from cloud_app.dashboard.routes import register_routes
from cloud_app.dashboard.state import dashboard_data
from cloud_app.frames import FrameStore
from cloud_app.stream.manager import StreamManager
from cloud_app.voice.voicevox import VoicevoxOutput
from local_agent.capture.minecraft import MinecraftCapturer

load_dotenv()

app = Flask(__name__)
logging.getLogger("werkzeug").setLevel(logging.ERROR)

frame_store = FrameStore()
stream_manager = None


def get_stream_manager():
    return stream_manager


register_routes(app, get_stream_manager, frame_store)


def main():
    from cloud_app.main import main as cloud_main

    cloud_main()


if __name__ == "__main__":
    main()
