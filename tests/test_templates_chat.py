"""Tests for the AI template editor + chat endpoint (T5). LLM is mocked."""

import json
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from packages.clips.templates.models import ClipTemplate, LayoutSpec, SubtitleSpec


def _tmpl() -> ClipTemplate:
    now = datetime(2026, 1, 1).isoformat()
    return ClipTemplate(
        id="t", name="T", created_at=now, updated_at=now,
        subtitles=SubtitleSpec(), layout=LayoutSpec(),
    )


class FakeLLM:
    """Stand-in for MultiProviderLLM: returns canned chat() responses in order."""

    def __init__(self, responses):
        self.responses = list(responses)
        self._idx = 0
        self.calls = 0  # text chat() calls
        self.vision_calls = 0  # chat_vision() calls
        self.last_image_path = None
        self.providers = [{"name": "fake-model"}]

    def _next(self):
        r = self.responses[min(self._idx, len(self.responses) - 1)]
        self._idx += 1
        return r

    def chat(self, system_prompt, user_message, **kw):
        self.calls += 1
        return self._next()

    def chat_vision(self, system_prompt, user_message, image_path, **kw):
        self.vision_calls += 1
        self.last_image_path = image_path
        return self._next()


# A 1x1 PNG, base64.
_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


# ── ai_editor unit ───────────────────────────────────────────────────────────


def test_chat_returns_validated_template():
    from packages.clips.templates.ai_editor import edit

    base = _tmpl()
    resp = json.dumps({
        "explanation": "Lo puse rojo",
        "template": {
            "subtitles": {**base.subtitles.model_dump(), "primary_color": "&H000000FF"},
            "layout": base.layout.model_dump(),
        },
    })
    out = edit(base, [{"role": "user", "content": "ponlo rojo"}], llm=FakeLLM([resp]))

    assert out["template"].subtitles.primary_color == "&H000000FF"
    assert out["explanation"] == "Lo puse rojo"
    assert out["provider_used"] == "fake-model"
    # id / is_builtin are never taken from the model output.
    assert out["template"].id == "t"
    assert out["template"].is_builtin is False


def test_chat_retries_then_raises_on_invalid_output():
    from packages.clips.templates.ai_editor import TemplateChatError, edit

    fake = FakeLLM(["not json", "still not json"])
    with pytest.raises(TemplateChatError):
        edit(_tmpl(), [{"role": "user", "content": "x"}], llm=fake)
    assert fake.calls == 2


def test_chat_recovers_on_second_attempt():
    from packages.clips.templates.ai_editor import edit

    base = _tmpl()
    good = json.dumps({
        "explanation": "ok",
        "template": {"subtitles": base.subtitles.model_dump(), "layout": base.layout.model_dump()},
    })
    fake = FakeLLM(["garbage", good])
    out = edit(base, [{"role": "user", "content": "x"}], llm=fake)
    assert fake.calls == 2
    assert out["explanation"] == "ok"


# ── endpoint ─────────────────────────────────────────────────────────────────


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AZELIA_HOME", str(tmp_path))
    from packages.core.config import settings

    active_dir = tmp_path / "active"
    active_dir.mkdir()
    monkeypatch.setattr(settings, "data_dir", active_dir, raising=False)
    from server.app import app

    return TestClient(app)


# ── vision (T6) ──────────────────────────────────────────────────────────────


def test_edit_with_image_uses_chat_vision():
    from packages.clips.templates.ai_editor import edit

    base = _tmpl()
    good = json.dumps({
        "explanation": "copié el estilo",
        "template": {"subtitles": base.subtitles.model_dump(), "layout": base.layout.model_dump()},
    })
    fake = FakeLLM([good])
    out = edit(base, [{"role": "user", "content": "replica esto"}], image_path="/tmp/x.png", llm=fake)

    assert fake.vision_calls == 1
    assert fake.calls == 0  # text chat() not used
    assert fake.last_image_path == "/tmp/x.png"
    assert out["explanation"] == "copié el estilo"


def test_decode_reference_image_rejects_garbage():
    from packages.clips.templates.ai_editor import ImageInvalid, decode_reference_image

    with pytest.raises(ImageInvalid):
        decode_reference_image("not-base64-image!!!")


def test_chat_endpoint_image_without_vision_returns_422(client, monkeypatch):
    import packages.clips.templates.ai_editor as ae

    monkeypatch.setattr(ae, "vision_available", lambda: False)

    template = client.get("/api/templates/splitscreen").json()
    r = client.post(
        "/api/templates/chat",
        json={
            "template": template,
            "messages": [{"role": "user", "content": "replica"}],
            "image_b64": _PNG_B64,
        },
    )
    assert r.status_code == 422
    assert r.json()["detail"]["error_code"] == "VISION_UNAVAILABLE"


def test_chat_endpoint_invalid_image_returns_422(client, monkeypatch):
    import packages.clips.templates.ai_editor as ae

    monkeypatch.setattr(ae, "vision_available", lambda: True)

    template = client.get("/api/templates/splitscreen").json()
    r = client.post(
        "/api/templates/chat",
        json={
            "template": template,
            "messages": [{"role": "user", "content": "replica"}],
            "image_b64": "Zm9vYmFy",  # valid base64, not an image
        },
    )
    assert r.status_code == 422
    assert r.json()["detail"]["error_code"] == "IMAGE_INVALID"


def test_chat_endpoint_temp_image_deleted_after_call(client, monkeypatch):
    import packages.clips.templates.ai_editor as ae

    monkeypatch.setattr(ae, "vision_available", lambda: True)
    captured = {}

    def fake_edit(template, messages, image_path=None, llm=None):
        captured["path"] = image_path
        assert image_path and __import__("os").path.exists(image_path)
        return {"explanation": "ok", "template": template, "provider_used": "claude-code-cli"}

    monkeypatch.setattr(ae, "edit", fake_edit)

    template = client.get("/api/templates/splitscreen").json()
    r = client.post(
        "/api/templates/chat",
        json={
            "template": template,
            "messages": [{"role": "user", "content": "replica"}],
            "image_b64": _PNG_B64,
        },
    )
    assert r.status_code == 200
    # The temp file existed during the call but is cleaned up afterwards.
    import os

    assert not os.path.exists(captured["path"])


def test_chat_endpoint_no_provider_returns_503(client, monkeypatch):
    import packages.clips.templates.ai_editor as ae

    def boom():
        raise ValueError("No LLM providers available")

    monkeypatch.setattr(ae, "get_llm", boom)

    template = client.get("/api/templates/splitscreen").json()
    r = client.post(
        "/api/templates/chat",
        json={"template": template, "messages": [{"role": "user", "content": "hola"}]},
    )
    assert r.status_code == 503
    assert r.json()["detail"]["error_code"] == "LLM_UNAVAILABLE"
