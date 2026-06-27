"""Color conversions for the render layer.

ASS stores colors as ``&HAABBGGRR`` (alpha, blue, green, red). FFmpeg's drawbox
and drawtext want ``0xRRGGBB`` (with an optional ``@alpha``). Getting the byte
order right is easy to get wrong — hence its own tested helper.
"""

import re

_ASS = re.compile(r"^&H([0-9A-Fa-f]{8})$")


def ass_to_ffmpeg_hex(ass: str) -> str:
    """Convert an ASS ``&HAABBGGRR`` color to FFmpeg ``0xRRGGBB`` (alpha dropped)."""
    m = _ASS.match(ass or "")
    if not m:
        return "0xFFFFFF"
    h = m.group(1).upper()
    bb, gg, rr = h[2:4], h[4:6], h[6:8]
    return f"0x{rr}{gg}{bb}"
