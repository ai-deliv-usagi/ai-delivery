from google import genai
from google.genai import types


class AICommentator:
    def __init__(self, model_id, project_id, location):
        self.client = genai.Client(
            vertexai=True,
            project=project_id,
            location=location,
        )
        self.model_id = model_id
        self.history = []
        self.chat = self.client.chats.create(model=self.model_id)

    def generate_comment(self, image_data, system_prompt="", extra_context=""):
        history_text = "\n".join([f"- {h}" for h in self.history[-5:]])
        full_prompt = (
            f"{system_prompt}\n\n"
            f"## Recent logs:\n{history_text}\n\n"
            f"{extra_context}"
        )

        try:
            response = self.chat.send_message(
                [
                    types.Part.from_bytes(data=image_data, mime_type="image/jpg"),
                    full_prompt,
                ],
                config=types.GenerateContentConfig(temperature=1.0),
            )
            comment = response.text.strip()
            self.history.append(comment)
            if len(self.history) > 10:
                self.history.pop(0)
            return comment
        except Exception as exc:
            print(f"AI generation error: {exc}")
            return None
