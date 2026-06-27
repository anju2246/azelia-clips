"""Translate a ClipTemplate into the concrete knobs the render pipeline uses.

Kept pure (no I/O, no FFmpeg) so the mapping — including backward-compatibility
with the pre-template ``splitscreen`` style — is unit-testable.
"""

from dataclasses import dataclass

from packages.clips.subtitles.generator import SubtitleStyle
from packages.clips.templates.models import ClipTemplate


@dataclass
class RenderPlan:
    """Everything the pipeline needs to render a clip from a template."""

    style: SubtitleStyle
    animation: str
    words_per_line: int
    layout_type: str
    wide_height_ratio: float
    intro_title: object | None = None  # IntroTitleSpec | None (hook title, T13)


def template_to_style(template: ClipTemplate) -> SubtitleStyle:
    """Map a template's SubtitleSpec back to the legacy SubtitleStyle dataclass.

    The style ``name`` is taken from the template name (cosmetic only; it does
    not affect rendering). All other fields map 1:1, so the splitscreen built-in
    round-trips to exactly ``STYLES['splitscreen']``.
    """
    s = template.subtitles
    return SubtitleStyle(
        name=template.name,
        font_name=s.font_name,
        font_size=s.font_size,
        primary_color=s.primary_color,
        secondary_color=s.secondary_color,
        outline_color=s.outline_color,
        back_color=s.back_color,
        bold=s.bold,
        outline=s.outline,
        shadow=s.shadow,
        alignment=s.alignment,
        margin_v=s.margin_v,
    )


def template_to_render_plan(template: ClipTemplate) -> RenderPlan:
    """Resolve a template into a concrete RenderPlan."""
    return RenderPlan(
        style=template_to_style(template),
        animation=template.subtitles.animation,
        words_per_line=template.subtitles.words_per_line,
        layout_type=template.layout.type,
        wide_height_ratio=template.layout.wide_height_ratio,
        intro_title=getattr(template, "intro_title", None),
    )
