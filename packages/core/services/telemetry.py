"""Telemetry no-op for local-first MVP.

In the SaaS-era this module ran a fire-and-forget Supabase client that sent
clip metrics, performance signals, and consent events to the central DB.
Local-first v0.1.0 keeps everything on the user's machine — no telemetry.

We keep the public surface (`telemetry`, `_cohort_hash`, `TelemetryService`)
so the rest of the codebase compiles without per-call gating. Every method
is a silent no-op.

If you want analytics on YOUR clips, look at the local SQLite at
~/.azelia/data/youtube_shorts.db — that data stays local.
"""

import hashlib
from typing import Any


def _cohort_hash(user_id: str) -> str:
    """Deterministic local hash. Kept for API compat (was anonymization)."""
    if not user_id:
        return ""
    return hashlib.sha256(user_id.encode()).hexdigest()[:12]


class _NoopTelemetry:
    enabled = False

    def __getattr__(self, name: str):
        return lambda *args, **kwargs: None


telemetry = _NoopTelemetry()
TelemetryService = _NoopTelemetry
