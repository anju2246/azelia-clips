# Celia Clips 🎬✂️

> AI-powered podcast clip generator — part of the **Celia** suite by [Inminente](https://inminente.co).

[![License](https://img.shields.io/badge/License-MIT_Commons_Clause-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11+-green.svg)](https://python.org)

---

## What It Does

Celia Clips takes a podcast episode and outputs ready-to-post vertical clips with:

1. **🎤 Transcription** — WhisperX / MLX-Whisper with word-level timestamps + speaker diarization
2. **🧠 AI Curation** — Multi-agent system (Finder → Critic → Ranker) selects the most viral moments
3. **👁️ Smart Reframing** — MTCNN + FaceNet face tracking for 16:9 → 9:16 conversion
4. **📝 Styled Subtitles** — Animated captions with keyword highlighting

```
podcast.mp4 (60 min) → 5 vertical clips (30-90s each) + subtitles + captions
```

## Quick Start

### Install

```bash
# Core (curation + subtitles + server)
pip install -e .

# With transcription (requires GPU or Apple Silicon)
pip install -e ".[asr]"

# Apple Silicon optimized (MLX-Whisper)
pip install -e ".[asr-mlx]"

# Everything
pip install -e ".[all]"
```

### Configure

All configuration happens through the **web dashboard** — no `.env` editing required.

On first launch, the onboarding wizard walks you through:
1. 📛 Podcast name & profile
2. 🤖 AI provider setup (Groq, OpenAI, Claude, or Vertex AI)
3. 🔗 YouTube connection (optional — for analytics)

> For development/advanced config, see `docs/configuration.md`.

### Run

#### Dashboard Mode (Recommended)

```bash
# Build frontend + start server
celia start --build

# Or start with existing build
celia start

# Development mode (hot-reload)
celia start --dev
```

Open `http://localhost:8000` and you're ready to go.

#### CLI Mode

```bash
# Full pipeline: transcribe → curate → extract → subtitle
celia process video.mp4 --output ./clips --top 5

# Individual steps
celia transcribe video.mp4                 # Transcribe only
celia curate transcript.json --top 10      # Curate from transcript
celia reframe clip.mp4 --mode face         # Reframe to 9:16
celia subtitles clip.mp4 transcript.json   # Generate subtitles
```

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     celia process                        │
├─────────────┬──────────────┬─────────────┬──────────────┤
│  Transcribe │    Curate    │   Reframe   │  Subtitles   │
│  WhisperX / │  Finder  ──→│   MTCNN +   │  ASS/SRT     │
│  MLX-Whisper│  Critic  ──→│   FaceNet   │  + Highlight  │
│  + Pyannote │  Ranker     │  Identity   │  + Animate    │
├─────────────┴──────────────┴─────────────┴──────────────┤
│     LLM Provider (Groq / OpenAI / Claude / Vertex AI)    │
└─────────────────────────────────────────────────────────┘
```

### Multi-Agent Curation Pipeline

| Agent | Role | Output |
|-------|------|--------|
| **Finder** | Scans transcript for ALL potential viral moments | 15-20 candidates |
| **Critic** | Filters weak clips (incomplete ideas, bad hooks, wrong duration) | 8-12 approved |
| **Ranker** | Scores clips on 10 dimensions (hook, quotability, storytelling, pacing...) | Top N ranked |

## The Celia Suite

Celia Clips is the first product in the **Celia** suite — an open-source toolkit for podcasters.

| Product | Description | Status |
|---------|------------|--------|
| **Celia Clips** | AI clip generation from episodes | ✅ Available |
| **Celia Insights** | YouTube + TikTok analytics | 🔜 Coming Soon |
| **Celia Studio** | Full episode editing | 🔜 Coming Soon |
| **Celia Grow** | Guest outreach + audience growth | 🔜 Coming Soon |

## Requirements

- **Python** 3.11+
- **Node.js** 18+ (for the web dashboard)
- **FFmpeg** — `brew install ffmpeg` (macOS) / `apt install ffmpeg` (Linux)
- **For ASR**: Apple Silicon (MPS) or GPU with 4GB+ VRAM
- **For Diarization**: HuggingFace token with [pyannote access](https://huggingface.co/pyannote/speaker-diarization-3.1)

## Project Structure

```
packages/
├── core/              # Auth, config, branding, LLM routing
│   ├── config.py      # Centralized settings (Pydantic)
│   ├── branding.py    # Brand constants (easy rebrand)
│   └── db/            # SQLite models + engine
├── clips/             # Clip generation pipeline
│   ├── curation/      # Multi-agent clip selection
│   │   └── agents/    # Finder, Critic, Ranker
│   ├── vision/        # MTCNN + FaceNet face tracking
│   ├── transcription/ # WhisperX / MLX-Whisper
│   ├── subtitles/     # ASS subtitle generation
│   └── cli.py         # CLI entry point
server/
├── routes/            # FastAPI endpoints
│   ├── clips.py       # Upload, process, serve clips
│   ├── settings.py    # App config + directory browser
│   ├── analytics.py   # YouTube OAuth + analytics
│   └── auth.py        # Auth endpoints
web/
└── src/               # Astro + React dashboard
    ├── components/     # UI components
    ├── pages/          # Routes (dashboard, login, onboarding)
    └── lib/            # API client, Supabase config
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and guidelines.

## Cloud Solution

Need a managed, hosted solution? Contact us directly for enterprise/agency pricing.

📧 **hola@inminente.co**

## License

[MIT License + Commons Clause](LICENSE) — Open Source, but **not for commercial sale**.

### Legal

- **[Privacy Policy](PRIVACY_POLICY.md)** — What data we collect and how we handle it.
- **[Terms of Service](TERMS_OF_SERVICE.md)** — Usage rules and legal obligations.
- **[Contributor License Agreement (CLA)](CLA.md)** — Required for contributing.
- **[Data Usage Terms](DATA_USAGE_TERMS.md)** — How we handle anonymized analytics. Telemetry is opt-out via `CELIA_TELEMETRY_OPT_OUT=true`.


---

**Celia** — The open-source podcaster's toolkit. *By [Inminente](https://inminente.co).*
