"""Tests for ProfileManager (T1 — núcleo de perfiles: registry + slug + CRUD).

All tests are expected to FAIL until the GREEN-phase implementation lands.
They use ``tmp_path`` as a fake azelia home and NEVER touch the real ~/.azelia.
Migration / ensure_initialized is T2 and is intentionally not tested here.
"""

import pytest

from packages.core.profiles import ProfileError, ProfileManager


# ── create / slug ────────────────────────────────────────────────────────


def test_create_profile_generates_slug_and_dirs(tmp_path):
    pm = ProfileManager(tmp_path)
    p = pm.create("Mi Podcast")

    assert p.id == "mi-podcast"
    assert p.name == "Mi Podcast"
    assert (tmp_path / "profiles" / "mi-podcast" / "jobs").is_dir()

    secrets = (tmp_path / "profiles" / "mi-podcast" / "secrets.env").read_text()
    assert "PODCAST_NAME=Mi Podcast" in secrets


def test_create_collision_appends_suffix(tmp_path):
    pm = ProfileManager(tmp_path)
    pm.create("Mi Podcast")
    p2 = pm.create("Mi Podcast")
    assert p2.id == "mi-podcast-2"


@pytest.mark.parametrize("bad_name", ["", "   ", "x" * 65, "!!!"])
def test_invalid_name_rejected(tmp_path, bad_name):
    pm = ProfileManager(tmp_path)
    with pytest.raises(ProfileError):
        pm.create(bad_name)


# ── delete guards ──────────────────────────────────────────────────────────


def test_delete_active_profile_rejected(tmp_path):
    pm = ProfileManager(tmp_path)
    a = pm.create("Podcast A")
    pm.create("Podcast B")
    pm.set_active(a.id)
    with pytest.raises(ProfileError):
        pm.delete(a.id)


def test_delete_last_profile_rejected(tmp_path):
    pm = ProfileManager(tmp_path)
    only = pm.create("Solo")
    with pytest.raises(ProfileError):
        pm.delete(only.id)


def test_delete_with_data_only_under_profiles_dir(tmp_path):
    pm = ProfileManager(tmp_path)
    keep = pm.create("Keep")
    drop = pm.create("Drop")
    pm.set_active(keep.id)

    drop_dir = tmp_path / "profiles" / "drop"
    assert drop_dir.is_dir()

    pm.delete(drop.id, delete_data=True)
    assert not drop_dir.exists()
    # the kept profile's data must remain untouched
    assert (tmp_path / "profiles" / "keep").is_dir()


# ── active pointer + persistence ────────────────────────────────────────────


def test_set_active_persists_and_atomic_write(tmp_path):
    pm = ProfileManager(tmp_path)
    pm.create("A")
    b = pm.create("B")
    pm.set_active(b.id)

    assert pm.active().id == b.id
    assert (tmp_path / "profiles.json").exists()

    # a fresh manager reads back the same active pointer
    pm2 = ProfileManager(tmp_path)
    assert pm2.active().id == b.id


def test_registry_roundtrip_survives_reload(tmp_path):
    pm = ProfileManager(tmp_path)
    pm.create("One")
    pm.create("Two")

    pm2 = ProfileManager(tmp_path)
    ids = {p.id for p in pm2.list()}
    assert {"one", "two"} <= ids
