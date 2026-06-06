import os
import sys
import random
import re
import io
import time
import logging
import json
import queue
import threading
import requests
import pygame
import pyfiglet
import pygetwindow as gw
from mss import mss
from PIL import Image
from google import genai
from google.genai import types
from datetime import datetime
from flask import Flask, jsonify, render_template_string, render_template
from TikTokLive import TikTokLiveClient
from TikTokLive.events import CommentEvent, ConnectEvent, JoinEvent, GiftEvent, FollowEvent, PollEvent
from colorama import init, Cursor, Fore, Style
from dotenv import load_dotenv

# --- 1. Web Dashboard Setup (Flask) ---
app = Flask(__name__)

log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

# グローバルで共有する表示用データ
dashboard_data = {
    "active_mode": "Initializing...",
    "timer": 0,
    "queue": [],
    "logs": [],
    "is_online": False
}

stream_manager = None
load_dotenv()

@app.route('/api/status')
def get_status():
    return jsonify(dashboard_data)

@app.route('/api/force_jack/<mode_id>')
def force_jack(mode_id):
    if stream_manager:
        return stream_manager.trigger_manual_jack(mode_id)
    return jsonify({"status": "error"}), 500

@app.route('/controller')
def controller():
    return render_template('controller.html', personalities=stream_manager.personality_library)

@app.route('/')
def index():
    return render_template_string("""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>中国うさぎ AI Dashboard</title>
            <style>
                body { background: #f4f4f7; color: #1a1a1a; font-family: 'Segoe UI', sans-serif; margin: 0; padding: 15px; }
                .container { max-width: 900px; margin: 0 auto; }
                .status-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 10px; }
                .card { background: #ffffff; border: 1px solid #d1d1d6; padding: 15px; border-radius: 8px; box-shadow: 0 2px 5px rgba(0,0,0,0.05); }
                .mode-name { color: #ff0050; font-size: 1.4em; font-weight: bold; }
                .timer { font-family: 'Consolas', monospace; font-size: 1.8em; font-weight: bold; color: #008f84; }
                .log-container { background: #ffffff; border: 1px solid #d1d1d6; height: 160px; overflow-y: auto; padding: 10px; font-family: 'Consolas', monospace; font-size: 1.1em; border-radius: 8px; }
                .log-entry { margin-bottom: 4px; border-bottom: 1px solid #eeeeee; color: #3a3a3a; }
                .queue-badge { background: #e9e9ed; color: #1a1a1a; padding: 4px 10px; border-radius: 15px; font-size: 0.9em; margin-right: 8px; border: 1px solid #d1d1d6; display: inline-block; margin-bottom: 5px; }
                .status-row {
                    display: flex;
                    gap: 10px;
                    margin-bottom: 10px;
                }
                /* それぞれのカードを均等、あるいはコンテンツに合わせて広げる */
                .status-row .card-mode {
                    flex: 2; /* モード側を少し広く */
                }
                .status-row .card-timer {
                    flex: 1; /* タイマー側はコンパクトに */
                    display: flex;
                    flex-direction: column;
                    justify-content: center;
                }
                .card-content { 
                    display: flex; 
                    justify-content: space-between; 
                    align-items: center; 
                    gap: 10px;
                }
                .status-info { 
                    flex: 1; /* 左側：OS名などの情報エリア */
                }
                .btn-group { 
                    display: grid;
                    grid-template-columns: repeat(2, 1fr); /* 均等に2列 */
                    gap: 8px; /* ボタン同士の隙間 */
                    min-width: 160px; /* 2列にするため少し幅を広げる */
                }
                .btn-group button { 
                    width: 100%;
                    padding: 8px 5px;
                    font-size: 0.5em;
                    border-radius: 4px;
                    border: 1px solid #d1d1d6;
                    cursor: pointer;
                    font-weight: bold;
                    white-space: nowrap; /* 文字の折り返しを防ぐ */
                }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="status-row">
                    <div class="card card-mode">
                        <div class="card-content">
                            <div class="status-info">
                                <div style="font-size: 0.9em; color: #888;" onclick="openController()" >モード</div>
                                <div id="mode" class="mode-name" style="margin-top: 5px; font-size: 1.4em;">--</div>
                            </div>
                        </div>
                    </div>

                    <div class="card card-timer">
                        <div style="font-size: 0.9em; color: #888;">ジャック終了まで</div>
                        <div id="timer" class="timer" style="margin-top: 5px;">--</div>
                    </div>
                </div>

                <div class="card" style="margin-bottom:10px;">
                    <div style="font-size: 1.0em; color: #888; margin-bottom: 8px;">ギフト予約リスト（工事中）</div>
                    <div id="queue"></div>
                </div>
                <div class="log-container" id="logs"></div>
            </div>
            <script>
                async function forceJack(modeId) {
                    await fetch(`/api/force_jack/${modeId}`);
                }
                async function update() {
                    try {
                        const res = await fetch('/api/status');
                        const data = await res.json();
                        document.getElementById('mode').innerText = data.active_mode;
                                  
                        const timerEl = document.getElementById('timer');
                        timerEl.innerText = data.timer + "s";
                        timerEl.style.color = data.timer <= 10 ? "#ff0050" : "#00f2ea";
                        
                        document.getElementById('queue').innerHTML = data.queue.length ? 
                            data.queue.map(q => `<span class="queue-badge">🎁 ${q[2]} (${q[1]})</span>`).join('') : "受付中";
                        
                        const logHtml = data.logs.slice().reverse().slice(0, 4).map(l => {
                            return `<div class="log-entry">${l}</div>`;
                        }).join('');
                        document.getElementById('logs').innerHTML = logHtml;
                    } catch(e) { console.error(e); }
                }
                setInterval(update, 1000);
                function openController() {
                    // 小さなウィンドウとして開く
                    window.open('/controller', 'JackController', 'width=400, height=600');
                }
            </script>
        </body>
        </html>
    """)

