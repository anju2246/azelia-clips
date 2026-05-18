import React, { useEffect, useState, useMemo } from "react";
import {
  Play,
  FileText,
  CheckCircle2,
  Clock,
  AlertCircle,
  FolderOpen,
  Search,
  Loader2,
  Pause,
  XCircle,
  RotateCcw,
  X,
} from "lucide-react";
import { ClipsApi, type EpisodeResponse } from "../../lib/api";
import toast from "react-hot-toast";

interface LibraryViewProps {
  onProcessEpisode: (episodeNum: number) => void;
  onResumeEpisode?: (episodeNum: number) => void;
  onResetEpisode?: (episodeNum: number) => void;
}

// 60s cache so navigating Dashboard ↔ Review doesn't re-scan the disk every time
const EPISODES_CACHE_KEY = "az_episodes_cache_v1";
const EPISODES_CACHE_TTL_MS = 60_000;

// Three-state button: extract (new), resume (paused/cancelled/failed),
// process_again (completed — needs confirm). Mirrors the WIP backup so
// users can recover interrupted jobs from the library without going
// through the cancel/restart loop.
type EpisodeAction = "extract" | "resume" | "process_again";

function getEpisodeAction(ep: EpisodeResponse): EpisodeAction {
  const s = ep.job_status;
  if (s === "paused" || s === "cancelled" || s === "failed") return "resume";
  if (ep.is_processed && (!s || s === "completed")) return "process_again";
  return "extract";
}

