"""Tests for claude_detect (T3 — detección de binarios y cuentas de Claude Code).

All tests are expected to FAIL until the GREEN-phase implementation lands.
Filesystem/subprocess are faked via tmp_path fixtures and injected runners —
nothing touches the real ~/.claude or runs the real `claude` binary.
"""

import json
import os
import stat

import pytest

from packages.core import claude_detect


# ── helpers ──────────────────────────────────────────────────────────────


def _write_account(path, email, display_name="Someone", plan="claude_max"):
    """Write a fake .claude.json with an oauthAccount block."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"oauthAccount": {
        "emailAddress": email,
        "displayName": display_name,
        "organizationType": plan,
    }}))


def _make_executable(path, body="#!/bin/sh\necho '1.2.3 (Claude Code)'\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


# ── binaries ───────────────────────────────────────────────────────────────


def test_dedup_binaries_by_realpath(tmp_path):
    real = tmp_path / "bin" / "claude"
    _make_executable(real)
    link = tmp_path / "link" / "claude"
    link.parent.mkdir(parents=True)
    os.symlink(real, link)

    runner = lambda p: ("1.2.3 (Claude Code)", True)
    found = claude_detect.detect_installations(
        candidate_paths=[("path", str(link)), ("npm", str(real))],
        version_runner=runner,
    )
    assert len(found) == 1
    assert found[0]["valid"] is True
    assert found[0]["version"] == "1.2.3 (Claude Code)"


def test_invalid_binary_marked_not_valid(tmp_path):
    real = tmp_path / "bin" / "claude"
    _make_executable(real)
    runner = lambda p: (None, False)
    found = claude_detect.detect_installations(
        candidate_paths=[("path", str(real))],
        version_runner=runner,
    )
    assert len(found) == 1
    assert found[0]["valid"] is False


# ── accounts (authoritative-file rule) ──────────────────────────────────────


def test_read_account_default_uses_home_json(tmp_path):
    # home/.claude.json is authoritative for the default; the inner
    # home/.claude/.claude.json is legacy noise with a DIFFERENT email.
    _write_account(tmp_path / ".claude.json", "live@home.com")
    _write_account(tmp_path / ".claude" / ".claude.json", "stale@inner.com")

    acc = claude_detect.read_account(None, home=tmp_path)
    assert acc["email"] == "live@home.com"
    assert acc["logged_in"] is True

    acc_default = claude_detect.read_account(tmp_path / ".claude", home=tmp_path)
    assert acc_default["email"] == "live@home.com"


def test_read_account_custom_uses_inner_json_no_fallback(tmp_path):
    _write_account(tmp_path / ".claude.json", "home@x.com")
    custom = tmp_path / ".claude-work"
    _write_account(custom / ".claude.json", "work@y.com")

    acc = claude_detect.read_account(custom, home=tmp_path)
    assert acc["email"] == "work@y.com"

    # a custom dir WITHOUT its own .claude.json must NOT fall back to home
    empty = tmp_path / ".claude-empty"
    empty.mkdir()
    acc_empty = claude_detect.read_account(empty, home=tmp_path)
    assert acc_empty["logged_in"] is False
    assert acc_empty["email"] is None


def test_missing_oauth_account_degrades_gracefully(tmp_path):
    (tmp_path / ".claude.json").write_text(json.dumps({"numStartups": 3}))
    acc = claude_detect.read_account(None, home=tmp_path)
    assert acc["logged_in"] is False
    assert acc["email"] is None


def test_detect_accounts_skips_backup_dirs(tmp_path):
    _write_account(tmp_path / ".claude-work" / ".claude.json", "work@y.com")
    _write_account(tmp_path / ".claude-work.backup" / ".claude.json", "work@y.com")

    accounts = claude_detect.detect_accounts(home=tmp_path)
    dirs = [a.get("config_dir") or "" for a in accounts]
    assert any("work@y.com" == a["email"] for a in accounts)
    assert not any(str(d).endswith(".backup") for d in dirs)


# ── validate ─────────────────────────────────────────────────────────────


def test_validate_reports_reason_codes(tmp_path):
    # non-executable path
    plain = tmp_path / "notexec"
    plain.write_text("nope")
    res = claude_detect.validate(path=str(plain), config_dir=None)
    assert res["valid"] is False
    assert res["reason"] == "not_executable"

    # good binary but missing config_dir
    good = tmp_path / "claude"
    _make_executable(good)
    res2 = claude_detect.validate(
        path=str(good),
        config_dir=str(tmp_path / "does-not-exist"),
        version_runner=lambda p: ("1.2.3", True),
    )
    assert res2["valid"] is False
    assert res2["reason"] == "config_dir_not_found"