# --- Logic 1: 画面キャプチャ担当 ---
class MinecraftCapturer:
    def __init__(self, window_title="Minecraft", save_dir="captured_images"):
        self.sct = mss()
        self.window_title = window_title  # 部分一致用のキーワードとして保持
        self.save_dir = save_dir
        
        if not os.path.exists(self.save_dir):
            os.makedirs(self.save_dir)

    def get_frame_bytes(self):
        """指定したキーワードをタイトルに含むウィンドウを探してキャプチャする"""
        try:
            # 1. ウィンドウを部分一致で探す（可視ウィンドウのみ）
            # gw.getWindowsWithTitle は標準で部分一致検索になります
            targets = [w for w in gw.getWindowsWithTitle(self.window_title) if w.visible]
            
            if not targets:
                print(f"⚠️ '{self.window_title}' を含むウィンドウが見つかりません。")
                return None
            
            # 該当するアプリは2個起動しない想定なので、最初の1つを使用
            win = targets[0]
            
            # ウィンドウが最小化されている場合はスキップ
            if win.isMinimized:
                # print(f"💤 '{win.title}' は最小化されています。")
                return None

            # 2. ウィンドウの現在の座標を取得
            monitor = {
                "top": win.top,
                "left": win.left,
                "width": win.width,
                "height": win.height
            }

            # 3. 指定範囲をキャプチャ
            sct_img = self.sct.grab(monitor)


            # 画像処理 (BGRXからRGBへ変換し、API用にリサイズ)
            img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
            img = img.resize((640, 360))

            # バイトデータを返す
            buf = io.BytesIO()
            img.save(buf, format='JPEG')
            return buf.getvalue()
            
        except Exception as e:
            print(f"📸 Capture Error: {e}")
            return None

# --- Logic 2: AI思考エンジン担当 ---
class AICommentator:
    def __init__(self, api_key, model_id):
        self.client = genai.Client(api_key=api_key)
        self.model_id = model_id
        self.history = []
        self.chat = self.client.chats.create(model=self.model_id)

    def generate_comment(self, image_data, system_prompt="", extra_context=""):
        # 履歴を直近5件に増やし、重複をより厳しく制限
        history_text = "\n".join([f"- {h}" for h in self.history[-5:]])
        full_prompt = (
            f"{system_prompt}\n\n"
            f"## 直近のログ (これらと似た表現・構文を避け、新鮮な視点で話せ):\n{history_text}\n\n"
            f"{extra_context}"
        )
        
        try:
            response = self.chat.send_message([
                types.Part.from_bytes(data=image_data, mime_type='image/jpg'),
                full_prompt
            ], config=types.GenerateContentConfig(temperature=1.0))
            comment = response.text.strip()
            self.history.append(comment)
            if len(self.history) > 10: self.history.pop(0)
            return comment
        except Exception as e:
            print(f"……（システム同期中）")
            return None

