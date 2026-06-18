"""Built-in template presets derived from existing subtitle styles."""

from packages.clips.templates.models import ClipTemplate


def list_builtins() -> list[ClipTemplate]:
    """Return all built-in template presets (read-only)."""
    raise NotImplementedError


def get_builtin(slug: str) -> ClipTemplate | None:
    """Get a built-in template by slug, or None if not found."""
    raise NotImplementedError
