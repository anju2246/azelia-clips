"""Clip templates module - visual templates for subtitles + layout."""

from packages.clips.templates.models import ClipTemplate, SubtitleSpec, LayoutSpec
from packages.clips.templates.builtins import list_builtins, get_builtin
from packages.clips.templates.store import (
    TemplateStore,
    TemplateNotFound,
    TemplateReadOnly,
    TemplateInvalid,
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
