"""Tests for the profile→config→llm_provider integration (T4).

All tests are expected to FAIL until the GREEN-phase implementation lands.
data_dir resolution is tested as a pure function (NOT the import-time singleton,
which must never mutate the real ~/.azelia). The Claude binary/env wiring is
tested by capturing subprocess.run args.
"""

from pathlib import Path

from packages.core.profiles import ProfileManager


# ── data_dir resolution ──────────────────────────────────────────────────


def test_data_dir_resolves_active_profile(tmp_path):
    from packages.core import config

    pm = ProfileManager(tmp_path)
    pm.create("A")
    b = pm.create("B")
    pm.set_active(b.id)

    resolved = config._resolve_data_dir(tmp_path, None)
    assert resolved == tmp_path / "profiles" / "b"


def test_azelia_data_dir_override_wins(tmp_path):
    from packages.core import config

    override = tmp_path / "custom"
    resolved = config._resolve_data_dir(tmp_path, str(override))
    assert resolved == override


def test_resolve_falls_back_to_legacy_without_registry(tmp_path):
    from packages.core import config

    # no registry yet → legacy path, and NO migration side effect
    resolved = config._resolve_data_dir(tmp_path, None)
    assert resolved == tmp_path / "data"
    assert not (tmp_path / "profiles.json").exists()


# ── Claude binary + CLAUDE_CONFIG_DIR wiring ───────────────────────────────


class _FakeCompleted:
    returncode = 0
    stdout = "ok"
    stderr = ""


def _capture_run(monkeypatch):
    from packages.core import llm_provider

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return _FakeCompleted()

    monkeypatch.setattr(llm_provider.subprocess, "run", fake_run)
    return llm_provider, captured


def test_call_claude_code_uses_profile_binary(monkeypatch):
    llm_provider, captured = _capture_run(monkeypatch)
    from packages.core.config import settings

    monkeypatch.setattr(settings, "claude_binary", "/custom/claude", raising=False)
    monkeypatch.setattr(settings, "claude_config_dir", None, raising=False)

    # _call_claude_code does not use `self`; pass None
    llm_provider.MultiProviderLLM._call_claude_code(None, {"type": "claude_code"}, "sys", "msg", 0.5)
    assert captured["cmd"][0] == "/custom/claude"
    assert "-p" in captured["cmd"]


def test_call_claude_code_defaults_to_claude_when_unset(monkeypatch):
    llm_provider, captured = _capture_run(monkeypatch)
    from packages.core.config import settings

    monkeypatch.setattr(settings, "claude_binary", None, raising=False)
    monkeypatch.setattr(settings, "claude_config_dir", None, raising=False)

    llm_provider.MultiProviderLLM._call_claude_code(None, {"type": "claude_code"}, "sys", "msg", 0.5)
    assert captured["cmd"][0] == "claude"


def test_call_claude_code_passes_config_dir_env(monkeypatch):
    llm_provider, captured = _capture_run(monkeypatch)
    from packages.core.config import settings

    monkeypatch.setattr(settings, "claude_binary", None, raising=False)
    monkeypatch.setattr(settings, "claude_config_dir", "/cfg/dir", raising=False)

    llm_provider.MultiProviderLLM._call_claude_code(None, {"type": "claude_code"}, "sys", "msg", 0.5)
    env = captured["kwargs"].get("env")
    assert env is not None
    assert env["CLAUDE_CONFIG_DIR"] == "/cfg/dir"


def test_no_circular_import():
    # importing all three in any order must not raise
    import importlib

    for mod in ("packages.core.profiles", "packages.core.config", "packages.core.llm_provider"):
        importlib.import_module(mod)
