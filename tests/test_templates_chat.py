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
        self.calls = 0
        self.providers = [{"name": "fake-model"}]

    def chat(self, system_prompt, user_message, **kw):
        r = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        return r


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
