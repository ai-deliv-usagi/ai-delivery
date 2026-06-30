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
