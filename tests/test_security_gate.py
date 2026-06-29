"""Evals for the security/data-leak gate (scripts/security_gate.py).

These lock the gate's behavior so it can be trusted as the pre-push guardrail:
the exact leak we found in history (a real job transcript) MUST be flagged, and
known-good files (env examples, synthetic fixtures, source) MUST pass.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

_GATE = Path(__file__).resolve().parents[1] / "scripts" / "security_gate.py"
_spec = importlib.util.spec_from_file_location("security_gate", _GATE)
gate = importlib.util.module_from_spec(_spec)
# Register before exec so @dataclass can resolve the module (Python 3.13).
sys.modules["security_gate"] = gate
_spec.loader.exec_module(gate)


@pytest.mark.parametrize(
    "path",
    [
        "data/jobs/6bc3935c-8c43-4add-9c5a-15c28c783316/transcript.json",  # the real leak
        "data/jobs/abc/curation.json",
        "secrets.env",
        ".env",
        "web/.env.local",
        "server/jobs.db",
        "store.sqlite3",
        ".claude/projects/-Users-x/memory/project_note.md",
        "config/client_secret_123.json",
        "deploy/id_rsa",
        "certs/server.pem",
        "web/e2e/.auth/state.json",
    ],
)
def test_forbidden_paths_are_blocked(path):
    assert gate.check_path(path), f"expected {path} to be flagged"


@pytest.mark.parametrize(
    "path",
    [
        ".env.example",
        "web/.env.example",
        "examples/sample.json",
        "tests/fixtures/brief/curation.json",  # synthetic fixture, reviewed
        "packages/clips/pipeline.py",
        "server/routes/clips.py",
    ],
)
def test_good_paths_pass(path):
    assert not gate.check_path(path), f"expected {path} to pass"


# Built at runtime so this test file never contains a contiguous secret literal
# (the gate scans its own source, and these are deliberately realistic fakes).
_SK = "sk-ant-" + "api03-abc123def456ghi789jkl012mno345"
_AWS = "AKIA" + "1234567890ABCDEF"
_PK = "-----BEGIN OPENSSH " + "PRIVATE KEY-----"
_GK = "AIza" + "SyA1234567890abcdefghijklmnopqrstuv"


@pytest.mark.parametrize(
    "line",
    [
        f'KEY = "{_SK}"',
        f"const k = '{_AWS}'",
        _PK,
        f"GOOGLE={_GK}",
    ],
)
def test_secret_content_is_blocked(line):
    assert gate.check_content("x.py", [(1, line)]), f"expected secret in: {line}"


@pytest.mark.parametrize(
    "line",
    [
        "await input.fill('sk-ant-INVALID_KEY_12345')",  # test fixture
        "set ANTHROPIC_API_KEY=<your-key-here>",
        "api_key = os.environ['ANTHROPIC_API_KEY']",
    ],
)
def test_benign_content_passes(line):
    assert not gate.check_content("x.py", [(1, line)]), f"false positive on: {line}"


def test_self_test_suite_passes():
    """The gate's own built-in eval suite must be green."""
    assert gate.self_test() == 0
