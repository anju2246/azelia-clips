// Azelia Clips API Client
// Interfaces matching server/models.py

export type JobStatus =
  | "pending"
  | "processing"
  | "awaiting_brief"
  | "paused"
  | "resuming"
  | "completed"
  | "error"
  | "failed"
  | "cancelled";

// ── Conversational brief (human-in-the-loop gate, pre-render) ──────────
export interface BriefCandidate {
  id: number;
  start_time: number;
  end_time: number;
  title: string;
  summary: string;
  reasoning: string;
  score: number;
  critic_approved: boolean;
  above_threshold: boolean;
  selected: boolean;
  origin: "curation" | "rescued" | "found";
}

export interface BriefChatMessage {
  role: "user" | "assistant";
  content: string;
  change_summary?: string | null;
}

export interface BriefCounts {
  selected: number;
  total: number;
  discarded: number;
}

export interface BriefResponse {
  status: string;
  episode_id: string;
  candidates: BriefCandidate[];
  messages: BriefChatMessage[];
  counts: BriefCounts;
}

export interface BriefMessageResponse extends BriefResponse {
  reply: string;
  change_summary: string;
  actions: Array<Record<string, unknown>>;
}

export interface Clip {
  id: number;
  filename: string;
  start_time: number;
  end_time: number;
  duration: number;
  virality_score: number;
  title: string;
  summary: string;
  status: string; // 'approved', 'review'
  download_url?: string;
  thumbnail_url?: string;
}

export interface JobResponse {
  id: string;
  status: JobStatus;
  filename: string;
  created_at: string; // ISO datetime
  progress: number;
  message: string;
  clips: Clip[];
  error?: string;
}

export interface ProcessRequest {
  min_duration?: number;
  max_duration?: number;
  min_score?: number;
  subtitle_style?: string;
  transcription_source?: string;
  assemblyai_key?: string;
  supabase_url?: string;
  supabase_key?: string;
}

export interface ProcessLocalRequest extends ProcessRequest {
  video_path: string;
}

export interface SettingsResponse {
  podcast_name: string;
  podcast_dir: string;
  ai_provider_order?: string[];
  groq_api_key?: string;
  groq_model?: string;
  openai_api_key?: string;
  openai_model?: string;
  anthropic_api_key?: string;
  anthropic_model?: string;
  google_api_key?: string;
  google_model?: string;
  gcp_project_id?: string;
  vertex_model?: string;
  transcript_supabase_url?: string;
  transcript_supabase_key?: string;
  review_brief_before_processing?: boolean;
}

export interface UpdateSettingsRequest {
  podcast_name?: string;
  podcast_dir?: string;
  review_brief_before_processing?: boolean;
  ai_provider_order?: string[];
  groq_api_key?: string;
  groq_model?: string;
  openai_api_key?: string;
  openai_model?: string;
  anthropic_api_key?: string;
  anthropic_model?: string;
  google_api_key?: string;
  google_model?: string;
  gcp_project_id?: string;
  vertex_model?: string;
  transcript_supabase_url?: string;
  transcript_supabase_key?: string;
}

export interface CriticDecision {
  start_time: number;
  end_time: number;
  duration: number;
  title: string | null;
  summary: string | null;
  reasoning: string | null;
  approved: boolean;
  user_verdict: "agree" | "disagree" | "neutral" | null;
  user_note: string | null;
}

export interface EpisodeResponse {
  id: string;
  number: number;
  title: string;
  has_video: boolean;
  has_transcript: boolean;
  is_processed: boolean;
  path: string;
  job_status?:
    | "processing"
    | "paused"
    | "pending"
    | "resuming"
    | "completed"
    | "failed"
    | "cancelled"
    | null;
  job_progress?: number | null;
}

export interface IntelligenceInsights {
  average_score: number;
  top_categories: Record<string, number>;
  top_identities: Record<string, number>;
}

// Global API Configuration
const API_BASE = (import.meta.env?.PUBLIC_API_URL as string) || "/api";

import { supabase } from "./supabase";

/**
 * Helper for making typed fetch requests
 */
