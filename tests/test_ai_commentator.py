import json
import types


def test_ai_commentator_uses_vertex_ai_client(app_module, monkeypatch):
    from cloud_app.ai import gemini_commentator

    captured = {}

    def make_client(**kwargs):
        captured.update(kwargs)
        return types.SimpleNamespace()

    monkeypatch.setattr(gemini_commentator.genai, "Client", make_client)

    gemini_commentator.AICommentator(
        model_id="gemini-test",
        project_id="project-test",
        location="global",
    )

    assert captured == {
        "vertexai": True,
        "project": "project-test",
        "location": "global",
    }


def test_ai_commentator_sends_rules_as_system_instruction(app_module, monkeypatch):
    from cloud_app.ai import gemini_commentator

    calls = []

    class FakeModels:
        def generate_content(self, **kwargs):
            calls.append(kwargs)
            return types.SimpleNamespace(text="fresh angle")

    def make_client(**_kwargs):
        return types.SimpleNamespace(models=FakeModels())

    monkeypatch.setattr(gemini_commentator.genai, "Client", make_client)
    commentator = gemini_commentator.AICommentator(
        model_id="gemini-test",
        project_id="project-test",
        location="global",
    )
    commentator.history = ["old spoken line"]

    comment = commentator.generate_comment(
        b"image",
        system_prompt="personality rules",
        extra_context="# viewer comment: hello",
    )

    assert comment == "fresh angle"
    config = calls[0]["config"]
    user_context = json.loads(calls[0]["contents"][-1])
    assert config["system_instruction"].startswith("personality rules")
    assert "Return only one exact spoken line" in config["system_instruction"]
    assert "recent_spoken_lines" not in config["system_instruction"]
    assert user_context == {
        "recent_spoken_lines": ["old spoken line"],
        "viewer_and_event_context": "# viewer comment: hello",
    }


def test_ai_commentator_retries_when_comment_repeats_recent_history(
    app_module, monkeypatch
):
    from cloud_app.ai import gemini_commentator

    calls = []
    responses = iter(
        [
            types.SimpleNamespace(text="same comment"),
            types.SimpleNamespace(text="fresh angle"),
        ]
    )

    class FakeModels:
        def generate_content(self, **kwargs):
            calls.append(kwargs)
            return next(responses)

    def make_client(**_kwargs):
        return types.SimpleNamespace(models=FakeModels())

    monkeypatch.setattr(gemini_commentator.genai, "Client", make_client)
    commentator = gemini_commentator.AICommentator(
        model_id="gemini-test",
        project_id="project-test",
        location="global",
    )
    commentator.history = ["same comment"]

    comment = commentator.generate_comment(b"image", system_prompt="system")

    assert comment == "fresh angle"
    assert len(calls) == 2
    assert "Rewrite requirement" not in calls[0]["config"]["system_instruction"]
    assert "Rewrite requirement" in calls[1]["config"]["system_instruction"]
    assert commentator.history[-1] == "fresh angle"


def test_ai_commentator_retries_when_any_overused_topic_returns(
    app_module, monkeypatch
):
    from cloud_app.ai import gemini_commentator

    calls = []
    responses = iter(
        [
            types.SimpleNamespace(text="crimson forest is still filling the screen"),
            types.SimpleNamespace(text="the route choice feels tense now"),
        ]
    )

    class FakeModels:
        def generate_content(self, **kwargs):
            calls.append(kwargs)
            return next(responses)

    def make_client(**_kwargs):
        return types.SimpleNamespace(models=FakeModels())

    monkeypatch.setattr(gemini_commentator.genai, "Client", make_client)
    commentator = gemini_commentator.AICommentator(
        model_id="gemini-test",
        project_id="project-test",
        location="global",
    )
    commentator.history = [
        "crimson forest covers everything here",
        "still staring at this crimson forest",
    ]

    comment = commentator.generate_comment(b"image", system_prompt="system")

    assert comment == "the route choice feels tense now"
    assert len(calls) == 2
    assert "Topic fatigue" in calls[0]["config"]["system_instruction"]
    assert "Rewrite requirement" in calls[1]["config"]["system_instruction"]
    assert commentator.history[-1] == "the route choice feels tense now"


def test_ai_commentator_retries_when_model_outputs_transcript(app_module, monkeypatch):
    from cloud_app.ai import gemini_commentator

    calls = []
    transcript = (
        "AI\u5b9f\u6cc1\uff1ahello\n"
        "\uff08\u30b3\u30e1\u30f3\u30c8\uff09bug happened\n"
        "\uff08\u30b3\u30e1\u30f3\u30c8\uff09bug happened"
    )
    responses = iter(
        [
            types.SimpleNamespace(text=transcript),
            types.SimpleNamespace(text="The footing looks risky, so slow down here."),
        ]
    )

    class FakeModels:
        def generate_content(self, **kwargs):
            calls.append(kwargs)
            return next(responses)

    def make_client(**_kwargs):
        return types.SimpleNamespace(models=FakeModels())

    monkeypatch.setattr(gemini_commentator.genai, "Client", make_client)
    commentator = gemini_commentator.AICommentator(
        model_id="gemini-test",
        project_id="project-test",
        location="global",
    )

    comment = commentator.generate_comment(b"image", system_prompt="system")

    assert comment == "The footing looks risky, so slow down here."
    assert len(calls) == 2
    assert "transcripts" in calls[0]["config"]["system_instruction"]
    assert "Rewrite requirement" in calls[1]["config"]["system_instruction"]
    assert commentator.history == ["The footing looks risky, so slow down here."]


def test_ai_commentator_sanitizes_label_and_clips_long_comment(app_module):
    from cloud_app.ai.gemini_commentator import AICommentator

    comment = "AI\u5b9f\u6cc1\uff1a" + ("Proceed carefully here. " * 20)

    sanitized = AICommentator.sanitize_comment(comment)

    assert not sanitized.startswith("AI")
    assert len(sanitized) <= AICommentator.max_comment_chars


def test_ai_commentator_keeps_bounded_recent_history(app_module, monkeypatch):
    from cloud_app.ai import gemini_commentator

    class FakeModels:
        def generate_content(self, **_kwargs):
            return types.SimpleNamespace(text="new comment")

    def make_client(**_kwargs):
        return types.SimpleNamespace(models=FakeModels())

    monkeypatch.setattr(gemini_commentator.genai, "Client", make_client)
    commentator = gemini_commentator.AICommentator(
        model_id="gemini-test",
        project_id="project-test",
        location="global",
    )
    commentator.history = [f"old-{index}" for index in range(commentator.max_history)]

    commentator.generate_comment(b"image")

    assert commentator.history == [
        *[f"old-{index}" for index in range(1, commentator.max_history)],
        "new comment",
    ]
