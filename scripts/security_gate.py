#!/usr/bin/env python3
"""Security / data-leak gate for azelia-clips.

A deterministic check that BLOCKS secrets and personal data from reaching any
branch (especially the PUBLIC `main`). Wired as a `pre-push` git hook and runnable
by hand / in CI. Has a built-in eval suite (`--self-test`) so the gate itself is
verified before it's trusted.

The gate inspects two things about the content being introduced:
  1. PATHS   — forbidden files (job data, .env, *.db, OAuth secrets, the user's
               .claude memory notes, raw transcripts, key material).
  2. CONTENT — secret-looking strings on ADDED lines (API keys, private keys, JWTs).

Exit codes: 0 = clean, 2 = violation(s) found, 1 = usage / internal error.

Usage:
  security_gate.py --staged                 # check `git diff --cached` (pre-commit)
  security_gate.py --range <base>..<tip>    # check a commit range (pre-push)
  security_gate.py --files a.py b.json       # check explicit paths on disk
  security_gate.py --self-test              # run the eval suite, print PASS/FAIL
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass


# ── Rules ────────────────────────────────────────────────────────────────────
# A path is FORBIDDEN if it matches a forbidden pattern and NONE of the allow
# patterns. Keep these in sync with .gitignore's "never commit" section.

FORBIDDEN_PATH_PATTERNS: list[tuple[str, str]] = [
    (r"(^|/)data/", "job data dir (clips/transcripts/curation — user content)"),
    (r"\.db($|-wal$|-shm$)|\.sqlite[0-9]?$", "SQLite database (local user data)"),
    (r"(^|/)\.env$|(^|/)\.env\.", ".env file (may hold secrets)"),
    (r"(^|/)secrets?\.env$", "secrets.env (API keys / tokens)"),
    (r"\.claude/projects/.*/memory/", "personal Claude memory/brain note"),
    (r"(^|/)(id_rsa|id_ed25519)$|\.pem$|(^|/)[^/]*\.key$", "private key material"),
    (r"client_secret.*\.json$|(^|/)oauth.*\.json$|(^|/)token.*\.json$", "OAuth / token file"),
    (r"(^|/)transcript[^/]*\.json$", "raw transcript JSON (episode content)"),
    (r"web/e2e/\.auth/", "Playwright auth state (live session tokens)"),
]

# Paths that LOOK forbidden but are explicitly safe (templates / synthetic).
ALLOW_PATH_PATTERNS: list[str] = [
    r"\.env\.example$",
    r"(^|/)examples/.*\.json$",
    r"(^|/)tests/fixtures/.*\.json$",  # synthetic fixtures (reviewed)
]

# Secret-looking content on ADDED lines. Each is a (regex, label).
SECRET_CONTENT_PATTERNS: list[tuple[str, str]] = [
    (r"sk-ant-[A-Za-z0-9_-]{20,}", "Anthropic API key"),
    (r"AKIA[0-9A-Z]{16}", "AWS access key id"),
    (r"AIza[0-9A-Za-z_-]{30,}", "Google API key"),
    (r"ghp_[0-9A-Za-z]{30,}", "GitHub personal access token"),
    (r"xox[baprs]-[0-9A-Za-z-]{10,}", "Slack token"),
    (r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY", "private key block"),
    (r"eyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{10,}", "JWT"),
]

# A secret match is ignored if the same line also contains one of these
# (test fixtures, placeholders, docs).
SECRET_FALSE_POSITIVE = re.compile(
    r"INVALID|EXAMPLE|PLACEHOLDER|YOUR[_-]?KEY|XXXX|FAKE|DUMMY|REDACTED|<.*>", re.I
)


@dataclass
class Finding:
    path: str
    kind: str  # "path" | "content"
    detail: str
    line: int | None = None

    def __str__(self) -> str:
        loc = f"{self.path}:{self.line}" if self.line else self.path
        return f"  ✗ [{self.kind}] {loc} — {self.detail}"


def _path_is_allowed(path: str) -> bool:
    return any(re.search(p, path) for p in ALLOW_PATH_PATTERNS)


def check_path(path: str) -> list[Finding]:
    if _path_is_allowed(path):
        return []
    out = []
    for pat, label in FORBIDDEN_PATH_PATTERNS:
        if re.search(pat, path):
            out.append(Finding(path=path, kind="path", detail=label))
            break  # one reason per path is enough
    return out


def check_content(path: str, added_lines: list[tuple[int, str]]) -> list[Finding]:
    """`added_lines` is a list of (lineno, text) for newly added lines."""
    out = []
    for lineno, text in added_lines:
        if SECRET_FALSE_POSITIVE.search(text):
            continue
        for pat, label in SECRET_CONTENT_PATTERNS:
            if re.search(pat, text):
                out.append(Finding(path=path, kind="content", detail=label, line=lineno))
    return out


# ── Git plumbing ─────────────────────────────────────────────────────────────
def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=False
    ).stdout


def _changed_paths(diff_args: list[str]) -> list[str]:
    out = _git("diff", "--name-only", "--diff-filter=ACMR", *diff_args)
    return [p for p in out.splitlines() if p.strip()]


def _added_lines_by_path(diff_args: list[str]) -> dict[str, list[tuple[int, str]]]:
    """Parse unified diff → {path: [(new_lineno, added_text), ...]}."""
    diff = _git("diff", "--unified=0", "--diff-filter=ACMR", *diff_args)
    result: dict[str, list[tuple[int, str]]] = {}
    cur: str | None = None
    new_ln = 0
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            cur = line[6:]
            result.setdefault(cur, [])
        elif line.startswith("@@"):
            m = re.search(r"\+(\d+)", line)
            new_ln = int(m.group(1)) if m else 0
        elif cur and line.startswith("+") and not line.startswith("+++"):
            result[cur].append((new_ln, line[1:]))
            new_ln += 1
        elif cur and not line.startswith("-"):
            new_ln += 1
    return result


def scan(diff_args: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    for path in _changed_paths(diff_args):
        findings += check_path(path)
    for path, added in _added_lines_by_path(diff_args).items():
        if _path_is_allowed(path):
            continue
        findings += check_content(path, added)
    return findings


def scan_files(paths: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    for path in paths:
        findings += check_path(path)
        try:
            with open(path, encoding="utf-8", errors="ignore") as fh:
                added = [(i + 1, ln) for i, ln in enumerate(fh.read().splitlines())]
            if not _path_is_allowed(path):
                findings += check_content(path, added)
        except OSError:
            pass
    return findings


# ── Eval suite (the "evals definidos") ───────────────────────────────────────
def self_test() -> int:
    """Defined evals: the gate must flag known-bad and pass known-good."""
    bad_paths = [
        "data/jobs/abc/transcript.json",
        "data/jobs/abc/curation.json",
        "secrets.env",
        ".env",
        "server/x.db",
        "store.sqlite3",
        ".claude/projects/-Users-x/memory/note.md",
        "config/client_secret_123.json",
        "deploy/id_rsa",
        "certs/server.pem",
        "web/e2e/.auth/state.json",
    ]
    good_paths = [
        ".env.example",
        "web/.env.example",
        "examples/sample.json",
        "tests/fixtures/brief/curation.json",
        "packages/clips/pipeline.py",
        "server/routes/clips.py",
        "scripts/security_gate.py",
    ]
    # Samples are assembled at runtime so this file never contains a contiguous
    # secret literal (otherwise the gate would flag its own eval fixtures).
    sk = "sk-ant-" + "api03-abc123def456ghi789jkl012mno345"
    aws = "AKIA" + "1234567890ABCDEF"
    pk = "-----BEGIN OPENSSH " + "PRIVATE KEY-----"
    gk = "AIza" + "SyA1234567890abcdefghijklmnopqrstuv"
    bad_content = [
        ("a.py", [(1, f'KEY = "{sk}"')]),
        ("b.ts", [(7, f"const k = '{aws}'")]),
        ("c.txt", [(1, pk)]),
        ("d.env.real", [(1, f"GOOGLE={gk}")]),
    ]
    good_content = [
        ("e.spec.ts", [(100, "await input.fill('sk-ant-INVALID_KEY_12345')")]),
        ("f.md", [(1, "set ANTHROPIC_API_KEY=<your-key-here>")]),
        ("g.py", [(1, "api_key = os.environ['ANTHROPIC_API_KEY']")]),
    ]

    failures: list[str] = []
    for p in bad_paths:
        if not check_path(p):
            failures.append(f"FALSE NEGATIVE (path not flagged): {p}")
    for p in good_paths:
        if check_path(p):
            failures.append(f"FALSE POSITIVE (good path flagged): {p}")
    for p, lines in bad_content:
        if not check_content(p, lines):
            failures.append(f"FALSE NEGATIVE (secret missed): {p} {lines}")
    for p, lines in good_content:
        if check_content(p, lines):
            failures.append(f"FALSE POSITIVE (benign flagged): {p} {lines}")

    total = len(bad_paths) + len(good_paths) + len(bad_content) + len(good_content)
    if failures:
        print(f"security_gate self-test: {len(failures)}/{total} FAILED")
        for f in failures:
            print("  ✗", f)
        return 1
    print(f"security_gate self-test: PASS ({total}/{total} evals)")
    return 0


# ── CLI ──────────────────────────────────────────────────────────────────────
def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--staged", action="store_true", help="check staged changes")
    g.add_argument("--range", metavar="A..B", help="check a commit range")
    g.add_argument("--files", nargs="+", help="check explicit paths on disk")
    g.add_argument("--self-test", action="store_true", help="run the eval suite")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()
    if args.staged:
        findings = scan(["--cached"])
    elif args.range:
        findings = scan([args.range])
    else:
        findings = scan_files(args.files)

    if findings:
        print("🚫 SECURITY GATE BLOCKED — secrets / personal data detected:\n")
        for f in findings:
            print(f)
        print(
            "\nNothing was pushed/committed. Remove the file(s) from the change, or if "
            "this is a reviewed false positive, add an allow-rule in scripts/security_gate.py."
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