async function fetchApi<T>(
  endpoint: string,
  options: RequestInit = {},
): Promise<T> {
  const url = `${API_BASE}${endpoint}`;

  // Default headers (can be overridden by options.headers)
  const headers = new Headers(options.headers || {});
  if (!headers.has("Accept")) {
    headers.set("Accept", "application/json");
  }

  // Inject Auth token from Supabase session
  if (!headers.has("Authorization")) {
    try {
      const { data } = await supabase.auth.getSession();
      if (data?.session?.access_token) {
        headers.set("Authorization", `Bearer ${data.session.access_token}`);
      }
    } catch (e) {
      // Silently continue — the backend will return 401 if auth is required
    }
  }

  const response = await fetch(url, { ...options, headers });

  if (!response.ok) {
    let errorMsg = `API Error ${response.status}: ${response.statusText}`;
    try {
      const errData = await response.json();
      errorMsg = errData.detail || errorMsg;
    } catch (e) {
      // Not JSON
    }
    throw new Error(errorMsg);
  }

  return response.json() as Promise<T>;
}

// --- CLIPS & EPISODES API ---

export const ClipsApi = {
  // Episodes / History
  getEpisodes: () => fetchApi<EpisodeResponse[]>("/episodes"),
  getHistory: () => fetchApi<any[]>("/jobs/history"),

  processEpisode: (episodeNum: number, req: ProcessRequest = {}) =>
    fetchApi<JobResponse>(`/episodes/${episodeNum}/process`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    }),

  // Jobs
  getJob: (jobId: string) => fetchApi<JobResponse>(`/jobs/${jobId}`),

  pauseJob: (jobId: string) =>
    fetchApi<{ status: string; job_id: string; killed_subprocesses?: number }>(
      `/jobs/${jobId}/pause`,
      { method: "POST" },
    ),

  resumeJob: (jobId: string) =>
    fetchApi<{ status: string; job_id: string; resuming_from_clip?: number }>(
      `/jobs/${jobId}/resume`,
      { method: "POST" },
    ),

  cancelJob: (jobId: string) =>
    fetchApi<{
      status: string;
      job_id: string;
      killed_subprocesses?: number;
      workspace_removed?: boolean;
    }>(`/jobs/${jobId}/cancel`, { method: "POST" }),

  // ── Speaker identification (L3) ────────────────────────────────────

  identifyStatus: (episodeNum: number) =>
    fetchApi<{
      labeled: boolean;
      skipped: boolean;
      labels: Record<
        string,
        { name: string; face_ids?: string[]; face_id?: string }
      > | null;
    }>(`/episodes/${episodeNum}/identify/status`),

  identifyPrepare: (episodeNum: number, numSpeakers?: number) =>
    fetchApi<{
      episode_id: string;
      faces: string[];
      speakers: string[];
      existing_labels: Record<
        string,
        { name: string; face_ids?: string[]; face_id?: string }
      > | null;
    }>(`/episodes/${episodeNum}/identify/prepare`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(
        numSpeakers ? { num_speakers: numSpeakers } : {},
      ),
    }),

  identifyFaceUrl: (episodeNum: number, faceId: string) =>
    `/api/episodes/${episodeNum}/identify/face/${faceId}.jpg`,

  identifyAudioUrl: (episodeNum: number, speakerId: string) =>
    `/api/episodes/${episodeNum}/identify/audio/${speakerId}.wav`,

  identifySaveLabels: (
    episodeNum: number,
    payload: {
      skipped?: boolean;
      labels?: Record<string, { name: string; face_ids: string[] }>;
    },
  ) =>
    fetchApi<{ status: string; count?: number }>(
      `/episodes/${episodeNum}/identify/labels`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    ),

  identifyClearLabels: (episodeNum: number) =>
    fetchApi<{ status: string }>(`/episodes/${episodeNum}/identify/labels`, {
      method: "DELETE",
    }),

  getCriticLearnings: () =>
    fetchApi<{
      count: number;
      learnings: Array<{
        id: number;
        text: string;
        category: string | null;
        evidence_count: number;
        created_at: string;
        updated_at: string;
      }>;
    }>("/critic-learnings"),

  getCriticDecisions: (jobId: string) =>
    fetchApi<{
      episode_id: string;
      available: boolean;
      approved: CriticDecision[];
      rejected: CriticDecision[];
      counts?: { approved: number; rejected: number };
      message?: string;
    }>(`/jobs/${jobId}/critic-decisions`),

  saveCriticFeedback: (payload: {
    episode_id: string;
    start_time: number;
    end_time: number;
    title?: string | null;
    summary?: string | null;
    critic_reasoning?: string | null;
    user_verdict: "agree" | "disagree" | "neutral";
    user_note?: string | null;
  }) =>
    fetchApi<{ status: string; id: number }>("/critic-feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  // File Upload Process (Fallback if no episodes folder)
  processVideo: (file: File, req: ProcessRequest) => {
    const formData = new FormData();
    formData.append("file", file);

    // Append other form fields
    Object.entries(req).forEach(([key, value]) => {
      if (value !== undefined) {
        formData.append(key, String(value));
      }
    });

    return fetchApi<JobResponse>("/process", {
      method: "POST",
      body: formData,
    });
  },

  // Zero-upload local processing
  processLocalVideo: (req: ProcessLocalRequest) =>
    fetchApi<JobResponse>("/process-local", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    }),

  // Approve a clip (move from review/ to approved/)
  approveClip: (jobId: string, filename: string) =>
    fetchApi<any>(`/clips/${jobId}/${filename}/approve`, { method: "POST" }),

  // Reject a clip (move to rejected/, auto-deleted after 30 days)
  rejectClip: (jobId: string, filename: string) =>
    fetchApi<any>(`/clips/${jobId}/${filename}/reject`, { method: "POST" }),

  // List rejected clips for a job
  getRejectedClips: (jobId: string) =>
    fetchApi<any[]>(`/clips/${jobId}/rejected`),

  // Restore a rejected clip back to review
  restoreClip: (jobId: string, filename: string) =>
    fetchApi<any>(`/clips/${jobId}/${filename}/restore`, { method: "POST" }),

  // Open clip location in Finder (macOS)
  openClipLocation: (jobId: string, filename: string) =>
    fetchApi<any>(`/clips/${jobId}/${filename}/open`, { method: "POST" }),

  // ── Conversational brief ─────────────────────────────────────────
  getBrief: (jobId: string) =>
    fetchApi<BriefResponse>(`/jobs/${jobId}/brief`),

  sendBriefMessage: (jobId: string, message: string) =>
    fetchApi<BriefMessageResponse>(`/jobs/${jobId}/brief/message`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    }),

  approveBrief: (jobId: string, selectedIds?: number[]) =>
    fetchApi<{ status: string; approved_count: number }>(
      `/jobs/${jobId}/brief/approve`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(
          selectedIds ? { selected_ids: selectedIds } : {},
        ),
      },
    ),
};

