"""Detección de instalaciones y cuentas de Claude Code (F6/F7).

- Binarios: PATH (`which -a`), `~/.claude/local`, npm global, homebrew;
  deduplicados por realpath; cada uno probado con `--version`.
- Cuentas: identificadas por `oauthAccount.emailAddress` del `.claude.json`
  autoritativo. Regla verificada en máquina real:
    · config dir default (`~/.claude`, sin CLAUDE_CONFIG_DIR) ⇒ `~/.claude.json` (HOME),
      NO el `~/.claude/.claude.json` interno (que puede ser legacy con otro email).
    · config dir custom `X` ⇒ `X/.claude.json` (dentro), SIN fallback al home.

Módulo sin estado y sin secretos: solo lee los campos no-secretos de
`oauthAccount`. `version_runner` es inyectable para tests.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Callable, Optional

_BINARY_NAMES = ("claude", "claude.exe", "claude.cmd")
_VERSION_TIMEOUT = 3


# ── binarios ───────────────────────────────────────────────────────────────


def _default_version_runner(path: str) -> tuple[Optional[str], bool]:
    """Run `<path> --version`. Returns (version|None, valid). Raises on timeout."""
    try:
        r = subprocess.run(
            [path, "--version"], capture_output=True, text=True, timeout=_VERSION_TIMEOUT
        )
        return (r.stdout.strip(), True) if r.returncode == 0 else (None, False)
    except OSError:
        return None, False


def _default_candidates(home: Optional[Path] = None) -> list[tuple[str, str]]:
    """(source, path) candidates from PATH + common install locations."""
    home = Path(home) if home else Path.home()
    cands: list[tuple[str, str]] = []
    for d in os.environ.get("PATH", "").split(os.pathsep):
        for name in _BINARY_NAMES:
            c = os.path.join(d, name)
            if os.path.isfile(c):
                cands.append(("path", c))
    local = home / ".claude" / "local" / "claude"
    if local.exists():
        cands.append(("claude_local", str(local)))
    for hb in ("/opt/homebrew/bin/claude", "/usr/local/bin/claude"):
        if os.path.exists(hb):
            cands.append(("homebrew", hb))
    try:
        pref = subprocess.run(
            ["npm", "prefix", "-g"], capture_output=True, text=True, timeout=5
        ).stdout.strip()
        npc = os.path.join(pref, "bin", "claude") if pref else ""
        if npc and os.path.exists(npc):
            cands.append(("npm", npc))
    except (OSError, subprocess.SubprocessError):
        pass
    return cands


def detect_installations(
    candidate_paths: Optional[list[tuple[str, str]]] = None,
    version_runner: Optional[Callable[[str], tuple[Optional[str], bool]]] = None,
) -> list[dict]:
    """List Claude Code binaries, deduplicated by realpath, each probed for version."""
    if candidate_paths is None:
        candidate_paths = _default_candidates()
    runner = version_runner or _default_version_runner

    seen: dict[str, dict] = {}
    for source, path in candidate_paths:
        try:
            rp = os.path.realpath(path)
        except OSError:
            rp = path
        if rp in seen:
            continue
        try:
            version, valid = runner(path)
        except subprocess.TimeoutExpired:
            version, valid = None, False
        seen[rp] = {
            "path": path,
            "realpath": rp,
            "source": source,
            "version": version,
            "valid": valid,
        }
    return list(seen.values())


# ── cuentas ────────────────────────────────────────────────────────────────


def read_account(config_dir, home: Optional[Path] = None) -> dict:
    """Resolve the account behind a config dir via its authoritative .claude.json."""
    home = Path(home) if home else Path.home()
    if config_dir is None or Path(config_dir) == home / ".claude":
        cfg_file = home / ".claude.json"  # default: HOME file, not the inner one
        config_dir_field = None
    else:
        cfg_file = Path(config_dir) / ".claude.json"  # custom: inner, no fallback
        config_dir_field = str(config_dir)

    result = {
        "config_dir": config_dir_field,
        "email": None,
        "display_name": None,
        "plan": None,
        "logged_in": False,
    }
    try:
        data = json.loads(cfg_file.read_text())
    except (OSError, ValueError):
        return result

    oa = data.get("oauthAccount")
    if isinstance(oa, dict) and oa.get("emailAddress"):
        result.update(
            email=oa.get("emailAddress"),
            display_name=oa.get("displayName"),
            plan=oa.get("organizationType"),
            logged_in=True,
        )
    return result


def detect_accounts(extra_config_dirs=None, home: Optional[Path] = None) -> list[dict]:
    """Detect Claude accounts: default dir + extras + best-effort ~/.claude-* siblings."""
    home = Path(home) if home else Path.home()
    accounts: list[dict] = []
    seen: set[str] = set()

    def add(config_dir, require_login: bool = False) -> None:
        acc = read_account(config_dir, home=home)
        key = acc["config_dir"] or "__default__"
        if key in seen:
            return
        if require_login and not acc["logged_in"]:
            return
        seen.add(key)
        accounts.append(acc)

    add(None)  # default ~/.claude → ~/.claude.json
    for p in sorted(home.glob(".claude-*")):
        if not p.is_dir() or p.name.endswith((".backup", ".bak")):
            continue
        add(p, require_login=True)  # siblings are best-effort: only if logged in
    for d in extra_config_dirs or []:
        add(Path(d))
    return accounts


# ── validación manual ───────────────────────────────────────────────────────


def validate(
    path: Optional[str] = None,
    config_dir: Optional[str] = None,
    home: Optional[Path] = None,
    version_runner: Optional[Callable[[str], tuple[Optional[str], bool]]] = None,
) -> dict:
    """Validate a manual binary + config dir and identify its account."""
    if path is not None:
        p = Path(path)
        if not p.is_file() or not os.access(p, os.X_OK):
            return {"valid": False, "reason": "not_executable"}

    runner = version_runner or _default_version_runner
    try:
        version, ok = runner(path or "claude")
    except subprocess.TimeoutExpired:
        return {"valid": False, "reason": "timeout"}
    if not ok:
        return {"valid": False, "reason": "version_failed"}

    if config_dir is not None and not Path(config_dir).is_dir():
        return {"valid": False, "reason": "config_dir_not_found"}

    return {
        "valid": True,
        "version": version,
        "account": read_account(Path(config_dir) if config_dir else None, home=home),
    }
