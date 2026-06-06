import logging

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, render_template_string, request

from cloud_app.ai.gemini_commentator import AICommentator
from cloud_app.dashboard.state import dashboard_data
from cloud_app.frames import FrameStore
from cloud_app.stream.manager import StreamManager
from cloud_app.tiktok.listener import TikTokListener
from cloud_app.voice.voicevox import VoicevoxOutput
from local_agent.capture.minecraft import MinecraftCapturer

load_dotenv()

app = Flask(__name__)
logging.getLogger("werkzeug").setLevel(logging.ERROR)

frame_store = FrameStore()
stream_manager = None


@app.route("/api/status")
def get_status():
    return jsonify(dashboard_data)


@app.route("/api/force_jack/<mode_id>")
def force_jack(mode_id):
    if stream_manager:
        return stream_manager.trigger_manual_jack(mode_id)
    return jsonify({"status": "error"}), 500


@app.route("/api/frames", methods=["POST"])
def receive_frame():
    uploaded = request.files.get("frame")
    if uploaded is None:
        return jsonify({"status": "error", "message": "frame is required"}), 400

    frame_store.put(uploaded.read())
    return jsonify({"status": "accepted"})


@app.route("/controller")
def controller():
    personalities = stream_manager.personality_library if stream_manager else {}
    return render_template("controller.html", personalities=personalities)


@app.route("/")
def index():
    return render_template_string(
        """
        <!doctype html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>AI Delivery Dashboard</title>
        </head>
        <body>
            <main>
                <div id="mode">--</div>
                <div id="timer">--</div>
                <div id="queue"></div>
                <div id="logs"></div>
            </main>
            <script>
                async function update() {
                    const res = await fetch('/api/status');
                    const data = await res.json();
                    document.getElementById('mode').innerText = data.active_mode;
                    document.getElementById('timer').innerText = data.timer + 's';
                    document.getElementById('queue').innerHTML = data.queue.length
                        ? data.queue.map(q => `${q[2]} (${q[1]})`).join(', ')
                        : 'Empty';
                    document.getElementById('logs').innerHTML = data.logs.slice().reverse().slice(0, 4).join('<br>');
                }
                setInterval(update, 1000);
                update();
            </script>
        </body>
        </html>
        """
    )


def main():
    from cloud_app.main import main as cloud_main

    cloud_main()


if __name__ == "__main__":
    main()