// --- SETTINGS API ---

export const SettingsApi = {
  getSettings: () => fetchApi<SettingsResponse>("/settings"),
  getModels: () => fetchApi<{ data: any[] }>("/models"),
  refreshModels: () =>
    fetchApi<{ data: any[] }>("/models/refresh", { method: "POST" }),

  updateSettings: (req: UpdateSettingsRequest) =>
    fetchApi<SettingsResponse>("/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    }),
};

// --- INTELLIGENCE & ANALYTICS API ---

export const IntelligenceApi = {
  getInsights: () => fetchApi<IntelligenceInsights>("/analytics/insights"),

  getYouTubeStatus: () => fetchApi<any>("/connections/youtube"),

  fetchYouTubeAnalytics: () =>
    fetchApi<any>("/analytics/fetch-youtube", { method: "POST" }),
};

/**
 * Helper to construct WebSocket URLs.
 * Handles both absolute (http://...) and relative (/api) API_BASE values.
 */
export function getWebSocketUrl(endpoint: string): string {
  if (API_BASE.startsWith("http")) {
    // Absolute URL: just swap protocol
    const wsBase = API_BASE.replace(/^http/, "ws");
    return `${wsBase}${endpoint}`;
  }
  // Relative URL: build from current window location
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}${API_BASE}${endpoint}`;
}
