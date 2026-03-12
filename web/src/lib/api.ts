// Azelia Clips API Client
// Interfaces matching server/models.py

export type JobStatus = 'pending' | 'processing' | 'paused' | 'resuming' | 'completed' | 'error' | 'failed' | 'cancelled';

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
  gcp_project_id?: string;
  vertex_model?: string;
  transcript_supabase_url?: string;
  transcript_supabase_key?: string;
  generate_teasers?: boolean;
}

export interface UpdateSettingsRequest {
  podcast_name?: string;
  podcast_dir?: string;
  ai_provider_order?: string[];
  groq_api_key?: string;
  groq_model?: string;
  openai_api_key?: string;
  openai_model?: string;
  anthropic_api_key?: string;
  anthropic_model?: string;
  gcp_project_id?: string;
  vertex_model?: string;
  transcript_supabase_url?: string;
  transcript_supabase_key?: string;
  generate_teasers?: boolean;
}

export interface EpisodeResponse {
  id: string;
  number: number;
  title: string;
  has_video: boolean;
  has_transcript: boolean;
  is_processed: boolean;
  path: string;
}

export interface IntelligenceInsights {
  average_score: number;
  top_categories: Record<string, number>;
  top_identities: Record<string, number>;
}

// Global API Configuration
const API_BASE = (import.meta.env?.PUBLIC_API_URL as string) || '/api';

import { supabase } from './supabase';

/**
 * Helper for making typed fetch requests
 */
async function fetchApi<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const url = `${API_BASE}${endpoint}`;

  // Default headers (can be overridden by options.headers)
  const headers = new Headers(options.headers || {});
  if (!headers.has('Accept')) {
    headers.set('Accept', 'application/json');
  }

  // Inject Auth token from Supabase session
  if (!headers.has('Authorization')) {
    try {
      const { data } = await supabase.auth.getSession();
      if (data?.session?.access_token) {
        headers.set('Authorization', `Bearer ${data.session.access_token}`);
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
  // Episodes
  getEpisodes: () => fetchApi<EpisodeResponse[]>('/episodes'),

  processEpisode: (episodeNum: number, req: ProcessRequest = {}) =>
    fetchApi<JobResponse>(`/episodes/${episodeNum}/process`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req)
    }),

  // Jobs
  getJob: (jobId: string) => fetchApi<JobResponse>(`/jobs/${jobId}`),

  // File Upload Process (Fallback if no episodes folder)
  processVideo: (file: File, req: ProcessRequest) => {
    const formData = new FormData();
    formData.append('file', file);

    // Append other form fields
    Object.entries(req).forEach(([key, value]) => {
      if (value !== undefined) {
        formData.append(key, String(value));
      }
    });

    return fetchApi<JobResponse>('/process', {
      method: 'POST',
      body: formData
    });
  },

  // Zero-upload local processing
  processLocalVideo: (req: ProcessLocalRequest) =>
    fetchApi<JobResponse>('/process-local', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req)
    }),

  // Approve a clip (stub for API implementation)
  approveClip: (clipId: number) =>
    fetchApi<any>(`/clips/${clipId}/approve`, { method: 'POST' }),
};

// --- SETTINGS API ---

export const SettingsApi = {
  getSettings: () => fetchApi<SettingsResponse>('/settings'),

  updateSettings: (req: UpdateSettingsRequest) =>
    fetchApi<SettingsResponse>('/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req)
    })
};

// --- INTELLIGENCE & ANALYTICS API ---

export const IntelligenceApi = {
  getInsights: () => fetchApi<IntelligenceInsights>('/analytics/insights'),

  getYouTubeStatus: () => fetchApi<any>('/connections/youtube'),

  fetchYouTubeAnalytics: () => fetchApi<any>('/analytics/fetch-youtube', { method: 'POST' })
};

/**
 * Helper to construct WebSocket URLs.
 * Handles both absolute (http://...) and relative (/api) API_BASE values.
 */
export function getWebSocketUrl(endpoint: string): string {
  if (API_BASE.startsWith('http')) {
    // Absolute URL: just swap protocol
    const wsBase = API_BASE.replace(/^http/, 'ws');
    return `${wsBase}${endpoint}`;
  }
  // Relative URL: build from current window location
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${window.location.host}${API_BASE}${endpoint}`;
}