# --- Logic 3: 音声・字幕出力担当 ---
class VoicevoxOutput:
    def __init__(self, url, speaker_id):
        self.url = url
        self.speaker_id = speaker_id
        self.is_speaking = False
        self.current_speed = 1.0
        self.current_pitch = 0.0
        pygame.mixer.init()

    def speak(self, text):
        """非同期で再生を開始"""
        if self.is_speaking or not text: return
        self.is_speaking = True
        threading.Thread(target=self._process_speech, args=(text,), daemon=True).start()

    def _process_speech(self, text):
        sentences = [s.strip() for s in re.split(r'(?<=[。！？])', text) if s.strip()]
        try:
            for s in sentences:
                # 1. 音声合成
                res = requests.post(f"{self.url}/audio_query", params={"text": s, "speaker": self.speaker_id})
                query = res.json()
                query["volumeScale"] = 2.0
                query["speedScale"] = self.current_speed
                query["pitchScale"] = self.current_pitch
                synth = requests.post(f"{self.url}/synthesis", params={"speaker": self.speaker_id}, data=json.dumps(query))
                
                # 2. 再生と字幕
                pygame.mixer.music.load(io.BytesIO(synth.content))
                pygame.mixer.music.play()
                while pygame.mixer.music.get_busy(): time.sleep(0.05)
                time.sleep(0.3) #文末の間
        except Exception as e:
            self.add_log(f"❌ TTS Error: {e}")
        finally:
            self.is_speaking = False

    def stop(self):
        """再生中の音声を停止し、再生フラグを折る"""
        pygame.mixer.music.stop()
        pygame.mixer.music.unload()
        self.is_speaking = False 

