import importlib
import sys
import types

import pytest


def _install_stub_modules(monkeypatch):
    pygame = types.ModuleType("pygame")
    pygame.mixer = types.SimpleNamespace(
        init=lambda: None,
        music=types.SimpleNamespace(
            load=lambda *_args, **_kwargs: None,
            play=lambda *_args, **_kwargs: None,
            get_busy=lambda: False,
            stop=lambda: None,
            unload=lambda: None,
        ),
    )
    monkeypatch.setitem(sys.modules, "pygame", pygame)

    monkeypatch.setitem(sys.modules, "pyfiglet", types.ModuleType("pyfiglet"))

    pygetwindow = types.ModuleType("pygetwindow")
    pygetwindow.getWindowsWithTitle = lambda _title: []
    monkeypatch.setitem(sys.modules, "pygetwindow", pygetwindow)

    mss_module = types.ModuleType("mss")
    mss_module.mss = lambda: types.SimpleNamespace(grab=lambda _monitor: None)
    monkeypatch.setitem(sys.modules, "mss", mss_module)

    pil_module = types.ModuleType("PIL")
    image_module = types.ModuleType("PIL.Image")
    image_module.frombytes = lambda *_args, **_kwargs: None
    monkeypatch.setitem(sys.modules, "PIL", pil_module)
    monkeypatch.setitem(sys.modules, "PIL.Image", image_module)

    google_module = types.ModuleType("google")
    genai_module = types.ModuleType("google.genai")
    genai_module.Client = lambda *_args, **_kwargs: types.SimpleNamespace(
        chats=types.SimpleNamespace(
            create=lambda *_args, **_kwargs: types.SimpleNamespace(
                send_message=lambda *_args, **_kwargs: types.SimpleNamespace(text="")
            )
        )
    )
    genai_module.types = types.SimpleNamespace(
        Part=types.SimpleNamespace(from_bytes=lambda **kwargs: kwargs),
        GenerateContentConfig=lambda **kwargs: kwargs,
    )
    google_module.genai = genai_module
    monkeypatch.setitem(sys.modules, "google", google_module)
    monkeypatch.setitem(sys.modules, "google.genai", genai_module)

    tiktok_module = types.ModuleType("TikTokLive")

    class FakeTikTokLiveClient:
        def __init__(self, unique_id=None):
            self.unique_id = unique_id
            self.handlers = []

        def on(self, event_type):
            def decorator(func):
                self.handlers.append((event_type, func))
                return func

            return decorator

        def run(self):
            return None

    tiktok_module.TikTokLiveClient = FakeTikTokLiveClient
    events_module = types.ModuleType("TikTokLive.events")
    for name in (
        "CommentEvent",
        "ConnectEvent",
        "JoinEvent",
        "GiftEvent",
        "FollowEvent",
        "PollEvent",
    ):
        setattr(events_module, name, type(name, (), {}))
    monkeypatch.setitem(sys.modules, "TikTokLive", tiktok_module)
    monkeypatch.setitem(sys.modules, "TikTokLive.events", events_module)

    colorama_module = types.ModuleType("colorama")
    colorama_module.init = lambda *_args, **_kwargs: None
    colorama_module.Cursor = types.SimpleNamespace()
    colorama_module.Fore = types.SimpleNamespace()
    colorama_module.Style = types.SimpleNamespace()
    monkeypatch.setitem(sys.modules, "colorama", colorama_module)

    dotenv_module = types.ModuleType("dotenv")
    dotenv_module.load_dotenv = lambda *_args, **_kwargs: None
    monkeypatch.setitem(sys.modules, "dotenv", dotenv_module)


@pytest.fixture()
def app_module(monkeypatch):
    _install_stub_modules(monkeypatch)
    sys.modules.pop("app", None)
    module = importlib.import_module("app")
    module.dashboard_data.update(
        {
            "active_mode": "Initializing...",
            "timer": 0,
            "queue": [],
            "logs": [],
            "is_online": False,
        }
    )
    module.stream_manager = None
    return module


@pytest.fixture()
def client(app_module):
    app_module.app.config.update(TESTING=True)
    return app_module.app.test_client()

