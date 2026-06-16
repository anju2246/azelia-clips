"""Tests for ProfileManager.ensure_initialized (T2 — migración del árbol legacy).

All tests are expected to FAIL until the GREEN-phase implementation lands.
They use ``tmp_path`` as a fake azelia home and NEVER touch the real ~/.azelia.
"""

import os

import pytest

from packages.core.profiles import ProfileManager


def _make_legacy(home, podcast_name=None):
    """Create a fake legacy ~/.azelia/data tree with a marker file."""
    legacy = home / "data"
    (legacy / "jobs").mkdir(parents=True)
    (legacy / "jobs" / "marker.txt").write_text("keep me")
    if podcast_name is not None:
        (legacy / "secrets.env").write_text(f"PODCAST_NAME={podcast_name}\n")
    return legacy


def test_migrates_legacy_data_with_podcast_name(tmp_path):
    legacy = _make_legacy(tmp_path, "My Show")
    pm = ProfileManager(tmp_path)
    pm.ensure_initialized(legacy_data_dir=legacy)

    active = pm.active()
    assert active.name == "My Show"
    assert active.id == "my-show"
    # data physically moved under profiles/, legacy gone, marker preserved
    moved = tmp_path / "profiles" / "my-show"
    assert active.data_dir == str(moved)
    assert (moved / "jobs" / "marker.txt").read_text() == "keep me"
    assert not legacy.exists()


def test_default_name_inminente_when_unnamed(tmp_path):
    legacy = _make_legacy(tmp_path, "My Podcast")  # placeholder default
    pm = ProfileManager(tmp_path)
    pm.ensure_initialized(legacy_data_dir=legacy)
    assert pm.active().name == "Inminente"


def test_respects_azelia_data_dir_override_in_place(tmp_path):
    override = tmp_path / "custom-data"
    (override).mkdir()
    (override / "secrets.env").write_text("PODCAST_NAME=Override Cast\n")
    pm = ProfileManager(tmp_path)
    pm.ensure_initialized(override_data_dir=override)

    active = pm.active()
    assert active.name == "Override Cast"
    assert active.data_dir == str(override)
    # in-place: not moved under profiles/, original dir still there
    assert override.exists()
    assert not (tmp_path / "profiles" / "override-cast").exists()


def test_creates_empty_inminente_when_no_legacy(tmp_path):
    pm = ProfileManager(tmp_path)
    pm.ensure_initialized()
    active = pm.active()
    assert active.name == "Inminente"
    assert (tmp_path / "profiles" / "inminente").is_dir()


def test_ensure_initialized_idempotent(tmp_path):
    legacy = _make_legacy(tmp_path, "My Show")
    pm = ProfileManager(tmp_path)
    pm.ensure_initialized(legacy_data_dir=legacy)
    first_active = pm.active().id

    # second call is a no-op: same active, still exactly one profile
    pm.ensure_initialized(legacy_data_dir=legacy)
    assert pm.active().id == first_active
    assert len(pm.list()) == 1


def test_registry_not_written_on_move_failure(tmp_path, monkeypatch):
    legacy = _make_legacy(tmp_path, "My Show")
    pm = ProfileManager(tmp_path)

    def boom(*a, **k):
        raise OSError("disk gone")

    monkeypatch.setattr(os, "rename", boom)
    with pytest.raises(OSError):
        pm.ensure_initialized(legacy_data_dir=legacy)

    # registry must not exist — next boot retries cleanly
    assert not pm.registry_path.exists()
