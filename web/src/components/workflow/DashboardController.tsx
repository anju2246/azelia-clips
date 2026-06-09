import React, { useState, useEffect, useCallback } from "react";
import { Loader2, Activity } from "lucide-react";
import { UploadZone } from "./UploadZone";
import { LibraryView } from "./LibraryView";
import { LiveProcessingWidget } from "./LiveProcessingWidget";
import { SpeakerIdentificationModal } from "./SpeakerIdentificationModal";
import { BriefChatModal } from "./BriefChatModal";
import { MissingApiKeyModal } from "./MissingApiKeyModal";
import { YouTubeNudge } from "../analytics/YouTubeNudge";
import { CreditsStatusBanner } from "./CreditsStatusBanner";
import { FirstVisitHint } from "./FirstVisitHint";
import { ClipsApi, SettingsApi } from "../../lib/api";
import { getPipelineDefaults } from "../../lib/pipelineDefaults";
import { supabase } from "../../lib/supabase";
import toast from "react-hot-toast";

const API_BASE = (import.meta.env?.PUBLIC_API_URL as string) || "/api";

async function fetchWithAuth(endpoint: string, options: RequestInit = {}) {
  const headers = new Headers(options.headers || {});
  try {
    const { data } = await supabase.auth.getSession();
    if (data?.session?.access_token)
      headers.set("Authorization", `Bearer ${data.session.access_token}`);
  } catch (e) {
    /* continue */
  }
  return fetch(`${API_BASE}${endpoint}`, { ...options, headers });
}

const JOB_STORAGE_KEY = "azelia_active_job_id";

