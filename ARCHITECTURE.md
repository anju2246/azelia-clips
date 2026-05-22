# Architecture

> Azelia Clips v0.1.0 is **100% local-first and MIT-licensed**. No central backend, no telemetry, no Pro tier. Your video, your transcripts, your clips — never leave your machine.

This document is short because the architecture is small. That's the point.

---

## What runs where

```
Your machine
├── ~/.azelia/
│   ├── azelia/          ← MIT-licensed source (this repo, cloned by install.sh)
│   ├── venv/            ← Python virtualenv with pipeline deps
│   ├── bin/azelia       ← wrapper script (PATH-installed)
│   └── data/            ← YOUR data — never touched by updates
│       ├── jobs/        (generated clips, curation.json, faces, speakers)
│       ├── jobs.db      (SQLite: job statuses)
│       ├── youtube_shorts.db   (local YouTube Shorts sync — encrypted OAuth tokens)
│       ├── secrets.env  (your Anthropic API key, etc.)
│       └── update.log   (last self-update output)

External services (only what you explicitly call)
├── Anthropic API           (if you set ANTHROPIC_API_KEY — your account, your bill)
├── Claude Code CLI         (if installed locally — uses your subscription)
├── GitHub API              (read-only: check for new releases)
└── Your own Supabase       (optional: if you keep transcripts there)
```

Azelia itself runs **no servers**. There is nothing for us to take down, paywall, or rate-limit.

---

## The pipeline

```
podcast.mp4
   │
   ▼
[1. Transcribe]   Whisper (local) — MLX on Apple Silicon, OpenAI Whisper elsewhere
   │              Optional: Pyannote diarization if HF_TOKEN is set
   │              Optional: your own Supabase transcript table
   │
   ▼
[2. Curate]       Multi-agent LLM pipeline:
   │              Finder  → scans transcript for viral candidates
   │              Critic  → filters weak ones (incomplete ideas, bad hooks)
   │              Ranker  → scores survivors on 10 dimensions
   │              Caption → generates social-ready hooks
   │              (All steps run through Claude Code or Anthropic API.)
   │
   ▼
[3. Reframe]      MTCNN face detection + speaker tracking →
   │              dynamic crop, 16:9 → 9:16 vertical (TikTok/Reels format)
   │
   ▼
[4. Subtitle]    ASS subtitles with word-level timing + animation styles
   │              Burned into final MP4 with FFmpeg
   │
   ▼
ready-to-post vertical clips (under `data/jobs/{id}/clips/approved/`)
```

Every step runs on your hardware. The LLM call is the only network hop, and you pick the provider.

---

## What's MIT (everything here)

| Component | Path | Purpose |
|---|---|---|
| Client UI | `web/` | Astro + React dashboard |
| Server | `server/` | FastAPI: routes, queue, jobs, system updates |
| Pipeline | `packages/clips/` | Transcription, curation, vision, subtitles |
| Core | `packages/core/` | Config, LLM router, taxonomy, utilities |
| CLI | `packages/clips/cli.py` | `azelia process`, `start`, etc. |
| Installer | `install.sh` | One-shot setup + wrapper with auto-restart |
| Self-update | `scripts/self_update.sh` | Pulls latest release, restarts cleanly |

Fork it, rebrand it, ship it as your own product. The license allows that.

---

## What's NOT in this repo

- **Trademark.** The name "Azelia" and the logo are not covered by MIT. Forks can reuse the code under any name — not "Azelia".

That's the whole list. There is no proprietary backend, no closed dataset, no managed service.

---

## Self-update model

Updates are **GitHub releases** (semver tags like `v0.1.0`, `v0.1.1`, …).

1. The dashboard polls `GET /api/system/version` and compares the local version against the latest GitHub release.
2. If newer, the user clicks **Update now** in Settings → Workspace.
3. `POST /api/system/update` runs `scripts/self_update.sh`:
   - `git fetch` + `git reset --hard origin/main`
   - `pip install -e .`
   - `npm install && npm run build`
   - Touches a restart sentinel
4. The CLI watcher sees the sentinel and exits with code **42**.
5. The wrapper script (`bin/azelia`) detects exit 42 and re-launches the server with the new code.
6. The dashboard reconnects automatically.

Your data (`~/.azelia/data/`) is **outside the git checkout** and is never touched by any of these steps. Worst case (failed update), you can `git reset` the checkout manually — your clips and settings are safe.

---

## What we explicitly chose NOT to build (yet)

- **User accounts.** It's single-user, on localhost. No login, no signup. If you need multi-user, fork it.
- **Telemetry.** Nothing leaves your machine without your action. No "anonymous metrics" we promise are anonymous.
- **Pro tier / payments.** Free, MIT, all features. Pay your LLM provider directly.
- **Collective intelligence dataset.** Each install is an island. The Ranker uses prompt engineering, not a trained model on aggregated data.
- **Multi-platform clip distribution.** Generate the clips, upload them yourself (or wait for a future tool).

If a future version wants any of these, they'll be opt-in connections to a separately-licensed Azelia service. The local product will remain MIT and runnable disconnected.

---

## Versioning

- Single source of truth: `pyproject.toml` → `version = "X.Y.Z"`
- Surfaced via `packages.clips.__version__` and `server/app.py` (FastAPI version field)
- `/api/system/version` and `/api/system/info` expose it for diagnostics

Semver: bumps follow Keep a Changelog conventions; see `CHANGELOG.md`.

---

## Questions

- **Can I use Azelia to build a competing SaaS?** Yes, MIT allows it. Build your own brand.
- **Can I run multiple users on a LAN?** Set `AZELIA_BIND_HOST=0.0.0.0`. But there's no auth — anyone on the LAN can use it. Add your own reverse proxy with auth if needed.
- **Will there ever be a hosted version?** Maybe. If so, it'll be separately operated, and this MIT codebase will remain the source of truth.
- **What about YouTube integration?** v0.1.0 ships it as 100% local. OAuth connect from the dashboard, tokens encrypted at rest in `~/.azelia/data/youtube_shorts.db`. Pulls your own Shorts + analytics so the Ranker has prior context — nothing about your account ever leaves your machine.

Contact for anything else: open an issue on GitHub.
