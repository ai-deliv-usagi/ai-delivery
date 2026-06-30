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

        playback_busy = request.form.get("playback_busy", "").lower() in {"1", "true", "yes"}
        result = stream_manager.process_frame(frame, playback_busy=playback_busy)
        audio = result.pop("audio", None)
        if audio:
            result["audio_base64"] = base64.b64encode(audio).decode("ascii")
            result["audio_encoding"] = "base64"
        return jsonify(result)

    @app.route("/api/events", methods=["POST"])
    def receive_events():
        payload = request.get_json(silent=True) or {}
        events = payload.get("events")
        if not isinstance(events, list):
            return jsonify({"status": "error", "message": "events must be a list"}), 400

        stream_manager = _get_stream_manager(get_stream_manager)
        if not stream_manager:
            return jsonify({"status": "error", "message": "stream manager is unavailable"}), 500

        return jsonify(stream_manager.submit_events(events))

    @app.route("/controller")
    def controller():
        stream_manager = _get_stream_manager(get_stream_manager)
        personalities = stream_manager.personality_library if stream_manager else {}
        return render_template("controller.html", personalities=personalities)

    @app.route("/")
    def index():
        return render_template_string(
            r"""
            <!doctype html>
            <html>
            <head>
                <meta charset="utf-8">
                <title>AI実況ダッシュボード</title>
                <style>
                    :root {
                        --tt-pink: #fe2c55;
                        --tt-cyan: #25f4ee;
                    }
                    html, body {
                        background: transparent;
                        color: #fff;
                        font-family: 'Segoe UI', 'Hiragino Sans', sans-serif;
                        margin: 0;
                        padding: 14px;
                    }
                    .panel {
                        max-width: 720px;
                        display: flex;
                        flex-direction: column;
                        gap: 8px;
                    }
                    .card {
                        background: rgba(18, 18, 22, 0.72);
                        backdrop-filter: blur(10px);
                        -webkit-backdrop-filter: blur(10px);
                        border: 1px solid rgba(255, 255, 255, 0.1);
                        padding: 10px 14px;
                        border-radius: 16px;
                        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.35);
                    }
                    .header {
                        display: flex;
                        align-items: center;
                        gap: 14px;
                        flex-wrap: wrap;
                    }
                    .status-pill {
                        display: inline-flex;
                        align-items: center;
                        gap: 6px;
                        font-weight: 800;
                        font-size: 0.8em;
                        padding: 4px 10px;
                        border-radius: 999px;
                    }
                    .status-pill.online { background: rgba(37, 244, 238, 0.18); color: var(--tt-cyan); }
                    .status-pill.offline { background: rgba(255, 255, 255, 0.1); color: rgba(255, 255, 255, 0.5); }
                    .status-dot { width: 8px; height: 8px; border-radius: 50%; background: currentColor; box-shadow: 0 0 8px currentColor; }
                    .status-dot.blink { animation: blink 1.4s ease-in-out infinite; }
                    @keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }
                    .idle-note { margin-left: auto; font-size: 0.72em; color: rgba(255, 255, 255, 0.55); }
                    .idle-note.warn { color: var(--tt-pink); font-weight: 700; }
                    .mode-name {
                        background: linear-gradient(90deg, var(--tt-cyan), var(--tt-pink));
                        -webkit-background-clip: text;
                        background-clip: text;
                        color: transparent;
                        font-size: 1.2em;
                        font-weight: 800;
                        cursor: pointer;
                    }
                    .timer { font-family: Consolas, monospace; font-size: 1.2em; font-weight: 800; color: #fff; }
                    .log-container {
                        height: 270px;
                        overflow-y: auto;
                        display: flex;
                        flex-direction: column;
                        gap: 10px;
                    }
                    .log-container::-webkit-scrollbar { width: 4px; }
                    .log-container::-webkit-scrollbar-thumb { background: rgba(255, 255, 255, 0.2); border-radius: 4px; }
                    .log-entry {
                        padding-bottom: 10px;
                        border-bottom: 1px solid rgba(255, 255, 255, 0.08);
                    }
                    .log-entry:last-child { border-bottom: none; padding-bottom: 0; }
                    .log-time {
                        font-family: Consolas, monospace;
                        font-size: 0.72em;
                        font-weight: 700;
                        color: var(--tt-cyan);
                        margin-bottom: 3px;
                    }
                    .log-msg {
                        font-size: 1em;
                        line-height: 1.55;
                        color: rgba(255, 255, 255, 0.88);
                        word-break: break-word;
                    }
                    .log-entry.newest .log-msg {
                        color: #fff;
                        font-weight: 600;
                    }
                </style>
            </head>
            <body>
                <div class="panel">
                    <div class="card header">
                        <span id="status-pill" class="status-pill offline">
                            <span id="status-dot" class="status-dot"></span>
                            <span id="status-text">OFFLINE</span>
                        </span>
                        <span id="mode" class="mode-name" onclick="openController()">--</span>
                        <span id="timer" class="timer">--</span>
                        <span id="idle-note" class="idle-note"></span>
                    </div>
                    <div class="card log-container" id="logs"></div>
                </div>
                <script>
                    const UPDATE_INTERVAL_MS = 1000;
                    const IDLE_WARN_SECONDS = 30;
                    const LOG_LINE_RE = /^\[(\d{2}:\d{2}:\d{2})\]\s*([\s\S]*)$/;

                    function escapeHtml(text) {
                        const div = document.createElement('div');
                        div.innerText = text;
                        return div.innerHTML;
                    }

                    async function update() {
                        try {
                            const res = await fetch('/api/status');
                            const data = await res.json();

                            document.getElementById('mode').innerText = data.active_mode;
                            document.getElementById('timer').innerText = data.timer + '秒';

                            const pill = document.getElementById('status-pill');
                            const dot = document.getElementById('status-dot');
                            const text = document.getElementById('status-text');
                            pill.className = 'status-pill ' + (data.is_online ? 'online' : 'offline');
                            dot.className = 'status-dot' + (data.is_online ? ' blink' : '');
                            text.innerText = data.is_online ? 'ON AIR' : 'OFFLINE';

                            const idleNote = document.getElementById('idle-note');
                            if (data.is_online && data.idle_seconds != null && data.session_idle_timeout_seconds != null) {
                                const remaining = Math.max(0, data.session_idle_timeout_seconds - data.idle_seconds);
                                idleNote.innerText = `無反応 ${data.idle_seconds}秒 / 自動停止まで ${remaining}秒`;
                                idleNote.className = 'idle-note' + (remaining <= IDLE_WARN_SECONDS ? ' warn' : '');
                            } else {
                                idleNote.innerText = '';
                                idleNote.className = 'idle-note';
                            }

                            document.getElementById('logs').innerHTML = data.logs.slice().reverse().slice(0, 4)
                                .map((l, i) => {
                                    const match = l.match(LOG_LINE_RE);
                                    const time = match ? match[1] : '';
                                    const msg = match ? match[2] : l;
                                    const newestClass = i === 0 ? ' newest' : '';
                                    return `<div class="log-entry${newestClass}">
                                        <div class="log-time">${escapeHtml(time)}</div>
                                        <div class="log-msg">${escapeHtml(msg)}</div>
                                    </div>`;
                                }).join('');
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