export const DashboardController: React.FC = () => {
  const [youtubeConnected, setYoutubeConnected] = useState<boolean>(false);
  const [orphanJob, setOrphanJob] = useState<{
    id: string;
    message: string;
  } | null>(null);
  const [activeJobId, setActiveJobId] = useState<string | null>(() => {
    // Recover active job from localStorage on mount
    if (typeof window !== "undefined") {
      return localStorage.getItem(JOB_STORAGE_KEY);
    }
    return null;
  });

  // API key guard state
  const [showApiKeyModal, setShowApiKeyModal] = useState(false);
  const [hasApiKey, setHasApiKey] = useState<boolean | null>(null); // null = loading
  const [pendingAction, setPendingAction] = useState<(() => void) | null>(null);
  // Speaker identification (L3) — modal shown before processing if the
  // user hasn't already labeled this episode.
  const [identifyEp, setIdentifyEp] = useState<{
    episodeNum: number;
    forceReset: boolean;
  } | null>(null);
  // Brief gate — modal shown when a job parks at awaiting_brief (after
  // curation, before the heavy render). Set by LiveProcessingWidget.
  const [briefJobId, setBriefJobId] = useState<string | null>(null);

  // Fetch YouTube connection status so the Pro card doesn't nudge
  // users who already connected during onboarding.
  useEffect(() => {
    fetchWithAuth("/analytics/youtube/status")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (d?.connected) setYoutubeConnected(true);
      })
      .catch(() => {});
  }, []);

  // Check if user has any AI provider (API key or Claude Code)
  useEffect(() => {
    const checkKeys = async () => {
      try {
        // First check Claude Code — if active, no API key needed
        const { data } = await supabase.auth.getSession();
        const token = data.session?.access_token;
        if (token) {
          const res = await fetch(`${API_BASE}/providers`, {
            headers: { Authorization: `Bearer ${token}` },
          });
          if (res.ok) {
            const providerData = await res.json();
            if (providerData.claude_code?.active) {
              setHasApiKey(true);
              return;
            }
          }
        }
        // Fall back to checking API keys
        const settings = await SettingsApi.getSettings();
        const keys = [
          settings.groq_api_key,
          settings.openai_api_key,
          settings.anthropic_api_key,
          settings.gcp_project_id,
        ];
        const hasReal = keys.some(
          (k) => typeof k === "string" && k.trim().length >= 8,
        );
        setHasApiKey(hasReal);
      } catch {
        setHasApiKey(false);
      }
    };
    checkKeys();
  }, []);

  // Check if recovered job is still active
  useEffect(() => {
    if (!activeJobId) return;

    const checkJob = async () => {
      try {
        const job = await ClipsApi.getJob(activeJobId);
        if (
          job.status === "completed" ||
          job.status === "error" ||
          job.status === "failed"
        ) {
          // Job already finished — clear it
          clearActiveJob();
          if (job.status === "completed") {
            toast.success(`Previous job completed: ${job.message}`);
          } else {
            toast.error(`Previous job failed: ${job.error || job.message}`);
          }
        }
        // If still running, the LiveProcessingWidget will take over
      } catch {
        // Job not found — clear stale reference
        clearActiveJob();
      }
    };

    checkJob();
  }, []);

  // Poll for orphan jobs — jobs running on the server that aren't in localStorage.
  // This lets the user reconnect after dismissing the widget.
  useEffect(() => {
    if (activeJobId) return; // Already tracking a job
    let cancelled = false;

    const check = async () => {
      try {
        const history = await ClipsApi.getHistory();
        const running = history.find(
          (j: any) =>
            j.status === "processing" ||
            j.status === "pending" ||
            j.status === "resuming" ||
            j.status === "paused",
        );
        if (!cancelled) {
          setOrphanJob(
            running
              ? {
                  id: running.id,
                  message:
                    running.message || `Processing ${running.filename}...`,
                }
              : null,
          );
        }
      } catch {
        /* ignore */
      }
    };

    check();
    // Poll every 15s (was 5s) — orphan jobs are rare and 109 episodes is heavy disk I/O.
    const interval = setInterval(check, 15000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [activeJobId]);

  const setAndPersistJobId = (jobId: string) => {
    setActiveJobId(jobId);
    localStorage.setItem(JOB_STORAGE_KEY, jobId);
    // The scroll container is <main class="overflow-y-auto">, not window
    const main = document.querySelector("main");
    if (main) {
      main.scrollTo({ top: 0, behavior: "smooth" });
    } else {
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
  };

  const clearActiveJob = () => {
    setActiveJobId(null);
    localStorage.removeItem(JOB_STORAGE_KEY);
  };

  // Guard wrapper: checks for API key before running the action
  const guardWithApiKey = (action: () => void) => {
    if (hasApiKey === false) {
      setPendingAction(() => action);
      setShowApiKeyModal(true);
    } else {
      action();
    }
  };

  // Actually trigger the backend processing. Called after the user
  // either labels speakers in the modal or skips it. force_reset wipes
  // cached curation/clips when the user came in via "Process Again".
  const launchProcess = async (episodeNum: number, forceReset: boolean) => {
    const loadingToast = toast.loading("Starting episode processing...");
    try {
      const response = await ClipsApi.processEpisode(episodeNum, {
        ...getPipelineDefaults(),
        ...(forceReset ? { force_reset: true } : {}),
      });
      toast.success("Episode processing started!", { id: loadingToast });
      setAndPersistJobId(response.id);
    } catch (error: any) {
      console.error(error);
      toast.error(error.message || "Failed to process episode", {
        id: loadingToast,
      });
    }
  };

  // Entry-point: before kicking off processing, gate on whether the
  // user has already identified speakers for this episode. If not,
  // open the L3 modal; otherwise go straight to render.
  const ensureIdentifiedThenProcess = async (
    episodeNum: number,
    forceReset = false,
  ) => {
    try {
      const status = await ClipsApi.identifyStatus(episodeNum);
      if (status.labeled || status.skipped) {
        await launchProcess(episodeNum, forceReset);
      } else {
        setIdentifyEp({ episodeNum, forceReset });
      }
    } catch (e: any) {
      // If status fails (network etc.), fall back to direct launch so
      // we never block the user on a broken pre-flight.
      console.error("identifyStatus failed", e);
      await launchProcess(episodeNum, forceReset);
    }
  };

  const handleProcessEpisode = async (episodeNum: number) => {
    guardWithApiKey(async () => {
      await ensureIdentifiedThenProcess(episodeNum, false);
    });
  };

  const handleResumeEpisode = async (episodeNum: number) => {
    guardWithApiKey(async () => {
      const jobId = `EP${String(episodeNum).padStart(3, "0")}-process`;
      const loadingToast = toast.loading("Resuming…");
      try {
        await ClipsApi.resumeJob(jobId);
        toast.success("Resuming processing", { id: loadingToast });
        setAndPersistJobId(jobId);
      } catch (error: any) {
        toast.error(error.message || "Could not resume", {
          id: loadingToast,
        });
      }
    });
  };

  const handleResetEpisode = async (episodeNum: number) => {
    guardWithApiKey(async () => {
      await ensureIdentifiedThenProcess(episodeNum, true);
    });
  };

  const handleUploadProcess = (jobId: string) => {
    setAndPersistJobId(jobId);
  };

  const scrollToUpload = () => {
    if (typeof document === "undefined") return;
    const el = document.getElementById("upload-zone");
    if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
  };

  return (
    <div className="flex flex-col gap-12">
      {/* Active job widget — inline at the top, dashboard stays visible below */}
      {activeJobId && (
        <LiveProcessingWidget
          jobId={activeJobId}
          onAwaitingBrief={() => setBriefJobId(activeJobId)}
          onJobComplete={() => {
            // Keep showing so user can click "Review Clips"
          }}
          onDismiss={() => {
            clearActiveJob();
          }}
          onCancel={async () => {
            if (
              !window.confirm(
                "Cancel this job? In-flight clips will be killed and the workspace wiped. This cannot be undone.",
              )
            ) {
              return;
            }
            const t = toast.loading("Cancelling job…");
            try {
              await ClipsApi.cancelJob(activeJobId);
              toast.success("Job cancelled and workspace cleaned", { id: t });
              clearActiveJob();
            } catch (e: any) {
              toast.error(e?.message || "Cancel failed", { id: t });
            }
          }}
          onPause={async () => {
            const t = toast.loading("Pausing pipeline…");
            try {
              const r = await ClipsApi.pauseJob(activeJobId);
              const killed = r?.killed_subprocesses ?? 0;
              toast.success(
                killed > 0
                  ? `Paused — killed ${killed} in-flight render${killed === 1 ? "" : "s"}`
                  : "Paused at next clip boundary",
                { id: t },
              );
            } catch (e: any) {
              toast.error(e?.message || "Pause failed", { id: t });
            }
          }}
          onResume={async () => {
            const t = toast.loading("Resuming…");
            try {
              await ClipsApi.resumeJob(activeJobId);
              toast.success("Resumed — picking up from the last checkpoint", {
                id: t,
              });
            } catch (e: any) {
              toast.error(e?.message || "Resume failed", { id: t });
            }
          }}
        />
      )}

      {/* Orphan job banner — shown when a job is running but the widget was dismissed */}
      {!activeJobId && orphanJob && (
        <div className="flex items-center justify-between gap-4 px-4 py-3 bg-zinc-800 border border-zinc-700 rounded-xl">
          <div className="flex items-center gap-3">
            <Loader2 className="w-4 h-4 text-brand-400 animate-spin flex-shrink-0" />
            <div>
              <p className="text-sm font-medium text-white">
                Procesamiento en curso
              </p>
              <p className="text-xs text-zinc-400">{orphanJob.message}</p>
            </div>
          </div>
          <button
            onClick={() => setAndPersistJobId(orphanJob.id)}
            className="flex items-center gap-2 px-4 py-2 bg-brand-600 hover:bg-brand-500 text-white text-sm font-semibold rounded-lg transition-colors flex-shrink-0"
          >
            <Activity className="w-4 h-4" />
            Ver progreso
          </button>
        </div>
      )}

      {/* 0. First-visit acknowledgment — shown once, then dismissed. */}
      <FirstVisitHint onScrollToUpload={scrollToUpload} />

      {/* 1. Single nudge slot — one card at a time, priority: Pro → YouTube.
                  Pro is shown to free users. Once on Pro, YouTube nudge appears
                  until connected. Dismiss is session-only for YouTube so it keeps
                  showing on future visits until the user actually connects. */}
      {/* Pro tier removed in v0.1.0 */}

      {/* 2. Alerts — credits banner only shows when something's wrong. */}
      <CreditsStatusBanner />

      {/* 3. Primary workflow: library of processed episodes. */}
      <LibraryView
        onProcessEpisode={handleProcessEpisode}
        onResumeEpisode={handleResumeEpisode}
        onResetEpisode={handleResetEpisode}
      />

      {/* 3. Divider + manual upload fallback. */}
      <div className="relative">
        <div className="absolute inset-0 flex items-center" aria-hidden="true">
          <div className="w-full border-t border-white/5"></div>
        </div>
        <div className="relative flex justify-center">
          <span className="bg-zinc-950 px-4 text-sm text-zinc-500 uppercase tracking-widest">
            Or upload manually
          </span>
        </div>
      </div>

      <div id="upload-zone">
        <UploadZone
          onJobStarted={handleUploadProcess}
          requireApiKey={() => {
            if (hasApiKey === false) {
              setShowApiKeyModal(true);
              return false;
            }
            return true;
          }}
        />
      </div>

      <MissingApiKeyModal
        isOpen={showApiKeyModal}
        onClose={() => {
          setShowApiKeyModal(false);
          setPendingAction(null);
        }}
        onKeySaved={() => {
          setShowApiKeyModal(false);
          setHasApiKey(true);
          // Run the pending action if any
          if (pendingAction) {
            pendingAction();
            setPendingAction(null);
          }
        }}
      />

      {identifyEp && (
        <SpeakerIdentificationModal
          episodeNum={identifyEp.episodeNum}
          onClose={() => setIdentifyEp(null)}
          onConfirm={() => {
            const ep = identifyEp;
            setIdentifyEp(null);
            if (ep) launchProcess(ep.episodeNum, ep.forceReset);
          }}
        />
      )}

      {briefJobId && (
        <BriefChatModal
          jobId={briefJobId}
          onClose={() => setBriefJobId(null)}
          onApproved={() => setBriefJobId(null)}
        />
      )}
    </div>
  );
};
