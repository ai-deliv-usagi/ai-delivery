import base64


def test_send_frame_includes_playback_busy(monkeypatch):
    from local_agent.client.cloud_api import CloudApiClient

    calls = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"status": "busy"}

    def post(url, files, data, timeout):
        calls["url"] = url
        calls["files"] = files
        calls["data"] = data
        calls["timeout"] = timeout
        return Response()

    monkeypatch.setattr("local_agent.client.cloud_api.requests.post", post)

    result = CloudApiClient("https://example.test").send_frame(
        b"frame",
        playback_busy=True,
    )

    assert result == {"status": "busy"}
    assert calls["url"] == "https://example.test/api/frames"
    assert calls["data"] == {"playback_busy": "1"}
    assert calls["files"]["frame"][1] == b"frame"


def test_send_frame_decodes_audio(monkeypatch):
    from local_agent.client.cloud_api import CloudApiClient

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"audio_base64": base64.b64encode(b"wav").decode("ascii")}

    def post(*_args, **_kwargs):
        return Response()

    monkeypatch.setattr("local_agent.client.cloud_api.requests.post", post)

    result = CloudApiClient("https://example.test").send_frame(b"frame")

    assert result["audio_bytes"] == b"wav"
