"""Built-in template presets derived from existing subtitle styles.

The 5 presets mirror the ``STYLES`` dict in ``subtitles/generator.py`` so the
template system stays the single source of truth for clip styling while
remaining backward-compatible with the styles the pipeline used before.
"""

from packages.clips.subtitles.generator import STYLES, SubtitleStyle
from packages.clips.templates.models import ClipTemplate, LayoutSpec, SubtitleSpec

# Built-ins are not user-created, so they carry a fixed, deterministic timestamp.
_BUILTIN_TS = "1970-01-01T00:00:00"

# Which preset renders on the split-screen layout (the others are full-screen).
_SPLIT_SLUGS = {"splitscreen"}


def _subtitle_spec_from_style(style: SubtitleStyle) -> SubtitleSpec:
    """Map the legacy SubtitleStyle dataclass to a SubtitleSpec 1:1.

    ``animation`` and ``words_per_line`` have no equivalent in SubtitleStyle
    (the pipeline passed them separately), so they take the SubtitleSpec
    defaults — which match what the pipeline used (``cumulative`` / 5).
    """
    return SubtitleSpec(
        font_name=style.font_name,
        font_size=style.font_size,
        primary_color=style.primary_color,
        secondary_color=style.secondary_color,
        outline_color=style.outline_color,
        back_color=style.back_color,
        bold=style.bold,
        outline=style.outline,
        shadow=style.shadow,
        alignment=style.alignment,
        margin_v=style.margin_v,
    )


def _builtin_from_style(slug: str, style: SubtitleStyle) -> ClipTemplate:
    layout_type = "split" if slug in _SPLIT_SLUGS else "fullscreen"
    return ClipTemplate(
        id=slug,
        name=style.name,
        description=f"Built-in {style.name} preset",
        author="Azelia",
        is_builtin=True,
        created_at=_BUILTIN_TS,
        updated_at=_BUILTIN_TS,
        subtitles=_subtitle_spec_from_style(style),
        layout=LayoutSpec(type=layout_type),
    )


def list_builtins() -> list[ClipTemplate]:
    """Return all built-in template presets (read-only)."""
    return [_builtin_from_style(slug, style) for slug, style in STYLES.items()]


def get_builtin(slug: str) -> ClipTemplate | None:
    """Get a built-in template by slug, or None if not found."""
    style = STYLES.get(slug)
    if style is None:
        return None
    return _builtin_from_style(slug, style)
