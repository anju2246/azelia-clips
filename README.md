# Azelia Clips

> Open-source, local-first podcast clipper powered by Claude. Your video, your transcripts, your clips — never leave your machine.

[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11+-green.svg)](https://python.org)
[![Status](https://img.shields.io/badge/status-v0.1.0--beta-orange.svg)](#status)

---

## What it does

Takes a podcast episode (60–120 min) → outputs ready-to-post vertical clips with subtitles.

```
podcast.mp4  ──►  ./clips/approved/clip_01.mp4
                  ./clips/approved/clip_02.mp4
                  ./clips/review/clip_03.mp4
                  ...
```

Each clip is 30–90 s, vertical 9:16, with animated subtitles burned in.

**Pipeline**: Whisper (transcription) → Claude multi-agent curation (Finder → Critic → Ranker) → MTCNN face tracking (reframe) → ASS subtitles.

---

## Why this exists

Existing clippers (OpusClip, Vizard, etc.) are cloud-only, paid SaaS, and upload your content to their servers. Azelia Clips runs **entirely on your machine**:

- Your videos never leave your laptop
- You bring your own LLM key (Anthropic) **or** use Claude Code locally — no Azelia account
- MIT-licensed: fork it, rebrand it, ship your own product
- Self-update from the dashboard with one click; your data is preserved

The trade: you need a machine that can run Whisper (Apple Silicon or NVIDIA GPU recommended for speed) and you pay your LLM provider directly. In exchange you keep full control of your pipeline and your content.

---

## Install

### One-line install (macOS / Linux)

```bash
curl -fsSL https://raw.githubusercontent.com/anju2246/azelia-clips/main/install.sh | bash
```

Installs into `~/.azelia/`. Sets up Python venv, installs all deps (including Whisper + face tracking + diarization), adds `azelia` to your PATH.

### From source

```bash
git clone https://github.com/anju2246/azelia-clips.git
cd azelia-clips
python3 -m venv venv
source venv/bin/activate
pip install -e ".[all]"
cd web && npm install && npm run build && cd ..
```

Requires Python 3.11+, Node 18+, FFmpeg, and (for diarization) a [HuggingFace token](https://huggingface.co/pyannote/speaker-diarization-3.1).

---

## Run

```bash
azelia start
```

Opens `http://localhost:8000` in your browser. The first launch builds the dashboard (~1 min).

**Onboarding**: paste your Anthropic API key (or have Claude Code installed locally), then pick the folder where your podcast episodes live. That's it.

---

## Podcast folder layout

During onboarding (or in Settings → Workspace) you pick a folder that contains your episodes. Azelia expects each episode in its own subfolder, prefixed with `EPNNN -`, with a video file inside:

```
~/Podcasts/                              ← whatever folder you pick
├── EP001 - First Episode Title/
│   └── video.mp4
├── EP002 - Another Episode/
│   └── video.mp4
└── EP003 - …/
    └── video.mp4
```

Rules the scanner uses:

- **Subfolder name must start with `EPNNN -`** (e.g. `EP001 -`, `EP042 -`). The number is the episode ID Azelia uses across runs.
- **The subfolder must contain a `.mp4`.** It prefers a file named exactly `video.mp4`; otherwise it picks the first `.mp4` it finds.
- **Generated clips render next to the source**, in `EP001 - …/clips/approved/clip_NN.mp4` — never inside the install folder.

If you just want to try Azelia on a one-off file without organising a library, use the **Upload** tab in the dashboard — it accepts any `.mp4`/`.mov`/`.mkv` and renders into `~/.azelia/data/jobs/`.

> A more flexible layout (any folder, no `EPNNN -` prefix) is on the roadmap for v0.1.1.

---

## LLM cost per episode

Azelia Clips is **BYOK** — you pay the LLM provider directly, nothing routes through us.

| Provider | Cost per 60-min episode |
|---|---|
| **Claude Code** (local subscription) | **$0** (uses your Claude.ai plan) |
| Anthropic Claude Haiku 4.5 | ~$0.07–$0.15 |
| Anthropic Claude Sonnet 4.6 | ~$0.40–$0.80 |
| Anthropic Claude Opus 4.7 | ~$2.00–$4.00 |

Transcription runs locally via Whisper (Apple Silicon optimized) — **zero API cost**.
The multi-agent pipeline sends ~50k input + ~15k output tokens to the LLM you choose.

In v0.1.0 the supported providers are **Claude Code + Anthropic API**. Other providers (Groq, OpenAI, Google) may return in v0.2 — for now we ship what we test against.

---

## Self-update

When a new version ships, you'll see an **Update now** button in Settings → Workspace. Click it and:

1. The server pulls the latest code from GitHub
2. Reinstalls Python + JS dependencies
3. Restarts itself cleanly
4. The dashboard reconnects automatically

Your clips, transcripts, settings and SQLite DBs live in `~/.azelia/data/` — **outside the install folder** — so updates never touch them.

---

## Status

**v0.1.0-beta** (current): local-first foundation. Pipeline runs end-to-end. Self-update works. YouTube integration disabled while we rebuild it for local-only (back in v0.1.1).

This is an early beta. Things will break. [Open issues](https://github.com/anju2246/azelia-clips/issues) freely.

---

## Project structure

```
azelia-clips/
├── packages/
│   ├── clips/                # Pipeline
│   │   ├── transcription/    # WhisperX / MLX-Whisper + Pyannote diarization
│   │   ├── curation/         # Finder → Critic → Ranker LLM agents
│   │   ├── vision/           # MTCNN face tracker + reframer
│   │   └── subtitles/        # ASS subtitle generator
│   └── core/                 # Config, LLM router, taxonomy
├── server/                   # FastAPI: routes, queue, jobs, system updates
├── web/                      # Astro + React dashboard
├── scripts/self_update.sh    # In-app self-update
└── install.sh                # One-line installer (with restart-loop wrapper)
```

For details see [ARCHITECTURE.md](ARCHITECTURE.md).

---

## License

[MIT](LICENSE). Use, modify, redistribute, build a competing product — all allowed.

Trademark on the name "Azelia" and the logo is not covered by MIT. Forks should use a different name.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Contributors sign the [CLA](CLA.md). Security issues: see [SECURITY.md](SECURITY.md).

---

**Azelia Clips** — local-first clips for podcasters who own their stack.
