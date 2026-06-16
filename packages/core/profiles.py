"""Profile manager — multi-podcast isolation.

Each podcast is a *profile* with its own data tree under
``<azelia_home>/profiles/<slug>/`` (jobs, jobs.db, youtube_shorts.db,
secrets.env). A global registry at ``<azelia_home>/profiles.json`` holds the
profile list and the active-profile pointer.

ProfileManager takes the azelia home dir explicitly and must NOT import
packages.core.config (config.py imports this module — the dependency stays
one-directional to avoid an import cycle). Migration of the legacy
``~/.azelia/data`` tree (``ensure_initialized``) is added in T2.
"""

from __future__ import annotations

import errno
import json
import os
import re
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

REGISTRY_VERSION = 1
_NAME_MAX = 64


class ProfileError(Exception):
    """Base error for profile operations (validation, illegal delete, etc.)."""


class ProfileNotFound(ProfileError):
    """Raised when a profile id is not in the registry."""


class ActiveProfileError(ProfileError):
    """Raised when deleting the currently-active profile."""


class LastProfileError(ProfileError):
    """Raised when deleting the only remaining profile."""


def slugify(name: str) -> str:
    """Turn a podcast name into a stable, filesystem-safe slug.

    Lowercases, replaces any run of non-alphanumeric chars with a single
    hyphen, and trims leading/trailing hyphens. Returns "" if nothing usable
    survives (caller treats that as invalid).
    """
    s = (name or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


@dataclass
class Profile:
    id: str
    name: str
    data_dir: str
    claude_binary: Optional[str] = None
    claude_config_dir: Optional[str] = None
    is_default: bool = False
    created_at: str = ""


class ProfileManager:
    """Reads/writes the profile registry at ``<azelia_home>/profiles.json``."""

    def __init__(self, azelia_home: Path):
        self.azelia_home = Path(azelia_home)

    # ── paths ────────────────────────────────────────────────────────────

    @property
    def registry_path(self) -> Path:
        return self.azelia_home / "profiles.json"

    @property
    def profiles_root(self) -> Path:
        return self.azelia_home / "profiles"

    # ── registry I/O ─────────────────────────────────────────────────────

    def _load(self) -> dict:
        if not self.registry_path.exists():
            return {"version": REGISTRY_VERSION, "active_profile": None, "profiles": []}
        with open(self.registry_path, encoding="utf-8") as f:
            return json.load(f)

    def _save(self, data: dict) -> None:
        """Atomic write: dump to a temp file then os.replace (never a partial
        registry on crash)."""
        self.azelia_home.mkdir(parents=True, exist_ok=True)
        tmp = self.registry_path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, self.registry_path)

    @staticmethod
    def _to_profile(d: dict) -> Profile:
        return Profile(
            id=d["id"],
            name=d["name"],
            data_dir=d["data_dir"],
            claude_binary=d.get("claude_binary"),
            claude_config_dir=d.get("claude_config_dir"),
            is_default=d.get("is_default", False),
            created_at=d.get("created_at", ""),
        )

    # ── validation ───────────────────────────────────────────────────────

    @staticmethod
    def _validate_name(name: str) -> str:
        n = (name or "").strip()
        if not n or len(n) > _NAME_MAX:
            raise ProfileError(f"Profile name must be 1–{_NAME_MAX} characters")
        if not slugify(n):
            raise ProfileError("Profile name must contain letters or digits")
        return n

    @staticmethod
    def _validate_claude_binary(path: Optional[str]) -> None:
        if path is None:
            return
        p = Path(path)
        if not p.is_file() or not os.access(p, os.X_OK):
            raise ProfileError("Selected Claude binary is not a valid executable")

    @staticmethod
    def _validate_config_dir(path: Optional[str]) -> None:
        if path is None:
            return
        if not Path(path).is_dir():
            raise ProfileError("CLAUDE_CONFIG_DIR must be an existing directory")

    def _unique_slug(self, base: str, existing: set[str]) -> str:
        if base not in existing:
            return base
        i = 2
        while f"{base}-{i}" in existing:
            i += 1
        return f"{base}-{i}"

    # ── queries ──────────────────────────────────────────────────────────

    def list(self) -> list[Profile]:
        return [self._to_profile(d) for d in self._load()["profiles"]]

    def get(self, profile_id: str) -> Optional[Profile]:
        for d in self._load()["profiles"]:
            if d["id"] == profile_id:
                return self._to_profile(d)
        return None

    def active(self) -> Profile:
        data = self._load()
        active_id = data.get("active_profile")
        for d in data["profiles"]:
            if d["id"] == active_id:
                return self._to_profile(d)
        raise ProfileNotFound("No active profile")

    def active_data_dir(self) -> Path:
        return Path(self.active().data_dir)

    # ── lifecycle / migration ────────────────────────────────────────────

    _PLACEHOLDER_NAMES = {"", "my podcast"}

    def ensure_initialized(
        self,
        legacy_data_dir: Optional[Path] = None,
        override_data_dir: Optional[Path] = None,
    ) -> None:
        """Create the registry on first run. Idempotent.

        - registry already exists  → no-op
        - AZELIA_DATA_DIR override  → register it as the default profile in-place
        - legacy ~/.azelia/data     → move it under profiles/<slug>/
        - nothing                   → create an empty "Inminente" profile
        """
        if self.registry_path.exists():
            return
        if override_data_dir is not None:
            self._init_in_place(Path(override_data_dir))
        elif legacy_data_dir is not None and Path(legacy_data_dir).exists():
            self._migrate_legacy(Path(legacy_data_dir))
        else:
            self.create("Inminente")

    def _resolve_name(self, data_dir: Path) -> str:
        """Podcast name from a dir's secrets.env, or 'Inminente' if placeholder/missing."""
        name = ""
        secrets = data_dir / "secrets.env"
        if secrets.exists():
            for line in secrets.read_text().splitlines():
                if line.startswith("PODCAST_NAME="):
                    name = line.split("=", 1)[1].strip()
                    break
        if name.strip().lower() in self._PLACEHOLDER_NAMES:
            return "Inminente"
        return name

    def _register_single(self, slug: str, name: str, data_dir: Path) -> None:
        profile = Profile(
            id=slug,
            name=name,
            data_dir=str(data_dir),
            is_default=True,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self._save(
            {
                "version": REGISTRY_VERSION,
                "active_profile": slug,
                "profiles": [asdict(profile)],
            }
        )

    def _init_in_place(self, data_dir: Path) -> None:
        name = self._resolve_name(data_dir)
        self._register_single(slugify(name), name, data_dir)

    def _migrate_legacy(self, legacy: Path) -> None:
        name = self._resolve_name(legacy)
        slug = slugify(name)
        self.profiles_root.mkdir(parents=True, exist_ok=True)
        target = self.profiles_root / slug
        try:
            os.rename(legacy, target)
        except OSError as e:
            if getattr(e, "errno", None) == errno.EXDEV:
                target = legacy  # cross-volume: register in-place, don't risk a copy
            else:
                raise
        # registry written only AFTER the move succeeds
        self._register_single(slug, name, target)

    # ── mutations ────────────────────────────────────────────────────────

    def create(
        self,
        name: str,
        claude_binary: Optional[str] = None,
        claude_config_dir: Optional[str] = None,
    ) -> Profile:
        name = self._validate_name(name)
        self._validate_claude_binary(claude_binary)
        self._validate_config_dir(claude_config_dir)

        data = self._load()
        existing = {d["id"] for d in data["profiles"]}
        slug = self._unique_slug(slugify(name), existing)

        data_dir = self.profiles_root / slug
        (data_dir / "jobs").mkdir(parents=True, exist_ok=True)
        secrets = data_dir / "secrets.env"
        secrets.write_text(f"PODCAST_NAME={name}\n")
        try:
            os.chmod(secrets, 0o600)
        except OSError:
            pass

        profile = Profile(
            id=slug,
            name=name,
            data_dir=str(data_dir),
            claude_binary=claude_binary,
            claude_config_dir=claude_config_dir,
            is_default=not data["profiles"],  # first profile is the default
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        data["profiles"].append(asdict(profile))
        if data.get("active_profile") is None:
            data["active_profile"] = slug
        self._save(data)
        return profile

    def update(self, profile_id: str, **fields) -> Profile:
        data = self._load()
        entry = next((d for d in data["profiles"] if d["id"] == profile_id), None)
        if entry is None:
            raise ProfileNotFound(profile_id)

        if "name" in fields:
            new_name = self._validate_name(fields["name"])
            entry["name"] = new_name
            self._write_podcast_name(Path(entry["data_dir"]), new_name)
        if "claude_binary" in fields:
            self._validate_claude_binary(fields["claude_binary"])
            entry["claude_binary"] = fields["claude_binary"]
        if "claude_config_dir" in fields:
            self._validate_config_dir(fields["claude_config_dir"])
            entry["claude_config_dir"] = fields["claude_config_dir"]

        self._save(data)
        return self._to_profile(entry)

    def delete(self, profile_id: str, delete_data: bool = False) -> None:
        data = self._load()
        entry = next((d for d in data["profiles"] if d["id"] == profile_id), None)
        if entry is None:
            raise ProfileNotFound(profile_id)
        if len(data["profiles"]) <= 1:
            raise LastProfileError("Cannot delete the last remaining profile")
        if data.get("active_profile") == profile_id:
            raise ActiveProfileError("Cannot delete the active profile; switch first")

        data["profiles"] = [d for d in data["profiles"] if d["id"] != profile_id]
        self._save(data)

        if delete_data:
            target = Path(entry["data_dir"]).resolve()
            root = self.profiles_root.resolve()
            # Only ever wipe data that lives under <home>/profiles/ — never an
            # in-place AZELIA_DATA_DIR path the user pointed us at.
            if root in target.parents and target.exists():
                shutil.rmtree(target, ignore_errors=True)

    def set_active(self, profile_id: str) -> None:
        data = self._load()
        if not any(d["id"] == profile_id for d in data["profiles"]):
            raise ProfileNotFound(profile_id)
        data["active_profile"] = profile_id
        self._save(data)

    # ── helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _write_podcast_name(data_dir: Path, name: str) -> None:
        """Update PODCAST_NAME in the profile's secrets.env, preserving the rest."""
        secrets = data_dir / "secrets.env"
        lines: list[str] = []
        found = False
        if secrets.exists():
            for line in secrets.read_text().splitlines():
                if line.startswith("PODCAST_NAME="):
                    lines.append(f"PODCAST_NAME={name}")
                    found = True
                else:
                    lines.append(line)
        if not found:
            lines.append(f"PODCAST_NAME={name}")
        data_dir.mkdir(parents=True, exist_ok=True)
        secrets.write_text("\n".join(lines) + "\n")
