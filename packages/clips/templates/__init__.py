"""Clip templates module - visual templates for subtitles + layout."""

from packages.clips.templates.builtins import get_builtin, list_builtins
from packages.clips.templates.models import ClipTemplate, LayoutSpec, SubtitleSpec
from packages.clips.templates.store import (
    TemplateInvalid,
    TemplateNotFound,
    TemplateReadOnly,
    TemplateStore,
)

__all__ = [
    "ClipTemplate",
    "SubtitleSpec",
    "LayoutSpec",
    "list_builtins",
    "get_builtin",
    "TemplateStore",
    "TemplateNotFound",
    "TemplateReadOnly",
    "TemplateInvalid",
]
