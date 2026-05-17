"""AnalyticsSync stub for local-first MVP.

In the SaaS-era this class wrapped a Supabase client and pushed telemetry,
clip metrics and creator signals to the Azelia central DB. Local-first
v0.1.0 keeps all that data in the user's machine — nothing goes upstream.

We keep the class with the same surface so the rest of the codebase
(server/routes/analytics.py, packages/clips/pipeline.py) continues to
compile and call .sync_clip(), .Enabled, etc. without per-call gating.
Calls are silent no-ops.

When v0.2 reintroduces optional opt-in upload to a central service, this
file is the natural place to wire it.
"""

from typing import Any


class AnalyticsSync:
    """No-op stand-in for the SaaS-era Supabase analytics client."""

    Enabled = False

    def __init__(self, auth_token: Any = None, **_kwargs: Any):
        self.client = None

    def sync_clip(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def sync_episode(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def sync_session(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def __getattr__(self, name: str):
        """Catch-all so any unknown method becomes a no-op (forward compat)."""
        return lambda *a, **kw: None
