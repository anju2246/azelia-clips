"""Domain models for clip templates."""

from typing import Literal, Optional
from pydantic import BaseModel, Field


# v2 adds optional, default-off render extensions (intro title, branding,
# progress bar, bumpers). A v1 .azt still loads: the new fields take their
# defaults, so behavior is unchanged unless explicitly enabled.
SCHEMA_VERSION = 2


class SubtitleSpec(BaseModel):
    """Subtitle styling specification."""

    font_name: str = Field(default="Montserrat", min_length=1, max_length=60)
    font_size: int = Field(default=52, ge=12, le=200)
    primary_color: str = Field(default="&H00FFFFFF", pattern=r"^&H[0-9A-Fa-f]{8}$")
    secondary_color: str = Field(default="&H0000FFFF", pattern=r"^&H[0-9A-Fa-f]{8}$")
    outline_color: str = Field(default="&H00000000", pattern=r"^&H[0-9A-Fa-f]{8}$")
    back_color: str = Field(default="&H80000000", pattern=r"^&H[0-9A-Fa-f]{8}$")
    bold: bool = True
    outline: int = Field(default=3, ge=0, le=10)
    shadow: int = Field(default=2, ge=0, le=10)
    alignment: int = Field(default=2, ge=1, le=9)
    margin_v: int = Field(default=50, ge=0, le=1920)
    animation: Literal["highlight", "karaoke", "box", "cumulative"] = "cumulative"
    words_per_line: int = Field(default=5, ge=1, le=10)


class LayoutSpec(BaseModel):
    """Layout specification for clip composition."""

    # Default reproduces the historical split layout exactly: a 608px wide shot
    # (true 16:9 at 1080px width) over a 1312px close-up.  608 / 1920 ≈ 0.3167.
    type: Literal["split", "fullscreen"] = "split"
    output_width: int = 1080
    output_height: int = 1920
    wide_height_ratio: float = Field(default=608 / 1920, ge=0.20, le=0.50)


class IntroTitleSpec(BaseModel):
    """A title card shown on screen for the first N seconds of the clip.

    The text is NOT stored here — it comes from the clip's curated title at
    render time. This spec only controls how/where/how long it shows.
    """

    enabled: bool = False
    duration_s: float = Field(default=4.0, ge=1.0, le=8.0)
    # Empty font_name inherits the subtitle font at render time.
    font_name: str = Field(default="", max_length=60)
    font_size: int = Field(default=72, ge=12, le=200)
    color: str = Field(default="&H00FFFFFF", pattern=r"^&H[0-9A-Fa-f]{8}$")
    outline_color: str = Field(default="&H00000000", pattern=r"^&H[0-9A-Fa-f]{8}$")
    position: Literal["top", "center", "bottom"] = "center"
    box: bool = True
    # When true, word captions are held until the title finishes (the title
    # shows BEFORE the captions). When false, captions run under the title.
    delay_captions: bool = True


class ClipTemplate(BaseModel):
    """A visual template for clip rendering."""

    schema_version: int = SCHEMA_VERSION
    id: str = Field(pattern=r"^[a-z0-9-]{1,48}$")
    name: str = Field(min_length=1, max_length=60)
    description: str = Field(default="", max_length=280)
    author: str = Field(default="", max_length=60)
    is_builtin: bool = False
    created_at: str
    updated_at: str
    subtitles: SubtitleSpec
    layout: LayoutSpec
    # v2 optional render extensions (default-off → no-regression).
    intro_title: Optional[IntroTitleSpec] = None

    def to_azt_bytes(self) -> bytes:
        """Serialize to .azt JSON bytes."""
        return self.model_dump_json(indent=2).encode("utf-8")

    @classmethod
    def from_azt_bytes(cls, data: bytes) -> "ClipTemplate":
        """Deserialize from .azt JSON bytes."""
        return cls.model_validate_json(data)
