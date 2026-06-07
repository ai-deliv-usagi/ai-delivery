import json
import logging


class NullStreamStateStore:
    def load(self):
        return None

    def save(self, _state):
        return None


class GcsStreamStateStore:
    def __init__(self, bucket_name, blob_name="state/stream-session.json"):
        self.bucket_name = bucket_name
        self.blob_name = blob_name
        self._bucket = None

    def _get_blob(self):
        if self._bucket is None:
            from google.cloud import storage

            self._bucket = storage.Client().bucket(self.bucket_name)
        return self._bucket.blob(self.blob_name)

    def load(self):
        blob = self._get_blob()
        if not blob.exists():
            return None
        return json.loads(blob.download_as_text(encoding="utf-8"))

    def save(self, state):
        blob = self._get_blob()
        blob.upload_from_string(
            json.dumps(state, ensure_ascii=False),
            content_type="application/json",
        )


class SafeStreamStateStore:
    def __init__(self, store):
        self.store = store

    def load(self):
        try:
            return self.store.load()
        except Exception as exc:
            logging.warning("Stream state load failed: %s", exc)
            return None

    def save(self, state):
        try:
            self.store.save(state)
        except Exception as exc:
            logging.warning("Stream state save failed: %s", exc)
