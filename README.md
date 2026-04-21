# Azelia Clips 🎬✂️

> AI-powered podcast clip generator — part of the **Azelia** suite by [Inminente](https://inminente.co).

[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11+-green.svg)](https://python.org)

---

## What It Does

Azelia Clips takes a podcast episode and outputs ready-to-post vertical clips with:

1. **🎤 Transcription** — WhisperX / MLX-Whisper with word-level timestamps + speaker diarization
2. **🧠 AI Curation** — Multi-agent system (Finder → Critic → Ranker) selects the most viral moments
3. **👁️ Smart Reframing** — MTCNN + FaceNet face tracking for 16:9 → 9:16 conversion
4. **📝 Styled Subtitles** — Animated captions with keyword highlighting

```
podcast.mp4 (60 min) → 5 vertical clips (30-90s each) + subtitles + captions
```

## Cost transparency

Azelia is **BYOK** — you pay the AI provider directly, nothing routes through us.
Typical cost per 60-minute episode:

| Provider + model                    | Input $/M | Output $/M | Est. per episode |
|-------------------------------------|-----------|------------|------------------|
| Anthropic Claude Haiku 4.5          | $1.00     | $5.00      | **~$0.07–$0.15** |
| Anthropic Claude Sonnet 4.6         | $3.00     | $15.00     | **~$0.40–$0.80** |
| Anthropic Claude Opus 4.7           | $15.00    | $75.00     | ~$2.00–$4.00     |
| OpenAI GPT-4o                       | $2.50     | $10.00     | ~$0.30–$0.70     |
| OpenAI GPT-4o Mini                  | $0.15     | $0.60      | ~$0.04–$0.08     |
| Groq Llama 3.3 70B (free tier)      | $0        | $0         | $0 (rate-limited) |

Transcription runs locally via Whisper/MLX-Whisper (Apple Silicon optimized) —
**zero API cost**. The multi-agent pipeline (Finder → Critic → Ranker) sends
~50k input + ~15k output tokens to the LLM you choose.

Default is Haiku — switch to Sonnet in Settings → Pipeline if you want
sharper curation at a higher cost. Nothing is called without your key.

## Azelia Clips vs. the alternatives

|                        | Azelia Clips           | OpusClip / Vizard | Descript                |
|------------------------|------------------------|-------------------|-------------------------|
| License                | **MIT — open source**  | Proprietary       | Proprietary             |
| Runtime                | **Self-hosted, local** | Cloud only        | Cloud + desktop         |
| Pricing model          | **BYOK (~$0.10/ep)**   | $15–80 / month    | $12–40 / month          |
| Your video stays local | **Yes, by default**    | Uploaded to cloud | Uploaded to cloud       |
| Data for training      | **Opt-in anonymous**   | Depends (ToS)     | Depends (ToS)           |
| Multi-agent curation   | **Yes (3 agents)**     | Single model      | Single model            |
| Configurable prompts   | **Yes**                | No                | Limited                 |
| Swap providers         | **Any BYOK**           | No                | No                      |

Trade-offs Azelia doesn't try to hide: you need a local machine capable of
running Whisper (Apple Silicon or NVIDIA GPU recommended for speed), you
manage your own API keys, and you are responsible for your inference costs.
In exchange you keep control of your pipeline and your content.

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
azelia start --build

# Or start with existing build
azelia start

# Development mode (hot-reload)
azelia start --dev
```

Open `http://localhost:8000` and you're ready to go.

#### CLI Mode

```bash
# Full pipeline: transcribe → curate → extract → subtitle
azelia process video.mp4 --output ./clips --top 5

# Individual steps
azelia transcribe video.mp4                 # Transcribe only
azelia curate transcript.json --top 10      # Curate from transcript
azelia reframe clip.mp4 --mode face         # Reframe to 9:16
azelia subtitles clip.mp4 transcript.json   # Generate subtitles
```

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     azelia process                        │
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

## The Azelia Suite

Azelia Clips is the first product in the **Azelia** suite — an open-source toolkit for podcasters.

| Product | Description | Status |
|---------|------------|--------|
| **Azelia Clips** | AI clip generation from episodes | ✅ Available |
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

[MIT](LICENSE) — Open Source. Usa, modifica, distribuye. Haz lo que necesites con el código.

### Legal

- **[Privacy Policy](PRIVACY_POLICY.md)** — What data we collect and how we handle it.
- **[Terms of Service](TERMS_OF_SERVICE.md)** — Usage rules and legal obligations.
- **[Contributor License Agreement (CLA)](CLA.md)** — Required for contributing.
- **[Data Usage Terms](DATA_USAGE_TERMS.md)** — How we handle anonymized analytics. Telemetry is opt-out via `AZELIA_TELEMETRY_OPT_OUT=true`.


---

**Azelia** — The open-source podcaster's toolkit. *By [Inminente](https://inminente.co).*
