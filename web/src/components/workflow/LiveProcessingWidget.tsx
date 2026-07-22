import React, { useEffect, useState, useRef } from "react";
import {
  Loader2,
  CheckCircle2,
  AlertTriangle,
  ExternalLink,
  Play,
} from "lucide-react";
import { ClipsApi, type JobResponse, getWebSocketUrl } from "../../lib/api";
import { supabase } from "../../lib/supabase";
import toast from "react-hot-toast";

interface LiveProcessingWidgetProps {
  jobId: string;
  onJobComplete: () => void;
  onCancel: () => void;
  onPause?: () => void;
  onResume?: () => void;
  onAwaitingBrief?: () => void;
  onAwaitingFraming?: () => void;
  /** Drop the widget without touching the job — for jobs already finished. */
  onDismiss?: () => void;
}

export const LiveProcessingWidget: React.FC<LiveProcessingWidgetProps> = ({
  jobId,
  onJobComplete,
  onCancel,
  onPause,
  onResume,
  onAwaitingBrief,
  onAwaitingFraming,
  onDismiss,
}) => {
  const [job, setJob] = useState<JobResponse | null>(null);
  const [wsStatus, setWsStatus] = useState<
    "connecting" | "connected" | "disconnected"
  >("connecting");
  const wsRef = useRef<WebSocket | null>(null);
  const briefFiredRef = useRef(false);
  const framingFiredRef = useRef(false);
  const completedFiredRef = useRef(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Fire each gate once when the job parks on it.
  const maybeFireBrief = (status?: string) => {
    if (status === "awaiting_brief" && !briefFiredRef.current) {
      briefFiredRef.current = true;
      onAwaitingBrief?.();
    }
    if (status === "awaiting_framing" && !framingFiredRef.current) {
      framingFiredRef.current = true;
      onAwaitingFraming?.();
    }
  };

  // Fire completion once, whether it arrives via WS or the poll fallback.
  const markComplete = () => {
    if (completedFiredRef.current) return;
    completedFiredRef.current = true;
    onJobComplete();
  };

  // Initial fetch + WS for live updates + a polling fallback so the widget
  // (and the brief gate) keep working even when the WS can't connect (e.g.
  // the dev proxy doesn't forward WebSockets, or the socket drops).
  useEffect(() => {
    fetchJobStatus();
    connectWebSocket();
    pollRef.current = setInterval(fetchJobStatus, 3000);

    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [jobId]);

  const fetchJobStatus = async () => {
    try {
      const data = await ClipsApi.getJob(jobId);
      setJob(data);
      maybeFireBrief(data.status);
      if (
        data.status === "completed" ||
        data.status === "error" ||
        data.status === "failed"
      ) {
        if (pollRef.current) {
          clearInterval(pollRef.current);
          pollRef.current = null;
        }
        if (wsRef.current) wsRef.current.close();
        if (data.status === "completed") markComplete();
      }
    } catch (error) {
      console.error("Failed to fetch job", error);
      toast.error("Failed to get job status");
    }
  };

  const connectWebSocket = async () => {
    const { data: authData } = await supabase.auth.getSession();
    const token = authData?.session?.access_token || "";
    const wsUrl = getWebSocketUrl(`/ws/jobs/${jobId}`) + `?token=${token}`;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => setWsStatus("connected");
    ws.onclose = () => setWsStatus("disconnected");

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.event === "progress") {
          setJob((prev) =>
            prev
              ? {
                  ...prev,
                  progress: msg.data.progress,
                  message: msg.data.message,
                  status: msg.data.status || prev.status,
                }
              : null,
          );
          maybeFireBrief(msg.data.status);
        } else if (msg.event === "error") {
          setJob((prev) =>
            prev ? { ...prev, status: "error", error: msg.data.error } : null,
          );
          toast.error(`Processing error: ${msg.data.error}`);
        } else if (msg.event === "completed") {
          setJob((prev) =>
            prev
              ? {
                  ...prev,
                  status: "completed",
                  progress: 100,
                  message: "Done!",
                }
              : null,
          );
          toast.success("Clips generated successfully!");
          markComplete();
        }
      } catch (e) {
        console.error("WS Parse error", e);
      }
    };
  };

  if (!job) {
    return (
      <div className="w-full max-w-2xl mx-auto mt-10 p-8 rounded-2xl glass-card border border-white/5 animate-pulse">
        <div className="h-6 w-1/3 bg-zinc-800 rounded mb-6"></div>
        <div className="h-2 w-full bg-zinc-800 rounded-full mb-4"></div>
        <div className="h-4 w-1/2 bg-zinc-800 rounded"></div>
      </div>
    );
  }

  const isCompleted = job.status === "completed";
  // The store writes `failed`; the API enum calls it `error`. Both are terminal,
  // and treating only one as such leaves the widget spinning forever.
  const isError = job.status === "error" || job.status === "failed";
  const progressPercent = job.progress || 0;

  return (
    <div className="w-full max-w-2xl mx-auto mt-10">
      <div className="bg-zinc-900/40 backdrop-blur-xl border border-white/10 p-8 rounded-2xl shadow-2xl relative overflow-hidden">
        {/* Animated background glow */}
        {!isCompleted && !isError && (
          <div
            className="absolute top-0 left-0 h-1 bg-brand-500 transition-all duration-500 shadow-[0_0_20px_rgba(34,197,94,0.4)]"
            style={{ width: `${progressPercent}%` }}
          />
        )}

        {isCompleted && (
          <div className="absolute top-0 left-0 h-1 w-full bg-green-500" />
        )}
        {isError && (
          <div className="absolute top-0 left-0 h-1 w-full bg-red-500" />
        )}

        <div className="flex items-start justify-between mb-8">
          <div>
            <h2 className="text-2xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-white to-zinc-400">
              Processing Engine
            </h2>
            <div className="flex items-center gap-2 mt-2">
              <span
                className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
                  wsStatus === "connected"
                    ? "bg-green-500/10 text-green-400 border border-green-500/20"
                    : wsStatus === "connecting"
                      ? "bg-yellow-500/10 text-yellow-500 border border-yellow-500/20"
                      : "bg-red-500/10 text-red-500 border border-red-500/20"
                }`}
              >
                {wsStatus === "connected" ? "● Live" : "○ Offline"}
              </span>
              <span className="text-zinc-500 text-sm font-mono">{job.id}</span>
            </div>
          </div>

          {!isCompleted && !isError && (
            <div className="w-12 h-12 rounded-full bg-brand-500/10 flex items-center justify-center animate-pulse">
              <Loader2 className="w-6 h-6 text-brand-400 animate-spin" />
            </div>
          )}
          {isCompleted && (
            <div className="w-12 h-12 rounded-full bg-green-500/10 flex items-center justify-center">
              <CheckCircle2 className="w-6 h-6 text-green-500" />
            </div>
          )}
          {isError && (
            <div className="w-12 h-12 rounded-full bg-red-500/10 flex items-center justify-center">
              <AlertTriangle className="w-6 h-6 text-red-500" />
            </div>
          )}
        </div>

        {/* Progress Display */}
        <div className="mb-8">
          <div className="flex justify-between items-end mb-2">
            <span className="text-sm font-medium text-zinc-300">
              {job.message || "Initializing pipeline..."}
            </span>
            <span className="text-2xl font-light font-mono text-white">
              {progressPercent}%
            </span>
          </div>
          <div className="h-2 w-full bg-black rounded-full overflow-hidden border border-white/5">
            <div
              className={`h-full transition-all duration-300 ease-out ${
                isError
                  ? "bg-red-500"
                  : isCompleted
                    ? "bg-green-500"
                    : "bg-brand-500"
              }`}
              style={{ width: `${progressPercent}%` }}
            />
          </div>
        </div>

        {/* Console / Error output */}
        {isError && job.error && (
          <div className="p-4 bg-red-500/10 border border-red-500/20 rounded-xl mb-6">
            <h4 className="text-red-400 text-sm font-medium flex items-center gap-2 mb-1">
              <AlertTriangle className="w-4 h-4" /> Pipeline Error
            </h4>
            <p className="text-red-300/80 text-sm font-mono whitespace-pre-wrap">
              {job.error}
            </p>
          </div>
        )}

        {/* Actions */}
        <div className="flex justify-end gap-3 pt-4 border-t border-white/5">
          {isCompleted ? (
            <a
              href={`/dashboard/review?job=${job.id}`}
              className="px-6 py-2.5 bg-brand-600 hover:bg-brand-500 text-white rounded-xl font-medium transition-colors flex items-center gap-2"
            >
              Review Clips <ExternalLink className="w-4 h-4" />
            </a>
          ) : isError ? (
            <button
              onClick={onDismiss ?? onCancel}
              className="px-6 py-2.5 bg-zinc-800 hover:bg-zinc-700 text-white rounded-xl font-medium transition-colors"
            >
              Back to Upload
            </button>
          ) : (
            <>
              {/* Pause / Resume — only when processing/paused, not pending */}
              {job.status === "processing" && onPause && (
                <button
                  onClick={onPause}
                  className="px-4 py-2 hover:bg-zinc-800 rounded-lg text-sm text-zinc-300 border border-white/10 transition-colors"
                  title="Pause at next clip boundary (resume keeps your progress)"
                >
                  ⏸ Pause
                </button>
              )}
              {job.status === "paused" && onResume && (
                <button
                  onClick={onResume}
                  className="px-4 py-2 bg-brand-600/20 hover:bg-brand-600/30 border border-brand-500/30 rounded-lg text-sm text-brand-200 transition-colors"
                  title="Resume from the last completed clip"
                >
                  ▶ Resume
                </button>
              )}
              <button
                onClick={onCancel}
                className="px-4 py-2 hover:bg-red-950/40 hover:text-red-300 rounded-lg text-sm text-zinc-400 transition-colors"
              >
                ✕ Cancel
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
};
