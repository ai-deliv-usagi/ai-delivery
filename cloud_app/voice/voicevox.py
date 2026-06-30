import json
import requests


class VoicevoxOutput:
    """Cloud-side VOICEVOX adapter that synthesizes audio bytes.

    Playback belongs to the local agent. This class keeps the old `speak` and
    `stop` surface for StreamManager compatibility while exposing generated
    audio through `last_audio`.
    """

    def __init__(self, url, speaker_id, max_text_chars=240):
        self.url = url
        self.speaker_id = speaker_id
        self.max_text_chars = max_text_chars
        self.is_speaking = False
        self.current_speed = 1.0
        self.current_pitch = 0.0
        self.last_audio = None

    def prepare_text(self, text):
        text = (text or "").strip()
        if len(text) <= self.max_text_chars:
            return text
        return text[: self.max_text_chars].rstrip("、。,. ") + "。"

    def synthesize(self, text):
        text = self.prepare_text(text)
        if not text:
            return None

        query_response = requests.post(
            f"{self.url}/audio_query",
            params={"text": text, "speaker": self.speaker_id},
            timeout=30,
        )
        query_response.raise_for_status()
        query = query_response.json()
        query["volumeScale"] = 2.0
        query["speedScale"] = self.current_speed
        query["pitchScale"] = self.current_pitch

        synth_response = requests.post(
            f"{self.url}/synthesis",
            params={"speaker": self.speaker_id},
            data=json.dumps(query),
            timeout=60,
        )
        synth_response.raise_for_status()
        return synth_response.content

    def speak(self, text):
        if self.is_speaking or not text:
            return None
        self.is_speaking = True
        try:
            self.last_audio = self.synthesize(text)
            return self.last_audio
        finally:
            self.is_speaking = False

    def stop(self):
        self.is_speaking = False