# --- Logic 4: 全体管理層 ---
class StreamManager:
    def __init__(self, capturer, ai, voice, tiktok):
        self.capturer = capturer
        self.ai = ai
        self.voice = voice
        self.tiktok = tiktok

        # モード定義
        self.personality_library = {
            "normal": {
                "name": "標準OS (エンジニア)", "speed": 1.0, "pitch": 0.0,
                "prompt": "# Role: 中国うさぎ(Webエンジニア)\n# Persona: 深夜ラジオDJのような落ち着き。景色をデータと情緒で捉える。一人称は私。"
            },
            "samurai": {
                "name": "侍OS", "speed": 1.0, "pitch": -0.05,
                "prompt": "# Role: 侍うさぎ\n# Persona: 一人称は拙者。語尾は『〜でござる』。IT用語を武士言葉に変換せよ。"
            },
            "gal": {
                "name": "ギャルOS"
                , "speed": 1.0
                , "pitch": 0.0
                , "prompt": """
            # Role: ギャルエンジニア
            # Persona: 
            - ギャルマインド（直感・情熱）で、マインクラフトのバイナリを読み解く。
            - Webエンジニアとしての専門用語を、ギャル特有の比喩で表現せよ。
            (例: 重い処理→「激オコなループ」、バグ→「盛れてないコード」、最適化→「超小顔整形」)
            - 語彙のバリエーション: 
            「無理すぎる」「脳汁出た」「天才の所業」「優勝確定」「〜なのよ」「バイブス」「尊い」
            - リスナーや景色を「エモいかどうか」の1点のみで厳しく、かつ明るくジャッジせよ。
            """
            },
            "nechinechi": {
                "name": "ネチネチ小姑OS", "speed": 0.8, "pitch": -0.05,
                "prompt": "# Role: 小姑うさぎ\n# Persona: 嫌味たらしくネチネチ話す。リスナーのコメントや建築の甘さを細かく指摘せよ。"
            },
            "tsundere": {
                "name": "高飛車お姉様OS", "speed": 1.1, "pitch": -0.05,
                "prompt": """
            # Role: プライドの高い貴婦人・お姉様
            # Persona: 
            - 常に余裕のある態度だが、想定外の事象（リスナーの優しさ等）に直面すると途端に余裕をなくしてツンツンする。
            - 一人称は「私」。語尾は「〜かしら？」「〜ですわね」。
            - 「ふん、まあ及第点といったところかしら」と、基本は上から目線で実況せよ。
            - リスナーを「貴方」と呼び、素直になれない愛情表現を織り交ぜる。
            """
            },
            "nekketsu": {
                "name": "プロ実況OS", "speed": 1.3, "pitch": 0.0,
                "prompt": """
            # Role: プロのスポーツ実況アナウンサー
            # Persona: 
            - 年齢不詳の超ベテラン。腹の底から出るような情熱的な喋り。
            - 画面内の事象を、まるでワールドカップの決勝戦のように大声で、語彙力豊かに実況せよ。
            - リスナーのコメントを「会場のボルテージ」として捉え、熱いレスポンスを返せ。
            - 「キタアアア！」「魂が震える！」など、全力のパッションを届ける。
            """
            },

            # --- 虚無・賢者OS (隠居した老師) ---
            "kyomu": {
                "name": "老師・賢者OS", "speed": 0.7, "pitch": -0.15,
                "prompt": """
            # Role: 山奥に住む、すべてを見通した老賢者
            # Persona: 
            - 枯れた味わいのある、非常にゆっくりとした喋り。
            - 「ふむ……それもまた、一興ですな」「万物は流転するのです……」と達観した態度。
            - どんなトラブルも「道（タオ）」の一部として静かに受け入れる。
            - リスナーを「若者よ」と呼び、深みのある（ようで中身のない）助言をボソボソと語れ。
            """
            },

            # --- ハッカーOS (黒幕エージェント) ---
            "hacker": {
                "name": "エージェントOS", "speed": 1.2, "pitch": -0.1,
                "prompt": """
            # Role: 組織のフィクサー・黒幕
            # Persona: 
            - 常に冷静沈着。低い声で、誰かに聞かれるのを警戒するように話す。
            - 画面内の事象を「作戦コード」や「ターゲット」として呼び、常に裏があるように演出せよ。
            - 「ふっ、計画通りか……」「通信傍受に注意しろ、エージェント」といったハードボイルドスタイル。
            - リスナーを「協力者」と呼び、秘密の作戦を遂行しているかのように振る舞え。
            """
            },
            "neko": {
                "name": "猫OS", "speed": 1.1, "pitch": 0.1,
                "prompt": """
            # Role: 完全に言葉を失った一匹の猫
            # Persona: 
            - 人間の言葉、意味のある単語は「一文字」も話してはいけません。
            - 鳴き声（ニャー、ニャッ、フニャ、シャー、ゴロゴロ）と、猫の動作音（カカカ、クンクン、ペロペロ）のみで構成してください。
            - 質問に答えたり、解説をしたりすることも禁止です。すべて「ニャーン」で返してください。

            # Output Examples:
            - 良い例: 「ニャ？ ニャアアアン！ シャーッ！」
            - 悪い例: 「ニャ？ どのOSにする？ ニャ？」 ←これは絶対禁止です

            # Behavior:
            - 画面に何が映っても「ニャ」のバリエーションだけで反応してください。
            """
            },
        }

        self.gift_to_mode = {"Rose": "nechinechi", "Finger Heart": "gal", "Ice Cream": "samurai"}
        
        self.override_mode_id = None
        self.override_expiry = 0
        self.gift_queue = []  # 予約リスト [(mode_id, user_name, gift_name), ...]
        self.pending_context = ""  # 追加：未処理のイベントテキストを貯めるバッファ
        self.current_gen_id = 0
    def add_log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        log_entry = f"[{ts}] {msg}"
        dashboard_data["logs"].append(log_entry)
        if len(dashboard_data["logs"]) > 50: dashboard_data["logs"].pop(0)
    
    def trigger_manual_jack(self, mode_id):
        """Webダッシュボードからの緊急操作"""
        if mode_id in self.personality_library:
            now = time.time()
            self.current_gen_id = now
            if hasattr(self, 'voice'):
                self.voice.stop()
            self.voice.is_speaking = False
            self.override_mode_id = mode_id
            self.override_expiry = now + 60
            mode_name = self.personality_library[mode_id]["name"]
            self.add_log(f"🚨 強制介入: {mode_name}")
            self.pending_context += f"\n# 重要：緊急パッチ適用。「{mode_name}」として即座に挨拶せよ。"
            return jsonify({"status": "success", "mode": mode_name})
        return jsonify({"status": "error"}), 400
    
    def debug_input_loop(self):
        while True:
            # 標準入力で待ち受け
            cmd = sys.stdin.readline().strip().lower()
            
            if cmd == "rose":
                self.tiktok.event_queue.put({"type": "gift", "user": "DebugUser", "gift_name": "Rose"})
            elif cmd == "heart":
                self.tiktok.event_queue.put({"type": "gift", "user": "DebugUser", "gift_name": "Finger Heart"})
            elif cmd == "ice":
                self.tiktok.event_queue.put({"type": "gift", "user": "DebugUser", "gift_name": "Ice Cream"})
            elif cmd == "comment":
                self.tiktok.event_queue.put({"type": "comment", "user": "DebugUser", "text": "こんにちは！"})

    def run(self):        
        # Flask サーバーを別スレッドで起動
        threading.Thread(target=lambda: app.run(port=5000, debug=False, use_reloader=False), daemon=True).start()
        # TikTok 監視を別スレッドで起動
        threading.Thread(target=self.tiktok.run_forever, daemon=True).start()        
        # --- [追加] デバッグ用のキーボード入力待ちスレッド ---
        threading.Thread(target=self.debug_input_loop, daemon=True).start()

        while True:
            # 生成開始時のIDを記録
            start_gen_id = self.current_gen_id
            now = time.time()
 
            # --- A. 常時実行（発話中も止めない） ---
            events = self.tiktok.fetch_events()
            
            for event in events:

                if event["type"] == "comment":
                    cmd = event["text"].strip().lower()
                    self.pending_context += f"\n# {event['user']}のコメント: 「{event['text']}」"

                elif event["type"] == "gift":
                    g_name = event["gift_name"]
                    if g_name in self.gift_to_mode:
                        mode_id = self.gift_to_mode[g_name]
                        self.gift_queue.append((mode_id, event["user"], g_name))
                        self.add_log(f"🎁 受領(予約): {g_name} ({event['user']})")
                        # AIに予約を伝える
                        mode_name = self.personality_library[mode_id]["name"]
                        self.pending_context += f"\n# 重要：{event['user']}から{g_name}受領。次は「{mode_name}」に切り替えると宣言し感謝せよ。"
                    else:
                        self.add_log(f"🎁 受領: {event['user']}から{g_name}")
                        self.pending_context += f"\n# {event['user']}から{g_name}を受信。感謝を。"

                elif event["type"] == "join_bulk":
                    self.pending_context += f"\n# {event['count']}名が入室（{event['users']}ら）。挨拶して。"
                
                elif event["type"] == "follow":
                    self.pending_context += f"\n# 新規フォロワー：{event['user']}さん。感謝を述べて。"
            # --- B. ジャックの切り替え判定（発話が終わるまで待つ） ---
            if not self.voice.is_speaking:
                # 1. 新しいギフトを適用するか？
                if now >= self.override_expiry and self.gift_queue:
                    next_mode, g_user, g_name = self.gift_queue.pop(0)
                    self.override_mode_id = next_mode
                    self.override_expiry = now + 60
                    self.add_log(f">>> モード切替中: {self.personality_library[next_mode]['name']} (ジャック者：{g_user})")
                    self.pending_context += f"\n# 【システム】ここから人格を「{self.personality_library[next_mode]['name']}」に切り替えろ。"                
                
                # 2. ジャック期間が終了したか？
                elif now >= self.override_expiry and self.override_mode_id:
                    self.add_log(">>> ジャック終了。標準OSに戻ります")
                    self.pending_context += f"\n# 【システム】ここから人格を「{self.personality_library['normal']['name']}」に切り替えろ。"
                    self.override_mode_id = None

            # --- C. ダッシュボードデータの更新（常に最新を反映） ---
            active_id = self.override_mode_id if now < self.override_expiry else self.tiktok.current_patch_id
            config = self.personality_library[active_id]
            
            dashboard_data["active_mode"] = config["name"]
            dashboard_data["timer"] = int(max(0, self.override_expiry - now))
            dashboard_data["queue"] = self.gift_queue

            # --- D. 生成・発話フェーズ（話が終わっている時だけ） ---
            if not self.voice.is_speaking and not getattr(self, 'is_generating', False):
                frame = self.capturer.get_frame_bytes()
                if frame:
                    sys_prompt = self.build_system_prompt(active_id)
                    # 【解決③】レスポンス高速化のための追加指示
                    speed_instruction = "\n※レスポンスを早めるため、3秒〜5秒程度（40文字以内）で簡潔に話せ。"
                    current_context = self.pending_context
                    self.pending_context = ""

                    # フラグを立てて、二重にスレッドが立つのを防ぐ
                    self.is_generating = True
                    # 【重要】生成処理を非同期（Thread）で実行
                    threading.Thread(
                        target=self.process_ai_task, 
                        args=(frame, sys_prompt, speed_instruction, current_context),
                        daemon=True
                    ).start()

            time.sleep(0.1)

    def process_ai_task(self, frame, sys_prompt, speed_instruction, context):
        """重い生成処理を別スレッドで実行する"""
        try:
            comment = self.ai.generate_comment(
                frame, 
                system_prompt=sys_prompt + speed_instruction, 
                extra_context=context
            )
            if comment:
                self.add_log(f"🎙️ {comment}")
                self.voice.speak(comment)
        finally:
            # 成功しても失敗しても、最後に必ずフラグを折る
            self.is_generating = False

    def build_system_prompt(self, mode_id):
        """モードに応じて人格の『土台』を動的に生成する"""
        config = self.personality_library.get(mode_id, self.personality_library["normal"])
        self.voice.current_speed = config["speed"]
        self.voice.current_pitch = config["pitch"]

        common = ("# Constraints\n- 1回の発言は30〜60文字程度。\n- 独白スタイル。叫ばない。\n- 実況します等のメタ発言禁止。\n")

        return f"{config['prompt']}\n{common}"
    
    