export const LibraryView: React.FC<LibraryViewProps> = ({
  onProcessEpisode,
  onResumeEpisode,
  onResetEpisode,
}) => {
  // Seed from sessionStorage if cache is fresh — avoids a fresh disk scan
  // on every dashboard return (disk wake-up on USB drives is the slow path).
  const [episodes, setEpisodes] = useState<EpisodeResponse[]>(() => {
    try {
      const raw = sessionStorage.getItem(EPISODES_CACHE_KEY);
      if (!raw) return [];
      const { at, data } = JSON.parse(raw);
      if (Date.now() - at < EPISODES_CACHE_TTL_MS) return data;
    } catch {
      /* ignore */
    }
    return [];
  });
  const [isLoading, setIsLoading] = useState(episodes.length === 0);
  const [searchQuery, setSearchQuery] = useState("");
  const [confirmReset, setConfirmReset] = useState<EpisodeResponse | null>(
    null,
  );

  useEffect(() => {
    loadEpisodes();
  }, []);

  // Poll while any episode has an active job so the badge / button reflect
  // live status instead of staying stuck at the cached value (paused, 96%,
  // etc). We poll the cheap /episodes endpoint — it's a directory scan plus
  // one SQL query against jobs.db, no model loads.
  useEffect(() => {
    const hasActive = episodes.some(
      (e) =>
        e.job_status === "processing" ||
        e.job_status === "pending" ||
        e.job_status === "resuming" ||
        e.job_status === "paused",
    );
    if (!hasActive) return;
    const id = setInterval(loadEpisodes, 4000);
    return () => clearInterval(id);
  }, [episodes]);

  const loadEpisodes = async () => {
    if (episodes.length === 0) setIsLoading(true);
    try {
      const data = await ClipsApi.getEpisodes();
      setEpisodes(data);
      try {
        sessionStorage.setItem(
          EPISODES_CACHE_KEY,
          JSON.stringify({ at: Date.now(), data }),
        );
      } catch {
        /* sessionStorage full or disabled — ignore */
      }
    } catch (error: any) {
      toast.error("Failed to load library: " + error.message);
    } finally {
      setIsLoading(false);
    }
  };

  const filteredEpisodes = useMemo(() => {
    if (!searchQuery.trim()) return episodes;

    const q = searchQuery.trim().toLowerCase();

    // Extract number from query like "EP97", "ep097", "97", "108"
    const numMatch = q.match(/(?:ep)?0*(\d+)/i);
    const searchNum = numMatch ? parseInt(numMatch[1]) : null;

    return episodes.filter((ep) => {
      // Match by episode number (fuzzy: "97" matches EP097, "EP97" matches EP097)
      if (searchNum !== null && ep.number === searchNum) return true;

      // Match by title (case-insensitive partial match)
      if (ep.title.toLowerCase().includes(q)) return true;

      // Match by ID
      if (ep.id.toLowerCase().includes(q)) return true;

      return false;
    });
  }, [episodes, searchQuery]);

  if (isLoading) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 border-brand-500"></div>
      </div>
    );
  }

  if (episodes.length === 0) {
    return (
      <div className="text-center py-20 border border-dashed border-zinc-800 rounded-2xl bg-zinc-900/50">
        <FolderOpen className="w-12 h-12 text-zinc-600 mx-auto mb-4" />
        <h3 className="text-lg font-medium text-zinc-300">No episodes found</h3>
        <p className="text-sm text-zinc-500 mt-2 max-w-md mx-auto">
          We couldn't detect any structured episode folders in your configured
          Podcast Directory. Use the Upload tab or check your Settings.
        </p>
      </div>
    );
  }

  return (
    <div className="w-full">
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 mb-6">
        <div>
          <h2 className="text-2xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-white to-zinc-400">
            Your Library
          </h2>
          <p className="text-zinc-500 text-sm mt-1">
            {episodes.length} episodes detected
          </p>
        </div>
        <div className="flex items-center gap-3 w-full sm:w-auto">
          <div className="relative flex-1 sm:w-64">
            <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
              <Search className="h-4 w-4 text-zinc-500" />
            </div>
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="block w-full pl-10 pr-3 py-2 border border-zinc-800 rounded-xl bg-zinc-900/50 text-zinc-300 placeholder-zinc-500 focus:outline-none focus:ring-1 focus:ring-brand-500 focus:border-brand-500 text-sm transition-all"
              placeholder="Search EP97, guest name..."
            />
          </div>
          <button
            onClick={loadEpisodes}
            className="px-4 py-2 hover:bg-zinc-800 rounded-lg text-sm text-zinc-400 transition-colors border border-zinc-800 whitespace-nowrap cursor-pointer"
          >
            Refresh
          </button>
        </div>
      </div>

      {filteredEpisodes.length === 0 && searchQuery ? (
        <div className="text-center py-12 border border-dashed border-zinc-800 rounded-2xl bg-zinc-900/50">
          <Search className="w-8 h-8 text-zinc-600 mx-auto mb-3" />
          <p className="text-zinc-400">
            No episodes match "<span className="text-white">{searchQuery}</span>
            "
          </p>
          <p className="text-zinc-500 text-sm mt-1">
            Try a different episode number or title keyword
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
          {filteredEpisodes.map((ep) => (
            <div
              key={ep.id}
              className="group glass-card rounded-2xl p-5 border border-white/5 bg-zinc-900/40 hover:bg-zinc-900/80 transition-all duration-300 hover:-translate-y-1 hover:border-brand-500/30 flex flex-col"
            >
              <div className="flex justify-between items-start mb-4">
                <div className="bg-brand-500/10 text-brand-400 text-xs font-bold px-2 py-1 rounded-md">
                  EP {ep.number.toString().padStart(3, "0")}
                </div>
                {(() => {
                  const s = ep.job_status;
                  if (
                    s === "processing" ||
                    s === "pending" ||
                    s === "resuming"
                  ) {
                    return (
                      <div className="flex items-center gap-1 text-brand-400 text-xs">
                        <Loader2 className="w-3 h-3 animate-spin" />
                        {s === "resuming" ? "Resuming" : "Processing"}
                        {ep.job_progress != null && ` ${ep.job_progress}%`}
                      </div>
                    );
                  }
                  if (s === "paused") {
                    return (
                      <div className="flex items-center gap-1 text-yellow-400 text-xs">
                        <Pause className="w-3 h-3" /> Paused
                        {ep.job_progress != null && ` ${ep.job_progress}%`}
                      </div>
                    );
                  }
                  if (s === "failed") {
                    return (
                      <div className="flex items-center gap-1 text-red-400 text-xs">
                        <XCircle className="w-3 h-3" /> Failed
                      </div>
                    );
                  }
                  if (ep.is_processed) {
                    return (
                      <div className="flex items-center gap-1 text-green-400 text-xs">
                        <CheckCircle2 className="w-3 h-3" /> Done
                      </div>
                    );
                  }
                  return (
                    <div className="flex items-center gap-1 text-zinc-500 text-xs">
                      <Clock className="w-3 h-3" /> Pending
                    </div>
                  );
                })()}
              </div>

              <h3
                className="font-semibold text-lg text-zinc-200 mb-2 line-clamp-2"
                title={ep.title}
              >
                {ep.title}
              </h3>

              <div className="flex gap-3 mb-6">
                <div
                  className={`flex items-center gap-1.5 text-xs ${ep.has_video ? "text-zinc-300" : "text-red-400/80"}`}
                >
                  {ep.has_video ? (
                    <Play className="w-3.5 h-3.5 text-zinc-500" />
                  ) : (
                    <AlertCircle className="w-3.5 h-3.5" />
                  )}
                  Video
                </div>
                <div
                  className={`flex items-center gap-1.5 text-xs ${ep.has_transcript ? "text-zinc-300" : "text-orange-400/80"}`}
                >
                  {ep.has_transcript ? (
                    <FileText className="w-3.5 h-3.5 text-zinc-500" />
                  ) : (
                    <AlertCircle className="w-3.5 h-3.5" />
                  )}
                  Transcript
                </div>
              </div>

              <div className="mt-auto">
                {(() => {
                  const s = ep.job_status;
                  const isLive =
                    s === "processing" ||
                    s === "pending" ||
                    s === "resuming";
                  if (isLive) {
                    return (
                      <button
                        disabled
                        className="w-full py-2.5 rounded-xl text-sm font-medium bg-zinc-800 text-zinc-500 cursor-not-allowed flex items-center justify-center gap-2"
                      >
                        <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        Processing…
                      </button>
                    );
                  }
                  const action = getEpisodeAction(ep);
                  if (action === "extract") {
                    return (
                      <button
                        onClick={() => onProcessEpisode(ep.number)}
                        disabled={!ep.has_video}
                        className={`w-full py-2.5 rounded-xl text-sm font-medium transition-colors cursor-pointer ${
                          !ep.has_video
                            ? "bg-zinc-800 text-zinc-500 cursor-not-allowed"
                            : "bg-brand-600 hover:bg-brand-500 text-white"
                        }`}
                      >
                        Extract Clips
                      </button>
                    );
                  }
                  if (action === "resume") {
                    return (
                      <button
                        onClick={() =>
                          onResumeEpisode
                            ? onResumeEpisode(ep.number)
                            : onProcessEpisode(ep.number)
                        }
                        disabled={!ep.has_video}
                        className="w-full py-2.5 rounded-xl text-sm font-medium transition-colors cursor-pointer bg-amber-600/20 hover:bg-amber-600/30 text-amber-300 border border-amber-500/30 flex items-center justify-center gap-2"
                      >
                        <Play className="w-3.5 h-3.5" />
                        Resume
                      </button>
                    );
                  }
                  // process_again — confirm before wiping existing clips
                  return (
                    <button
                      onClick={() =>
                        onResetEpisode ? setConfirmReset(ep) : onProcessEpisode(ep.number)
                      }
                      disabled={!ep.has_video}
                      className="w-full py-2.5 rounded-xl text-sm font-medium transition-colors cursor-pointer bg-white/5 hover:bg-white/10 text-white border border-white/10 flex items-center justify-center gap-2"
                    >
                      <RotateCcw className="w-3.5 h-3.5" />
                      Process Again
                    </button>
                  );
                })()}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Confirm dialog for Process Again — wipes existing curation + clips */}
      {confirmReset && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-6 max-w-md w-full">
            <div className="flex justify-between items-start mb-4">
              <div>
                <h3 className="text-lg font-semibold text-white">
                  Re-process {confirmReset.id}?
                </h3>
                <p className="text-zinc-400 text-sm mt-1">
                  This will discard the existing curation and re-render
                  every clip from scratch. Approved clips already on disk
                  stay where they are.
                </p>
              </div>
              <button
                onClick={() => setConfirmReset(null)}
                className="text-zinc-500 hover:text-white transition-colors cursor-pointer"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="flex gap-3 mt-6">
              <button
                onClick={() => setConfirmReset(null)}
                className="flex-1 py-2.5 rounded-xl text-sm font-medium bg-zinc-800 hover:bg-zinc-700 text-zinc-300 transition-colors cursor-pointer"
              >
                Cancel
              </button>
              <button
                onClick={() => {
                  if (onResetEpisode) onResetEpisode(confirmReset.number);
                  setConfirmReset(null);
                }}
                className="flex-1 py-2.5 rounded-xl text-sm font-medium bg-red-600 hover:bg-red-500 text-white transition-colors cursor-pointer flex items-center justify-center gap-2"
              >
                <RotateCcw className="w-3.5 h-3.5" />
                Re-process
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
