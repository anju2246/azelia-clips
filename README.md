# Celia Clips 🎬✂️

> AI-powered podcast clip generator — part of the **Celia** suite by [Inminente](https://inminente.co).

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11+-green.svg)](https://python.org)

---

## What It Does

Celia Clips takes a podcast episode and outputs ready-to-post vertical clips with:

1. **🎤 Transcription** — WhisperX with word-level timestamps + speaker diarization
2. **🧠 AI Curation** — Multi-agent system (Finder → Critic → Ranker) selects the most viral moments
3. **👁️ Smart Reframing** — MediaPipe face tracking for 16:9 → 9:16 conversion
4. **📝 Styled Subtitles** — Animated captions with keyword highlighting
5. **🎵 Audio Separation** — Demucs-based voice/music isolation

```
podcast.mp4 (60 min) → 5 vertical clips (30-90s each) + subtitles + captions
```

## Quick Start

### Install

```bash
# Core (curation + subtitles)
pip install -e .

# With transcription (requires GPU or Apple Silicon)
pip install -e ".[asr]"

# Apple Silicon optimized (MLX-Whisper)
pip install -e ".[asr-mlx]"

# Everything
pip install -e ".[all]"
```

### Configure

```bash
cp .env.example .env
```

Edit `.env` with your API keys:

| Key | Where to get it | Cost |
|-----|----------------|------|
| `GROQ_API_KEY` | [groq.com](https://console.groq.com) | Free tier available |
| `HF_TOKEN` | [huggingface.co](https://huggingface.co/settings/tokens) | Free (accept pyannote terms) |

### Run

```bash
# Full pipeline: transcribe → curate → extract → subtitle
celia process video.mp4 --output ./clips --top 5

# Individual steps
celia transcribe video.mp4                 # Transcribe only
celia curate transcript.json --top 10      # Curate from transcript
celia reframe clip.mp4 --style vertical    # Reframe to 9:16
celia subtitles clip.mp4 transcript.json   # Generate subtitles
```

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     celia process                        │
├─────────────┬──────────────┬─────────────┬──────────────┤
│  Transcribe │    Curate    │   Reframe   │  Subtitles   │
│  WhisperX   │  Finder  ──→│  MediaPipe  │  ASS/SRT     │
│  + Pyannote │  Critic  ──→│  Face Track │  + Highlight  │
│  diarize    │  Ranker     │  DeepSORT   │  + Animate    │
├─────────────┴──────────────┴─────────────┴──────────────┤
│              LLM Provider (Groq / Vertex AI)             │
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
- **FFmpeg** — `brew install ffmpeg` (macOS) / `apt install ffmpeg` (Linux)
- **For ASR**: Apple Silicon (MPS) or GPU with 4GB+ VRAM
- **For Diarization**: HuggingFace token with [pyannote access](https://huggingface.co/pyannote/speaker-diarization-3.1)

## Project Structure

```
src/
├── asr/              # WhisperX transcription + speaker diarization
├── audio/            # Demucs audio separation
├── curation/         # Multi-agent clip selection
│   ├── signals/      # Text, audio, structural analyzers
│   ├── prompts.py    # LLM prompt templates
│   └── curator_v2.py # Core pipeline
├── vision/           # Face tracking + video reframing
├── subtitles/        # ASS subtitle generation
├── cli.py            # CLI entry point
└── llm_provider.py   # Multi-provider LLM client
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and guidelines.

## Cloud Solution

Need a managed, hosted solution? Contact us directly for enterprise/agency pricing.

📧 **hola@inminente.co**

## License

[Apache License 2.0](LICENSE) — Free for commercial use.

---

**Celia** — The open-source podcaster's toolkit. *By [Inminente](https://inminente.co).*
