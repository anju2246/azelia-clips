import type { ProcessRequest } from "./api";

const STORAGE_KEY = "azelia_pipeline_defaults";

const HARD_DEFAULTS: Required<
  Pick<
    ProcessRequest,
    | "min_duration"
    | "max_duration"
    | "min_score"
    | "subtitle_style"
    | "transcription_source"
  >
> = {
  min_duration: 30,
  max_duration: 90,
  min_score: 70,
  subtitle_style: "highlight",
  transcription_source: "local_whisper",
};

export function getPipelineDefaults(): typeof HARD_DEFAULTS {
  if (typeof window === "undefined") return { ...HARD_DEFAULTS };
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return { ...HARD_DEFAULTS };
    const parsed = JSON.parse(raw);
    return {
      min_duration:
        typeof parsed.min_duration === "number"
          ? parsed.min_duration
          : HARD_DEFAULTS.min_duration,
      max_duration:
        typeof parsed.max_duration === "number"
          ? parsed.max_duration
          : HARD_DEFAULTS.max_duration,
      min_score:
        typeof parsed.min_score === "number"
          ? parsed.min_score
          : HARD_DEFAULTS.min_score,
      subtitle_style:
        typeof parsed.subtitle_style === "string"
          ? parsed.subtitle_style
          : HARD_DEFAULTS.subtitle_style,
      transcription_source:
        typeof parsed.transcription_source === "string"
          ? parsed.transcription_source
          : HARD_DEFAULTS.transcription_source,
    };
  } catch {
    return { ...HARD_DEFAULTS };
  }
}

export function savePipelineDefaults(cfg: Partial<typeof HARD_DEFAULTS>) {
  if (typeof window === "undefined") return;
  try {
    const merged = { ...getPipelineDefaults(), ...cfg };
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(merged));
  } catch {
    // localStorage may be disabled — silently ignore.
  }
}
