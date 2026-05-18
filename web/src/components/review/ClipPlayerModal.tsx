import React, { useRef, useState, useEffect } from "react";
import {
  Play,
  Pause,
  Volume2,
  VolumeX,
  Maximize2,
  SkipForward,
  SkipBack,
  X,
  FolderOpen,
  Check,
  Sparkles,
  RotateCcw,
} from "lucide-react";
import type { Clip } from "../../lib/api";
import { ClipsApi } from "../../lib/api";
import toast from "react-hot-toast";

interface ClipPlayerModalProps {
  clips: Clip[];
  initialClipIndex: number;
  jobId: string;
  onClose: () => void;
  onApprove: (id: number) => void;
  onReject: (id: number) => void;
}

export const ClipPlayerModal: React.FC<ClipPlayerModalProps> = ({
  clips,
  initialClipIndex,
  jobId,
  onClose,
  onApprove,
  onReject,
}) => {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [currentIndex, setCurrentIndex] = useState(initialClipIndex);
  const [isPlaying, setIsPlaying] = useState(true);
  const [progress, setProgress] = useState(0);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [volume, setVolume] = useState(1);
  const [isMuted, setIsMuted] = useState(false);
  const [showControls, setShowControls] = useState(true);
  const [showRejectConfirm, setShowRejectConfirm] = useState(false);
  const controlsTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Auto-adjust index if clips array shrinks (e.g. when rejecting)
  useEffect(() => {
    if (clips.length === 0) {
      onClose();
    } else if (currentIndex >= clips.length) {
      setCurrentIndex(clips.length - 1);
    }
  }, [clips.length, currentIndex, onClose]);

  const currentClip = clips[currentIndex];

  const API_BASE = (import.meta.env?.PUBLIC_API_URL as string) || "/api";
  // If the clip has a status but it's not approved/review, or if it lacks an ID (rejected clips from the list don't have numeric IDs in the same way)
  const isRejected =
    !currentClip?.status ||
    (currentClip.status !== "approved" && currentClip.status !== "review");
  const videoUrl = `${API_BASE}/clips/${jobId}/${currentClip?.filename}`;
  const isReview = currentClip?.status === "review";

  useEffect(() => {
    setIsPlaying(true);
    setProgress(0);
    setCurrentTime(0);
    if (videoRef.current) {
      videoRef.current.load();
      videoRef.current.play().catch(() => setIsPlaying(false));
    }
  }, [currentIndex]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === " ") {
        e.preventDefault();
        togglePlay();
      }
      if (e.key === "ArrowRight") seek(currentTime + 5);
      if (e.key === "ArrowLeft") seek(currentTime - 5);
      if (e.key === "ArrowDown") handleNext();
      if (e.key === "ArrowUp") handlePrev();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [currentTime, currentIndex]);

  useEffect(() => {
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = "";
    };
  }, []);

  const handleMouseMove = () => {
    setShowControls(true);
    if (controlsTimeoutRef.current) clearTimeout(controlsTimeoutRef.current);
    controlsTimeoutRef.current = setTimeout(() => setShowControls(false), 3000);
  };

  const togglePlay = () => {
    if (!videoRef.current) return;
    if (isPlaying) videoRef.current.pause();
    else videoRef.current.play();
    setIsPlaying(!isPlaying);
  };

  const handleTimeUpdate = () => {
    if (!videoRef.current) return;
    const cur = videoRef.current.currentTime;
    const dur = videoRef.current.duration;
    setCurrentTime(cur);
    setDuration(dur);
    setProgress((cur / dur) * 100);
  };

  const handleProgressScrub = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!videoRef.current) return;
    const rect = e.currentTarget.getBoundingClientRect();
    seek(((e.clientX - rect.left) / rect.width) * videoRef.current.duration);
  };

  const seek = (time: number) => {
    if (!videoRef.current || isNaN(videoRef.current.duration)) return;
    const clamped = Math.max(0, Math.min(time, videoRef.current.duration));
    videoRef.current.currentTime = clamped;
    setCurrentTime(clamped);
  };

  const handleVolumeChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const vol = parseFloat(e.target.value);
    setVolume(vol);
    if (videoRef.current) {
      videoRef.current.volume = vol;
      setIsMuted(vol === 0);
    }
  };

  const toggleMute = () => {
    if (!videoRef.current) return;
    videoRef.current.muted = !isMuted;
    setIsMuted(!isMuted);
    if (isMuted && volume === 0) {
      setVolume(1);
      videoRef.current.volume = 1;
    }
  };

  const toggleFullscreen = () => {
    if (!videoRef.current) return;
    if (document.fullscreenElement) document.exitFullscreen();
    else videoRef.current.requestFullscreen();
  };

  const fmt = (s: number) =>
    isNaN(s)
      ? "00:00"
      : `${Math.floor(s / 60)
          .toString()
          .padStart(2, "0")}:${Math.floor(s % 60)
          .toString()
          .padStart(2, "0")}`;
  const handleNext = () => {
    if (currentIndex < clips.length - 1) setCurrentIndex(currentIndex + 1);
  };
  const handlePrev = () => {
    if (currentIndex > 0) setCurrentIndex(currentIndex - 1);
  };

  const handleOpenInFinder = async () => {
    try {
      await ClipsApi.openClipLocation(jobId, currentClip.filename);
      toast.success("Abierto en Finder");
    } catch {
      toast.error("No se pudo abrir");
    }
  };

  if (!currentClip) return null;

  return (
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/95 backdrop-blur-xl"
      onMouseMove={handleMouseMove}
    >
      {/* Close Button - top right corner */}
      <button
        onClick={onClose}
        className="absolute top-5 right-5 z-30 p-2.5 bg-white/10 hover:bg-white/20 rounded-full text-white transition-colors backdrop-blur-md border border-white/10"
      >
        <X className="w-5 h-5" />
      </button>

      {/* Main Layout: Video (center) + Info Panel (right) */}
      <div className="flex items-center justify-center gap-8 h-full max-h-[92vh] px-20">
        {/* Nav: Previous */}
        <div
          className={`shrink-0 transition-opacity duration-300 ${currentIndex > 0 ? "opacity-100" : "opacity-0 pointer-events-none"}`}
        >
          <button
            onClick={handlePrev}
            className="p-3.5 bg-white/5 hover:bg-brand-600 rounded-full text-white border border-white/10 transition-all hover:scale-110"
          >
            <SkipBack className="w-5 h-5" />
          </button>
        </div>

        {/* Video Player */}
        <div
          className="relative h-full max-h-[85vh] aspect-[9/16] bg-black shadow-2xl rounded-xl overflow-hidden shrink-0"
          onClick={togglePlay}
        >
          <video
            ref={videoRef}
            src={videoUrl}
            className="h-full w-full object-contain"
            onTimeUpdate={handleTimeUpdate}
            onEnded={() => setIsPlaying(false)}
            autoPlay
            playsInline
          />

          {/* Centered Play indicator */}
          <div
            className={`absolute inset-0 flex items-center justify-center pointer-events-none transition-opacity duration-300 ${!isPlaying ? "opacity-100" : "opacity-0"}`}
          >
            <div className="w-20 h-20 rounded-full bg-white/10 backdrop-blur-xl flex items-center justify-center text-white border border-white/20">
              <Play className="w-10 h-10 ml-2" />
            </div>
          </div>

          {/* Bottom Controls (on video) */}
          <div
            className={`absolute bottom-0 left-0 right-0 px-4 pb-4 pt-10 bg-gradient-to-t from-black via-black/60 to-transparent transition-opacity duration-300 ${showControls ? "opacity-100" : "opacity-0 pointer-events-none"}`}
            onClick={(e) => e.stopPropagation()}
          >
            {/* Progress */}
            <div className="mb-2">
              <div
                className="h-1.5 w-full bg-white/20 rounded-full cursor-pointer relative group overflow-hidden hover:h-2.5 transition-all"
                onClick={handleProgressScrub}
              >
                <div
                  className="absolute top-0 left-0 h-full bg-brand-500 rounded-full pointer-events-none"
                  style={{ width: `${progress}%` }}
                />
              </div>
              <div className="flex justify-between text-[10px] text-zinc-400 font-mono mt-1">
                <span>{fmt(currentTime)}</span>
                <span>{fmt(duration)}</span>
              </div>
            </div>
            {/* Playback controls */}
            <div className="flex items-center gap-3">
              <button
                onClick={togglePlay}
                className="text-white hover:text-brand-400 transition-colors"
              >
                {isPlaying ? (
                  <Pause className="w-5 h-5" />
                ) : (
                  <Play className="w-5 h-5" />
                )}
              </button>
              <div className="flex items-center gap-1.5 group/vol">
                <button
                  onClick={toggleMute}
                  className="text-white hover:text-brand-400 transition-colors"
                >
                  {isMuted || volume === 0 ? (
                    <VolumeX className="w-4 h-4" />
                  ) : (
                    <Volume2 className="w-4 h-4" />
                  )}
                </button>
                <input
                  type="range"
                  min="0"
                  max="1"
                  step="0.01"
                  value={isMuted ? 0 : volume}
                  onChange={handleVolumeChange}
                  className="w-0 opacity-0 group-hover/vol:w-16 group-hover/vol:opacity-100 transition-all duration-300 accent-brand-500 h-1 cursor-pointer"
                />
              </div>
              <button
                onClick={toggleFullscreen}
                className="text-zinc-300 hover:text-white transition-colors ml-auto"
              >
                <Maximize2 className="w-4 h-4" />
              </button>
            </div>
          </div>
        </div>

        {/* Nav: Next */}
        <div
          className={`shrink-0 transition-opacity duration-300 ${currentIndex < clips.length - 1 ? "opacity-100" : "opacity-0 pointer-events-none"}`}
        >
          <button
            onClick={handleNext}
            className="p-3.5 bg-white/5 hover:bg-brand-600 rounded-full text-white border border-white/10 transition-all hover:scale-110"
          >
            <SkipForward className="w-5 h-5" />
          </button>
        </div>

        {/* RIGHT SIDE PANEL — Metadata & Actions */}
        <div className="shrink-0 w-72 max-h-[85vh] flex flex-col text-white">
          {/* Clip Counter */}
          <div className="flex items-center gap-2 mb-4">
            <span className="bg-brand-500/20 text-brand-400 text-xs font-bold px-3 py-1 rounded-full border border-brand-500/30">
              Clip {currentIndex + 1} / {clips.length}
            </span>
          </div>

          {/* Score */}
          {currentClip.virality_score !== undefined && (
            <div className="flex items-center gap-2 mb-3">
              <Sparkles className="w-4 h-4 text-brand-400" />
              <span className="text-sm text-zinc-400">Score:</span>
              <span className="text-lg font-bold text-white">
                {currentClip.virality_score}
                <span className="text-zinc-500 text-sm font-normal">/100</span>
              </span>
            </div>
          )}

          {/* Review Badge */}
          {isReview && (
            <div className="bg-yellow-500/15 text-yellow-400 text-xs font-bold px-3 py-2 rounded-lg border border-yellow-500/30 mb-4 flex items-center gap-2">
              ⚠ Requires Manual Review
            </div>
          )}

          {/* Title */}
          <h2 className="text-lg font-bold leading-tight mb-2">
            {currentClip.title}
          </h2>

          {/* Summary */}
          <p className="text-sm text-zinc-400 leading-relaxed mb-6">
            {currentClip.summary}
          </p>

          {/* Duration info */}
          <div className="text-xs text-zinc-500 mb-6">
            Duration:{" "}
            <span className="text-zinc-300">{currentClip.duration}s</span>
          </div>

          {/* Divider */}
          <div className="border-t border-white/10 my-2" />

          {/* Actions */}
          <div className="flex flex-col gap-3 mt-4 relative">
            {showRejectConfirm ? (
              <div className="absolute inset-0 z-10 bg-zinc-900/95 backdrop-blur-md rounded-xl p-4 flex flex-col justify-center border border-yellow-500/30">
                <p className="text-sm font-semibold text-center mb-3">
                  Reject this clip?
                </p>
                <div className="flex gap-2">
                  <button
                    onClick={() => setShowRejectConfirm(false)}
                    className="flex-1 py-1.5 bg-white/10 hover:bg-white/20 rounded-lg text-xs font-medium transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={() => {
                      setShowRejectConfirm(false);
                      onReject(currentClip.id);
                    }}
                    className="flex-1 py-1.5 bg-red-500 hover:bg-red-400 text-white rounded-lg text-xs font-bold transition-colors"
                  >
                    Reject
                  </button>
                </div>
              </div>
            ) : null}

            {currentClip.status === "approved" ? (
              <div className="w-full py-2.5 bg-green-500/15 text-green-400 rounded-xl text-sm font-bold flex items-center justify-center gap-2 border border-green-500/25">
                <Check className="w-4 h-4" /> Aprobado
              </div>
            ) : isRejected ? (
              <button
                onClick={() => onApprove(currentClip.id)}
                className="w-full py-2.5 bg-zinc-800 hover:bg-zinc-700 text-white rounded-xl text-sm font-bold flex items-center justify-center gap-2 transition-colors border border-zinc-700"
              >
                <RotateCcw className="w-4 h-4" /> Restaurar Clip
              </button>
            ) : (
              <>
                <button
                  onClick={() => onApprove(currentClip.id)}
                  className="w-full py-2.5 bg-brand-600 hover:bg-brand-500 text-white rounded-xl text-sm font-bold flex items-center justify-center gap-2 transition-colors"
                >
                  <Check className="w-4 h-4" /> Aprobar
                </button>
                {!isRejected && (
                  <button
                    onClick={() => setShowRejectConfirm(true)}
                    className="w-full py-2.5 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded-xl text-sm font-bold flex items-center justify-center gap-2 border border-zinc-700 transition-colors"
                  >
                    <X className="w-4 h-4" /> Rechazar
                  </button>
                )}
              </>
            )}

            <button
              onClick={handleOpenInFinder}
              className="w-full py-2.5 bg-white/5 hover:bg-white/10 text-zinc-300 rounded-xl text-sm font-medium flex items-center justify-center gap-2 border border-white/10 transition-colors"
            >
              <FolderOpen className="w-4 h-4" /> Abrir en Finder
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
