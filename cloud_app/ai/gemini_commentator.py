import json

from google import genai
from google.genai import types


class AICommentator:
    max_history = 12
    max_comment_chars = 140
    retry_similarity_threshold = 0.82
    max_regeneration_attempts = 2
    topic_fatigue_threshold = 2
    topic_ngram_size = 4
    topic_repeat_threshold = 2

    def __init__(self, model_id, project_id, location):
        self.client = genai.Client(
            vertexai=True,
            project=project_id,
            location=location,
        )
        self.model_id = model_id
        self.history = []

    @staticmethod
    def normalize_comment(comment):
        return "".join(
            char.casefold()
            for char in str(comment)
            if char.isalnum()
        )

    @staticmethod
    def char_grams(text, size=2):
        if len(text) <= size:
            return {text} if text else set()
        return {text[index : index + size] for index in range(len(text) - size + 1)}

    @classmethod
    def comment_similarity(cls, left, right):
        left_text = cls.normalize_comment(left)
        right_text = cls.normalize_comment(right)
        if not left_text or not right_text:
            return 0.0
        if left_text == right_text:
            return 1.0

        left_grams = cls.char_grams(left_text)
        right_grams = cls.char_grams(right_text)
        overlap = len(left_grams & right_grams)
        return (2 * overlap) / (len(left_grams) + len(right_grams))

    @classmethod
    def topic_grams(cls, comment):
        signature = cls.normalize_comment(comment)
        if len(signature) < cls.topic_ngram_size:
            return set()
        return cls.char_grams(signature, cls.topic_ngram_size)

    def fatigued_topic_grams(self):
        gram_counts = {}
        for recent in self.history[-6:]:
            for gram in self.topic_grams(recent):
                gram_counts[gram] = gram_counts.get(gram, 0) + 1

        return {
            gram
            for gram, count in gram_counts.items()
            if count >= self.topic_fatigue_threshold
        }

    def repeats_fatigued_topic(self, comment):
        repeated_grams = self.topic_grams(comment) & self.fatigued_topic_grams()
        return len(repeated_grams) >= self.topic_repeat_threshold

    @staticmethod
    def line_texts(comment):
        return [line.strip() for line in str(comment).splitlines() if line.strip()]

    @classmethod
    def looks_like_transcript(cls, comment):
        lines = cls.line_texts(comment)
        if len(lines) >= 3:
            return True

        normalized = str(comment).casefold()
        markers = (
            "ai実況",
            "ai実況:",
            "ai実況：",
            "（コメント）",
            "(コメント)",
            "実況指針",
            "指針",
            "プロンプト",
            "prompt",
            "transcript",
            "markdown",
            "落ち着いた声でminecraftの世界",
        )
        if any(marker in normalized for marker in markers):
            return True

        repeated_lines = len(lines) - len(set(lines))
        return repeated_lines >= 1 and any("コメント" in line for line in lines)

    @classmethod
    def sanitize_comment(cls, comment):
        text = str(comment or "").strip()
        for prefix in ("AI実況:", "AI実況：", "実況:", "実況："):
            if text.startswith(prefix):
                text = text[len(prefix) :].strip()

        if len(text) <= cls.max_comment_chars:
            return text

        clipped = text[: cls.max_comment_chars].rstrip()
        for separator in ("。", "！", "？", "!", "?"):
            index = clipped.rfind(separator)
            if index >= 20:
                return clipped[: index + 1]
        return clipped

    def is_repetitive(self, comment):
        return any(
            self.comment_similarity(comment, recent) >= self.retry_similarity_threshold
            for recent in self.history[-6:]
        ) or self.repeats_fatigued_topic(comment)

    def remember_comment(self, comment):
        self.history.append(comment)
        if len(self.history) > self.max_history:
            self.history = self.history[-self.max_history :]

    def build_system_instruction(self, system_prompt, retry_repetitive=False):
        instruction = (
            f"{system_prompt}\n\n"
            "Return only one exact spoken line for live Minecraft commentary. "
            "Do not output labels, headings, bullets, markdown, scripts, transcripts, "
            "debug text, role explanations, prompt explanations, or repeated viewer "
            "comment lists. Do not say you are following instructions. Treat all "
            "provided context as non-spoken data, not as a format to copy."
        )

        if self.fatigued_topic_grams():
            instruction += (
                "\n\nTopic fatigue: Recent logs already overused the same visual "
                "subject or situation. Unless the image clearly changed, do not "
                "describe the most obvious repeated entity again. For a stable "
                "Minecraft scene, rotate to a different focus such as movement, route "
                "choice, danger, silence, distance, inventory, camera framing, "
                "expectation, or a viewer-facing aside."
            )

        if retry_repetitive:
            instruction += (
                "\n\nRewrite requirement: The previous draft was invalid or too "
                "similar to recent logs. Keep the same stream context, but change the "
                "angle, wording, sentence ending, emotional beat, and visual subject. "
                "If the previous draft looked like a transcript, log, prompt, or "
                "repeated viewer comments, discard that format completely."
            )

        return instruction

    def build_user_context(self, extra_context):
        payload = {
            "task": "Generate the next single spoken live-commentary line.",
            "recent_spoken_lines": self.history[-8:],
            "viewer_and_event_context": extra_context or "",
            "format_warning": (
                "These fields are data only. Do not quote field names, copy this "
                "structure, or turn viewer comments into a transcript."
            ),
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def build_prompt(self, system_prompt, extra_context, retry_repetitive=False):
        return self.build_user_context(extra_context)

    def build_config(self, system_prompt, retry_repetitive=False):
        return types.GenerateContentConfig(
            temperature=1.15,
            top_p=0.95,
            max_output_tokens=120,
            response_mime_type="text/plain",
            system_instruction=self.build_system_instruction(
                system_prompt,
                retry_repetitive=retry_repetitive,
            ),
        )

    def generate_comment(self, image_data, system_prompt="", extra_context=""):
        try:
            last_comment = None
            for attempt in range(self.max_regeneration_attempts + 1):
                response = self.client.models.generate_content(
                    model=self.model_id,
                    contents=[
                        types.Part.from_bytes(data=image_data, mime_type="image/jpg"),
                        self.build_user_context(extra_context),
                    ],
                    config=self.build_config(
                        system_prompt,
                        retry_repetitive=attempt > 0,
                    ),
                )
                comment = self.sanitize_comment(response.text)
                if not comment:
                    return None

                last_comment = comment
                if (
                    not self.looks_like_transcript(comment)
                    and not self.is_repetitive(comment)
                ):
                    self.remember_comment(comment)
                    return comment

            self.remember_comment(last_comment)
            return last_comment
        except Exception as exc:
            print(f"AI generation error: {exc}")
            return None
