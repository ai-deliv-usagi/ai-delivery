from cloud_app.voice.voicevox import VoicevoxOutput


def test_prepare_text_caps_voicevox_input_length():
    voice = VoicevoxOutput("http://voicevox.example", speaker_id=1, max_text_chars=10)

    assert voice.prepare_text("123456789012345") == "1234567890。"


def test_prepare_text_keeps_short_text_unchanged():
    voice = VoicevoxOutput("http://voicevox.example", speaker_id=1, max_text_chars=10)

    assert voice.prepare_text("hello") == "hello"