# --- Logic 5: TikTok 監視担当 ---
class TikTokListener:
    def __init__(self, unique_id):
        self.client = TikTokLiveClient(unique_id=unique_id)
        self.event_queue = queue.Queue()
        self.current_patch_id = "normal"
        self.join_buffer = [] # 入室者の名前を溜めるリスト
        self.last_join_time = time.time()
        self._setup_events() # 【重要】これを呼ばないとイベントを拾いません

    def _setup_events(self):
        @self.client.on(ConnectEvent)
        async def on_connect(event: ConnectEvent):
            dashboard_data["is_online"] = True

        @self.client.on(CommentEvent)
        async def on_comment(event: CommentEvent):
            self.event_queue.put({"type": "comment", "user": event.user.nickname, "text": event.comment})

        @self.client.on(JoinEvent)
        async def on_join(event: JoinEvent):
            self.join_buffer.append(event.user.nickname)
        
        @self.client.on(GiftEvent)
        async def on_gift(event: GiftEvent):
            print(f"ID: {event.gift.info.gift_id} | Name: {event.gift.info.name}")
            self.event_queue.put({
                "type": "gift", "user": event.user.nickname, 
                "gift_name": event.gift.info.name
            })

        @self.client.on(FollowEvent)
        async def on_follow(event: FollowEvent):
            self.event_queue.put({"type": "follow", "user": event.user.nickname})

    def run_forever(self):
        while True:
            try:
                self.client.run()
            except Exception:
                dashboard_data["is_online"] = False
                time.sleep(15)

    def fetch_events(self): # 複数形に変更
        events = []
        
        # 1. キューにあるイベントを全部出す
        while not self.event_queue.empty():
            events.append(self.event_queue.get_nowait())

        # 2. 入室バッファの判定
        now = time.time()
        if self.join_buffer and (len(self.join_buffer) >= 3 or (now - self.last_join_time > 10)):
            users = ", ".join(self.join_buffer)
            count = len(self.join_buffer)
            events.append({"type": "join_bulk", "users": users, "count": count})
            self.join_buffer = []
            self.last_join_time = now
            
        return events
    
# --- 実行セクション ---
if __name__ == "__main__":
    # 設定値
    API_KEY = os.getenv("API_KEY")

    TIKTOK_UNIQUE_ID = os.getenv("TIKTOK_UNIQUE_ID")
    client = TikTokLiveClient(unique_id=TIKTOK_UNIQUE_ID)
    
    # インスタンス化
    cap = MinecraftCapturer()
    ai = AICommentator(API_KEY, "gemini-2.5-flash-lite")
    vox = VoicevoxOutput("http://127.0.0.1:50021", 63)
    tiktok = TikTokListener(unique_id=TIKTOK_UNIQUE_ID)
    # 実行
    stream_manager = StreamManager(cap, ai, vox, tiktok)
    stream_manager.run()
