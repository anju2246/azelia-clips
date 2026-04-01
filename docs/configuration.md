# Configuration Reference

> **For contributors and developers only.**
> End users configure Azelia through the Dashboard UI — no manual file editing needed.

## Environment Variables

Azelia Clips uses a `.env` file for local configuration. The Dashboard generates this file automatically during the setup wizard. If you're developing or contributing, create a `.env` in the project root with these variables:

### Required

| Variable | Description | How to get it |
|---|---|---|
| `GROQ_API_KEY` | Groq API key for LLM inference | [console.groq.com](https://console.groq.com) |

### AI Providers (optional — choose one or more)

| Variable | Description |
|---|---|
| `GROQ_API_KEY_2` | Secondary Groq key (fallback) |
| `ANTHROPIC_API_KEY` | Anthropic Claude API key |
| `GCP_PROJECT_ID` | Google Cloud project ID (for Vertex AI Gemini) |
| `GCP_LOCATION` | GCP region (default: `us-central1`) |

### Whisper (Speech-to-Text)

| Variable | Default | Description |
|---|---|---|
| `WHISPER_MODEL` | `large-v3` | Model size: `tiny`, `base`, `small`, `medium`, `large-v3` |
| `WHISPER_DEVICE` | `mps` | Device: `mps` (Mac), `cuda` (NVIDIA), `cpu` |
| `WHISPER_COMPUTE_TYPE` | `float16` | Compute type for inference |

### Speaker Diarization (optional)

| Variable | Description |
|---|---|
| `HF_TOKEN` | HuggingFace token for Pyannote diarization models |

### Clip Settings

| Variable | Default | Description |
|---|---|---|
| `CLIP_MIN_DURATION` | `15` | Minimum clip duration (seconds) |
| `CLIP_MAX_DURATION` | `90` | Maximum clip duration (seconds) |
| `CLIP_TOP_N` | `10` | Number of top clips to extract |

### Paths

| Variable | Default | Description |
|---|---|---|
| `OUTPUT_DIR` | `./output` | Output directory for processed clips |
| `PODCAST_DIR` | `external_drive/MyPodcast` | Path to podcast episodes folder |
| `PODCAST_NAME` | `My Podcast` | Podcast name (used in captions) |

### Supabase (pre-configured — do not change unless you know what you're doing)

| Variable | Description |
|---|---|
| `SUPABASE_URL` | Azelia Central project URL (auth + telemetry) |
| `SUPABASE_KEY` | Azelia Central anon key (public by design) |
| `SUPABASE_JWT_SECRET` | JWT secret for token validation |

### User's Own Supabase (optional — for importing transcriptions)

| Variable | Description |
|---|---|
| `USER_SUPABASE_URL` | User's Supabase project URL |
| `USER_SUPABASE_KEY` | User's Supabase anon key |

### Telemetry

| Variable | Default | Description |
|---|---|---|
| `AZELIA_TELEMETRY_OPT_OUT` | `false` | Set to `true` to disable anonymized telemetry |

## Notes

- The Dashboard setup wizard generates this file automatically for end users
- Supabase Central credentials come pre-configured — users don't need to set them
- Only `GROQ_API_KEY` is strictly required to start processing
- All paths support absolute and relative formats
