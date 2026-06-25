import base64

from flask import jsonify, render_template, render_template_string, request

from cloud_app.dashboard.state import dashboard_data


POKEMON_STATE_FIELDS = (
    "phase",
    "own_active",
    "own_bench",
    "available_actions",
    "opponent",
    "field",
    "notes",
)


def sanitize_pokemon_battle_state(payload):
    state = dashboard_data.get("pokemon_battle_state", {}).copy()
    for field in POKEMON_STATE_FIELDS:
        if field in payload:
            state[field] = str(payload.get(field) or "").strip()

    if "turn_history" in payload:
        history = payload.get("turn_history")
        if isinstance(history, str):
            history = [line.strip() for line in history.splitlines() if line.strip()]
        elif isinstance(history, list):
            history = [str(item).strip() for item in history if str(item).strip()]
        else:
            history = []
        state["turn_history"] = history[-6:]

    return state


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

    @app.route("/api/pokemon/state", methods=["GET", "POST"])
    def pokemon_state():
        if request.method == "GET":
            return jsonify(dashboard_data["pokemon_battle_state"])

        payload = request.get_json(silent=True) or {}
        dashboard_data["pokemon_battle_state"] = sanitize_pokemon_battle_state(payload)
        return jsonify({"status": "saved", "pokemon_battle_state": dashboard_data["pokemon_battle_state"]})

    @app.route("/pokemon-control")
    def pokemon_control():
        return render_template_string(
            """
            <!doctype html>
            <html>
            <head>
                <meta charset="utf-8">
                <title>Pokémon Adviser Control</title>
                <style>
                    body { font-family: Segoe UI, sans-serif; margin: 0; padding: 16px; background: #f4f4f7; color: #1a1a1a; }
                    .grid { display: grid; grid-template-columns: repeat(2, minmax(280px, 1fr)); gap: 12px; }
                    label { display: block; font-weight: 700; margin-bottom: 4px; }
                    textarea, input { width: 100%; box-sizing: border-box; border: 1px solid #ccc; border-radius: 8px; padding: 8px; font: 14px Consolas, monospace; }
                    textarea { min-height: 76px; }
                    button { margin-top: 12px; padding: 10px 16px; border: 0; border-radius: 8px; background: #ff0050; color: white; font-weight: 700; cursor: pointer; }
                    #status { margin-left: 10px; color: #008f84; font-weight: 700; }
                </style>
            </head>
            <body>
                <h1>Pokémon Adviser Control</h1>
                <div class="grid">
                    <div><label>Phase</label><input id="phase" placeholder="move selection / forced switch"></div>
                    <div><label>Available actions</label><textarea id="available_actions" placeholder="Move names, PP, legal switches"></textarea></div>
                    <div><label>Own active</label><textarea id="own_active" placeholder="Species, HP%, status, boosts, item"></textarea></div>
                    <div><label>Own bench</label><textarea id="own_bench" placeholder="Bench HP/status/switchable"></textarea></div>
                    <div><label>Opponent visible state</label><textarea id="opponent" placeholder="Active, HP%, status, known moves/items"></textarea></div>
                    <div><label>Field</label><textarea id="field" placeholder="Weather, terrain, hazards, screens, timers"></textarea></div>
                    <div><label>Turn history</label><textarea id="turn_history" placeholder="One turn per line; newest lines are kept"></textarea></div>
                    <div><label>Notes</label><textarea id="notes" placeholder="Uncertainty, reads, viewer poll"></textarea></div>
                </div>
                <button onclick="saveState()">Save battle state</button><span id="status"></span>
                <script>
                    const fields = ['phase','own_active','own_bench','available_actions','opponent','field','turn_history','notes'];
                    async function loadState() {
                        const res = await fetch('/api/pokemon/state', { cache: 'no-store' });
                        const data = await res.json();
                        for (const field of fields) {
                            const value = field === 'turn_history' ? (data[field] || []).join('\n') : (data[field] || '');
                            document.getElementById(field).value = value;
                        }
                    }
                    async function saveState() {
                        const payload = {};
                        for (const field of fields) payload[field] = document.getElementById(field).value;
                        const res = await fetch('/api/pokemon/state', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload) });
                        document.getElementById('status').innerText = res.ok ? 'saved' : 'error';
                    }
                    loadState();
                </script>
            </body>
            </html>
            """
        )

    @app.route("/character-overlay")
    def character_overlay():
        stream_manager = _get_stream_manager(get_stream_manager, create=False)
        if stream_manager and hasattr(stream_manager, "refresh_dashboard"):
            stream_manager.refresh_dashboard()
        return render_template_string(
            """
            <!doctype html>
            <html>
            <head>
                <meta charset="utf-8">
                <style>
                    html, body { margin: 0; width: 100%; height: 100%; background: transparent; overflow: hidden; }
                    #wrap { width: 100vw; height: 100vh; display: flex; align-items: end; justify-content: center; }
                    #character { max-width: 100%; max-height: 100%; object-fit: contain; transition: opacity 180ms ease; }
                    #fallback { display: none; padding: 16px 24px; border-radius: 18px; background: rgba(0,0,0,.55); color: white; font: 700 32px system-ui, sans-serif; }
                </style>
            </head>
            <body>
                <div id="wrap">
                    <img id="character" alt="active character">
                    <div id="fallback"></div>
                </div>
                <script>
                    let activeImage = '';
                    async function updateCharacter() {
                        const res = await fetch('/api/status', { cache: 'no-store' });
                        const data = await res.json();
                        const image = data.character_image || '';
                        const img = document.getElementById('character');
                        const fallback = document.getElementById('fallback');
                        if (image) {
                            fallback.style.display = 'none';
                            img.style.display = 'block';
                            if (image !== activeImage) {
                                activeImage = image;
                                img.style.opacity = 0;
                                img.onload = () => { img.style.opacity = 1; };
                                img.src = image;
                            }
                        } else {
                            img.style.display = 'none';
                            fallback.style.display = 'block';
                            fallback.innerText = data.active_character || data.active_mode || '';
                        }
                    }
                    setInterval(updateCharacter, 500);
                    updateCharacter();
                </script>
            </body>
            </html>
            """
        )

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
