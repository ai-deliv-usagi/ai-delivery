import base64

from flask import jsonify, render_template, render_template_string, request

from cloud_app.dashboard.state import dashboard_data


def _get_stream_manager(get_stream_manager, create=True):
    try:
        return get_stream_manager(create=create)
    except TypeError:
        return get_stream_manager()


def register_routes(app, get_stream_manager, frame_store=None):
    @app.route("/api/status")
    def get_status():
        stream_manager = _get_stream_manager(get_stream_manager, create=False)
        if stream_manager and hasattr(stream_manager, "refresh_dashboard"):
            stream_manager.refresh_dashboard()
        return jsonify(dashboard_data)

    @app.route("/api/force_jack/<mode_id>")
    def force_jack(mode_id):
        stream_manager = _get_stream_manager(get_stream_manager)
        if stream_manager:
            return stream_manager.trigger_manual_jack(mode_id)
        return jsonify({"status": "error"}), 500

    @app.route("/api/session/start", methods=["POST"])
    def start_session():
        stream_manager = _get_stream_manager(get_stream_manager)
        if not stream_manager:
            return jsonify({"status": "error", "message": "stream manager is unavailable"}), 500
        return jsonify(stream_manager.start_session())

    @app.route("/api/session/stop", methods=["POST"])
    def stop_session():
        stream_manager = _get_stream_manager(get_stream_manager)
        if not stream_manager:
            return jsonify({"status": "error", "message": "stream manager is unavailable"}), 500
        return jsonify(stream_manager.stop_session())

    @app.route("/api/frames", methods=["POST"])
    def receive_frame():
        uploaded = request.files.get("frame")
        if uploaded is None:
            return jsonify({"status": "error", "message": "frame is required"}), 400

        frame = uploaded.read()
        if frame_store is not None:
            frame_store.put(frame)

        stream_manager = _get_stream_manager(get_stream_manager)
        if not stream_manager:
            return jsonify({"status": "accepted"})

        result = stream_manager.process_frame(frame)
        audio = result.pop("audio", None)
        if audio:
            result["audio_base64"] = base64.b64encode(audio).decode("ascii")
            result["audio_encoding"] = "base64"
        return jsonify(result)

    @app.route("/controller")
    def controller():
        stream_manager = _get_stream_manager(get_stream_manager)
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
                <title>AI実況ダッシュボード</title>
                <style>
                    body { background: #f4f4f7; color: #1a1a1a; font-family: Segoe UI, sans-serif; margin: 0; padding: 15px; }
                    .container { max-width: 900px; margin: 0 auto; }
                    .status-row { display: flex; gap: 10px; margin-bottom: 10px; }
                    .card { background: white; border: 1px solid #d1d1d6; padding: 15px; border-radius: 8px; }
                    .mode-name { color: #ff0050; font-size: 1.4em; font-weight: bold; }
                    .timer { font-family: Consolas, monospace; font-size: 1.8em; font-weight: bold; color: #008f84; }
                    .log-container { background: white; border: 1px solid #d1d1d6; height: 160px; overflow-y: auto; padding: 10px; font-family: Consolas, monospace; border-radius: 8px; }
                    .queue-badge { background: #e9e9ed; color: #1a1a1a; padding: 4px 10px; border-radius: 15px; font-size: 0.9em; margin-right: 8px; border: 1px solid #d1d1d6; display: inline-block; margin-bottom: 5px; }
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="status-row">
                        <div class="card" style="flex:2">
                            <div style="font-size:0.9em;color:#888" onclick="openController()">モード</div>
                            <div id="mode" class="mode-name">--</div>
                        </div>
                        <div class="card" style="flex:1">
                            <div style="font-size:0.9em;color:#888">残り時間</div>
                            <div id="timer" class="timer">--</div>
                        </div>
                    </div>
                    <div class="card" style="margin-bottom:10px">
                        <div style="font-size:1.0em;color:#888;margin-bottom:8px">ギフト予約</div>
                        <div id="queue"></div>
                    </div>
                    <div class="log-container" id="logs"></div>
                </div>
                <script>
                    const UPDATE_INTERVAL_MS = 1000;

                    async function update() {
                        try {
                            const res = await fetch('/api/status');
                            const data = await res.json();
                            document.getElementById('mode').innerText = data.active_mode;
                            document.getElementById('timer').innerText = data.timer + '秒';
                            document.getElementById('queue').innerHTML = data.queue.length
                                ? data.queue.map(q => `<span class="queue-badge">${q[2]} (${q[1]})</span>`).join('')
                                : '予約なし';
                            document.getElementById('logs').innerHTML = data.logs.slice().reverse().slice(0, 4)
                                .map(l => `<div>${l}</div>`).join('');
                        } catch (e) { console.error(e); }
                    }
                    function openController() {
                        window.open('/controller', 'JackController', 'width=400,height=600');
                    }
                    setInterval(update, UPDATE_INTERVAL_MS);
                    update();
                </script>
            </body>
            </html>
            """
        )
