"""Detect which fonts are installed on the machine.

The ASS subtitle render (libass/FFmpeg) can only honor a font family that the
OS actually has; otherwise it silently substitutes one. The template editor
uses these helpers to warn when a chosen ``font_name`` is not installed, instead
of promising a look the render won't produce.

Strategy: prefer fontconfig (``fc-list``) when available (Linux, and macOS with
fontconfig). Fall back to scanning the standard font directories by filename
stem, which covers a stock macOS/Windows where fontconfig is absent. Results are
cached for the process; fonts don't change mid-run in practice.
"""

from __future__ import annotations

import functools
import subprocess
from pathlib import Path

_FONT_DIRS = [
    # macOS
    "/System/Library/Fonts",
    "/Library/Fonts",
    "~/Library/Fonts",
    # Linux
    "/usr/share/fonts",
    "/usr/local/share/fonts",
    "~/.fonts",
    "~/.local/share/fonts",
    # Windows
    "C:/Windows/Fonts",
]

_FONT_SUFFIXES = {".ttf", ".otf", ".ttc", ".woff", ".woff2"}


def _from_fontconfig() -> set[str]:
    """Family names via ``fc-list``; empty set if fontconfig isn't present."""
    try:
        out = subprocess.run(
            ["fc-list", ":", "family"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return set()
    if out.returncode != 0:
        return set()
    names: set[str] = set()
    for line in out.stdout.splitlines():
        # A line may list several comma-separated localized family aliases.
        for fam in line.split(","):
            fam = fam.strip()
            if fam:
                names.add(fam)
    return names


def _from_font_dirs() -> set[str]:
    """Best-effort family names from font filenames in the standard dirs."""
    names: set[str] = set()
    for raw in _FONT_DIRS:
        root = Path(raw).expanduser()
        if not root.is_dir():
            continue
        try:
            for path in root.rglob("*"):
                if path.suffix.lower() in _FONT_SUFFIXES:
                    names.add(path.stem.strip())
        except (OSError, PermissionError):
            continue
    return names


@functools.lru_cache(maxsize=1)
def list_installed_fonts() -> tuple[str, ...]:
    """Sorted tuple of font family names available on this machine."""
    names = _from_fontconfig()
    if not names:
        names = _from_font_dirs()
    return tuple(sorted(names))


def is_font_installed(name: str) -> bool:
    """True if ``name`` matches an installed family (case/space-insensitive)."""
    target = (name or "").strip().lower()
    if not target:
        return False
    return any(target == f.lower() for f in list_installed_fonts())
