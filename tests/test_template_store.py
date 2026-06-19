"""Tests for TemplateStore persistence and builtins (T1 - RED phase).

All tests are expected to FAIL until the implementation is written.
"""

import pytest
from pathlib import Path
from datetime import datetime

from packages.clips.templates.models import ClipTemplate, SubtitleSpec, LayoutSpec
from packages.clips.templates.builtins import list_builtins, get_builtin
from packages.clips.templates.store import (
    TemplateStore,
    TemplateNotFound,
    TemplateReadOnly,
)


# ── Built-ins ────────────────────────────────────────────────────────────────


def test_list_builtins_returns_five_readonly_presets():
    """list_builtins() should return exactly 5 presets with is_builtin=True."""
    builtins = list_builtins()

    assert len(builtins) == 5, "Should have exactly 5 built-in presets"

    # Check exact slugs (from STYLES in generator.py)
    slugs = {t.id for t in builtins}
    expected_slugs = {"hormozi", "mrbeast", "minimal", "podcast", "splitscreen"}
    assert slugs == expected_slugs, f"Expected {expected_slugs}, got {slugs}"

    # All should be marked as builtin
    for template in builtins:
        assert template.is_builtin is True, f"{template.id} should be builtin"


def test_get_builtin_known_and_unknown():
    """get_builtin() should return template for known slug, None for unknown."""
    # Known builtin
    hormozi = get_builtin("hormozi")
    assert hormozi is not None
    assert hormozi.id == "hormozi"
    assert hormozi.is_builtin is True

    # Unknown slug
    unknown = get_builtin("nope")
    assert unknown is None


# ── TemplateStore ────────────────────────────────────────────────────────────


def test_store_create_persists_to_templates_dir(tmp_path):
    """create() should persist template as .azt file in templates_dir."""
    store = TemplateStore(tmp_path)
    now = datetime.utcnow().isoformat()

    template = ClipTemplate(
        id="custom-template",
        name="Custom Template",
        created_at=now,
        updated_at=now,
        subtitles=SubtitleSpec(),
        layout=LayoutSpec(),
    )

    created = store.create(template)

    # Should have created file
    expected_file = tmp_path / "custom-template.azt"
    assert expected_file.exists(), "Should create .azt file"

    # Should be retrievable
    retrieved = store.get("custom-template")
    assert retrieved.id == "custom-template"
    assert retrieved.name == "Custom Template"


def test_store_slug_collision_disambiguates(tmp_path):
    """Two create() calls with same name should get distinct slugs with -2 suffix."""
    store = TemplateStore(tmp_path)
    now = datetime.utcnow().isoformat()

    # Create first template
    template1 = ClipTemplate(
        id="my-template",
        name="My Template",
        created_at=now,
        updated_at=now,
        subtitles=SubtitleSpec(),
        layout=LayoutSpec(),
    )
    created1 = store.create(template1)

    # Create second with same name
    template2 = ClipTemplate(
        id="my-template",  # Same slug requested
        name="My Template",
        created_at=now,
        updated_at=now,
        subtitles=SubtitleSpec(),
        layout=LayoutSpec(),
    )
    created2 = store.create(template2)

    # Should have different IDs
    assert created1.id == "my-template"
    assert created2.id == "my-template-2", "Second template should have -2 suffix"

    # Both files should exist
    assert (tmp_path / "my-template.azt").exists()
    assert (tmp_path / "my-template-2.azt").exists()


def test_store_get_missing_raises_not_found(tmp_path):
    """get() on non-existent template should raise TemplateNotFound."""
    store = TemplateStore(tmp_path)

    with pytest.raises(TemplateNotFound):
        store.get("does-not-exist")


def test_store_update_builtin_raises_readonly(tmp_path):
    """update() on a builtin template should raise TemplateReadOnly."""
    store = TemplateStore(tmp_path)
    now = datetime.utcnow().isoformat()

    # Try to update a builtin
    updated = ClipTemplate(
        id="splitscreen",  # This is a builtin
        name="Modified Splitscreen",
        created_at=now,
        updated_at=now,
        subtitles=SubtitleSpec(),
        layout=LayoutSpec(),
    )

    with pytest.raises(TemplateReadOnly):
        store.update("splitscreen", updated)


def test_store_delete_builtin_raises_readonly(tmp_path):
    """delete() on a builtin template should raise TemplateReadOnly."""
    store = TemplateStore(tmp_path)

    with pytest.raises(TemplateReadOnly):
        store.delete("splitscreen")


def test_store_delete_missing_raises_not_found(tmp_path):
    """delete() on non-existent template should raise TemplateNotFound."""
    store = TemplateStore(tmp_path)

    with pytest.raises(TemplateNotFound):
        store.delete("does-not-exist")


def test_store_resolve_none_returns_splitscreen(tmp_path):
    """resolve(None) should return the splitscreen builtin."""
    store = TemplateStore(tmp_path)

    resolved = store.resolve(None)

    assert resolved is not None
    assert resolved.id == "splitscreen"
    assert resolved.is_builtin is True


def test_store_resolve_unknown_raises_not_found(tmp_path):
    """resolve() with unknown ID should raise TemplateNotFound."""
    store = TemplateStore(tmp_path)

    with pytest.raises(TemplateNotFound):
        store.resolve("unknown-template-xyz")


def test_store_rejects_path_traversal_id(tmp_path):
    """An id that isn't a clean slug must never escape templates_dir."""
    store = TemplateStore(tmp_path)
    with pytest.raises(TemplateNotFound):
        store.get("../../etc/passwd")
    with pytest.raises(TemplateNotFound):
        store.delete("../secrets")


def test_store_slug_disambiguation_stays_within_48_chars(tmp_path):
    """Long names that collide must not produce slugs that violate the id pattern."""
    from datetime import datetime

    store = TemplateStore(tmp_path)
    now = datetime(2026, 1, 1).isoformat()
    max_id = "a" * 48  # already at the id length limit
    first = store.create(
        ClipTemplate(id=max_id, name="Long", created_at=now, updated_at=now,
                     subtitles=SubtitleSpec(), layout=LayoutSpec())
    )
    # Collision on a 48-char slug: the -N suffix must not push it past 48.
    second = store.create(
        ClipTemplate(id=max_id, name="Long", created_at=now, updated_at=now,
                     subtitles=SubtitleSpec(), layout=LayoutSpec())
    )
    assert first.id == max_id
    assert len(second.id) <= 48
    assert second.id != first.id
