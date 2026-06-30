import importlib
import sys
import types


def import_local_agent_main(monkeypatch, get_busy=lambda: False):
    music = types.SimpleNamespace(
        load=lambda *_args, **_kwargs: None,
        play=lambda *_args, **_kwargs: None,
        get_busy=get_busy,
        stop=lambda: None,
        unload=lambda: None,
    )
    pygame = types.ModuleType("pygame")
    pygame.mixer = types.SimpleNamespace(init=lambda: None, music=music)
    monkeypatch.setitem(sys.modules, "pygame", pygame)

    tiktok_listener = types.ModuleType("local_agent.tiktok.listener")
    tiktok_listener.LocalTikTokListener = lambda *_args, **_kwargs: None
    sys.modules.pop("local_agent.tiktok.listener", None)
    monkeypatch.setitem(sys.modules, "local_agent.tiktok.listener", tiktok_listener)

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

    sys.modules.pop("local_agent.main", None)
    return importlib.import_module("local_agent.main")


def test_audio_player_play_is_non_blocking(monkeypatch):
    module = import_local_agent_main(monkeypatch)
    logs = []
    player = module.AudioPlayer(log_func=logs.append)

    assert player.play(b"wav-bytes") is True
    player.stop()

    assert any("Playing audio" in entry for entry in logs)


def test_audio_player_rejects_empty_audio(monkeypatch):
    module = import_local_agent_main(monkeypatch)
    player = module.AudioPlayer(log_func=lambda _message: None)

    assert player.play(None) is False
