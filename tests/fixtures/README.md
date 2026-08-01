# Test fixtures — synthetic only

This is a **public** repository. Every file under `tests/fixtures/` must be
**invented data**. Never copy a real export, database row, transcript, or
analytics payload in here — not even a small slice of one, and not even when it
contains no names or IDs. Aggregated production numbers are still production
data.

## Rules

1. **Author fixtures by hand.** Reproduce the *schema* of the real payload, not
   its *values*. Round, obviously-fake numbers (`10000.0`, `0.02`, `1.5`) are a
   feature: they read as synthetic at a glance.
2. **Name them `*_synthetic.json`** when they mirror a real-world payload shape.
   Never `*_real`, `*_slice`, `*_export`, `*_ready`, `*_dump`, `*_OLD_<date>` —
   `scripts/security_gate.py` hard-blocks those names anywhere in the repo,
   including here, and the block cannot be waived by an allow rule.
3. **Use impossible sentinel values** where a real dataset would carry a real
   one. Periods use a far-future stamp (`2099-W01`) so a fixture record can
   never be mistaken for, or silently merged with, a genuine one.
4. **Never point a test at a path outside the repo.** A test that reads
   `~/.azelia/data/` or a `PODFINDER_SIGNALS_PATH` export passes on your machine
   and leaks context into CI logs. Copy an invented sample in instead.

## Why this file exists

`tests/fixtures/**` is on the security gate's allow-list for the *ordinary* path
rules (so a fixture may legitimately be named `oauth_something.json` without
tripping the OAuth-file check). That exemption once made this directory the one
blind spot where real data could sit unnoticed: two fixtures here held genuine
PodFinder intelligence records, copied verbatim out of a production export.

The gate now has a hard tier the allow-list cannot override, but naming
conventions only catch data that *looks* like a dump. A hand-picked slice with a
tidy name is invisible to any regex — so the real control is this policy plus
review. If you are not certain a fixture is invented, it is not.
