# Changelog

All notable changes to Azelia Clips. This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.1.0] — 2026-05-17

### The "local-first" release

Azelia Clips ships as a 100% local, MIT-licensed product. No central backend, no telemetry, no account, no Pro tier. Your podcast, your transcripts, your clips — never leave your machine.

This release supersedes the previous SaaS-oriented codebase. The git history before this commit is preserved under tag `v0.0.x-legacy` and in the `azelia-clips-archive` private repository.

### Added
- **Self-update from the dashboard.** Settings → Workspace → System updates. One click pulls the latest GitHub release, reinstalls deps, rebuilds the dashboard, and restarts the server. Your data in `~/.azelia/data/` is preserved.
- `scripts/self_update.sh` orchestrates the update.
- `install.sh` wrapper now runs `azelia` in a loop so the in-app update can trigger a clean restart (exit code 42).
- `GET /api/system/version`, `POST /api/system/update`, `GET /api/system/update/status`, `GET /api/system/info`.
- `~/.azelia/data/` standardized as the user data home — survives all updates and reinstalls.

### Changed
- LLM providers restricted to **Claude Code (local subscription) + Anthropic API**. Other providers (Groq, OpenAI, Google) hidden from UI; they'll come back as opt-in in v0.2 if there's demand.
- Server binds to `127.0.0.1` by default. Set `AZELIA_BIND_HOST=0.0.0.0` to expose on LAN (no auth!).
- Onboarding wizard collapsed from 4 steps to 2 (Workspace + AI providers).
- Settings UI: dropped Privacy tab (no telemetry to consent to). Integrations tab keeps the user-owned Supabase transcript option (BYO).
- README + ARCHITECTURE rewritten to reflect local-first reality.

### Removed
- **Supabase central backend**: auth, telemetry, IC Cascade dataset, Pro tier activation, account deletion routes, Edge Functions. Each install is now an island.
- Frontend pages: `/login`, `/auth/callback`, `/auth/reset-password`, `/dashboard/profile`, `/dashboard/intelligence`, `/youtube-connect`.
- Frontend components: `UserProfile`, `ProUpgradeCard`, `CreatorSignalsCard`, `MyContentIntelligence`, `NicheBenchmark`, `TelemetryNudge`, `IntelligenceDashboard`, `RetroactiveSyncModal`, `LoginForm`, `ResetPasswordForm`.
- Backend modules: `packages/core/auth.py`, `crypto.py`, `ic_contract.py`, `db/`, `services/telemetry.py`, `services/local_intelligence.py`, `services/analytics.py`.
- Routes: `server/routes/{auth,upgrade,telemetry_routes}.py`.
- Tests tied to removed features: `test_ic_cascade`, `test_telemetry_consent`, `test_security_hardening`, `test_local_intelligence`, `test_telemetry`.
- Legal docs that only applied to a hosted service: `PRIVACY_POLICY.md`, `TERMS_OF_SERVICE.md`, `DATA_USAGE_TERMS.md`, `LAUNCH_CHECKLIST.md`.
- YouTube central-feed routes from the SaaS era. (The OAuth-based Shorts sync was rebuilt locally before launch — see "Kept" below.)

### Kept (worth highlighting)
- The full multi-agent curation pipeline: Finder → Critic → Ranker → Captions.
- MTCNN face tracking and dynamic 16:9 → 9:16 reframing.
- ASS word-level animated subtitles burned into final MP4.
- Pause/Resume/Cancel of running jobs.
- 30-day rejected-clip trash with restore.
- BYO Supabase for transcript ingestion (the user's *own* Supabase project — Azelia has none of its own).
- WhisperX / MLX-Whisper transcription, optional Pyannote diarization.
- **YouTube Shorts sync (local-only).** OAuth connect from the dashboard, tokens stored encrypted in `~/.azelia/data/youtube_shorts.db`. Pulls your own published Shorts + analytics to give the Ranker prior context. Nothing about your account goes anywhere outside your machine.

### Verified
- Full pipeline tested live on a real 60-min podcast episode with Claude Code as the LLM backend. 22 clips generated end-to-end (transcribe → curate → reframe → subtitle) with no central-DB dependencies.

### Known limitations
- Single-user only. No auth. Don't expose the port without putting a reverse proxy in front.
- The `OnboardingWizard` and `SettingsForm` components are still oversized internally (~1k lines each). They work, but a refactor is queued for v0.1.2.
- Podcast library scanner requires `EPNNN -` prefixed subfolders today; flexible layout coming in v0.1.1.

---

## Pre-0.1.0

Earlier development is preserved in the private `azelia-clips-archive` repository and under the local tag `pre-mvp-rewrite-v0` (commit `711ea3c`). That history represents the original SaaS-oriented design — kept for reference, not for forking.
