import React, { useRef, useState } from "react";
import { Play, Check, X, Sparkles, FolderOpen } from "lucide-react";
import type { Clip } from "../../lib/api";
import { ClipsApi } from "../../lib/api";
import toast from "react-hot-toast";

interface ClipReviewCardProps {
  clip: Clip;
  jobId: string;
  onApprove: (id: number) => void;
  onReject: (id: number) => void;
  onClick?: () => void;
}

export const ClipReviewCard: React.FC<ClipReviewCardProps> = ({
  clip,
  jobId,
  onApprove,
  onReject,
  onClick,
}) => {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [showConfirm, setShowConfirm] = useState(false);

  const API_BASE = (import.meta.env?.PUBLIC_API_URL as string) || "/api";
  const videoUrl = `${API_BASE}/clips/${jobId}/${clip.filename}`;
  const isReview = clip.status === "review";

  const handleOpenInFinder = async (e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await ClipsApi.openClipLocation(jobId, clip.filename);
      toast.success("Abierto en Finder");
    } catch {
      toast.error("No se pudo abrir");
    }
  };

  return (
    <div
      className={`glass-card rounded-2xl overflow-hidden border ${isReview ? "border-yellow-500/30" : "border-white/5"} bg-zinc-900/40 hover:bg-zinc-900/60 transition-all duration-300 flex flex-col`}
    >
      {/* Video */}
      <div
        className="relative aspect-[9/16] bg-black group cursor-pointer"
        onMouseEnter={() => {
          if (videoRef.current) videoRef.current.play().catch(() => {});
        }}
        onMouseLeave={() => {
          if (videoRef.current) {
            videoRef.current.pause();
            videoRef.current.currentTime = 0;
          }
        }}
        onClick={onClick}
      >
        <video
          ref={videoRef}
          src={videoUrl}
          className="w-full h-full object-cover opacity-90 group-hover:opacity-100 transition-opacity"
          loop
          playsInline
          muted={true}
        />

        {/* Hover Play Overlay */}
        <div className="absolute inset-0 flex items-center justify-center bg-black/30 transition-opacity duration-300 opacity-0 group-hover:opacity-100">
          <div className="w-14 h-14 rounded-full bg-brand-600/90 backdrop-blur-md flex items-center justify-center text-white shadow-lg shadow-brand-900/50 scale-90 group-hover:scale-100 transition-transform">
            <Play className="w-6 h-6 ml-1" />
          </div>
        </div>

        {/* Score + Duration Badge (top-left) */}
        <div className="absolute top-3 left-3 flex flex-col gap-1.5 pointer-events-none">
          <div className="bg-black/60 backdrop-blur-md text-white text-xs font-bold px-2 py-1.5 rounded-lg flex items-center gap-1.5 border border-white/10">
            <Sparkles className="w-3.5 h-3.5 text-brand-400" />
            Score:{" "}
            <span className="text-brand-400">{clip.virality_score}/100</span>
          </div>
          <div className="bg-black/60 backdrop-blur-md text-zinc-300 text-[10px] font-medium px-2 py-1 rounded-md border border-white/10 w-max">
            {clip.duration}s
          </div>
        </div>
      </div>

      {/* Metadata — Title only + review badge below */}
      <div className="p-4 flex flex-col flex-1">
        <h3
          className="font-semibold text-sm text-zinc-200 mb-1.5 line-clamp-2"
          title={clip.title}
        >
          {clip.title}
        </h3>

        {/* Review badge below title */}
        {isReview && (
          <div className="bg-yellow-500/15 text-yellow-400 text-[11px] font-bold px-2.5 py-1.5 rounded-md border border-yellow-500/30 mb-3 flex items-center gap-1.5 w-max">
            ⚠ Requires Review
          </div>
        )}

        {/* Spacer */}
        <div className="flex-1" />

        {/* Controls */}
        <div className="flex gap-2 mt-3">
          {clip.status === "approved" ? (
            <div className="flex-1 flex items-center justify-center gap-2 py-2 bg-green-500/10 text-green-400 rounded-xl text-sm font-medium border border-green-500/20">
              <Check className="w-4 h-4" /> Aprobado
            </div>
          ) : (
            <>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onApprove(clip.id);
                }}
                className="flex-1 py-2 bg-brand-600 hover:bg-brand-500 text-white rounded-xl text-sm font-medium transition-colors flex justify-center items-center gap-1.5"
              >
                <Check className="w-4 h-4" /> Aprobar
              </button>
              {showConfirm ? (
                <div className="flex-1 flex gap-1">
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      setShowConfirm(false);
                    }}
                    className="flex-1 py-2 bg-zinc-700 hover:bg-zinc-600 text-zinc-300 rounded-xl text-xs font-semibold"
                  >
                    Cancelar
                  </button>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      setShowConfirm(false);
                      onReject(clip.id);
                    }}
                    className="flex-1 py-2 bg-red-500 hover:bg-red-400 text-white rounded-xl text-xs font-bold"
                  >
                    Seguro
                  </button>
                </div>
              ) : (
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    setShowConfirm(true);
                  }}
                  className="flex-1 py-2 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded-xl text-sm font-medium transition-colors flex justify-center items-center gap-1.5 border border-zinc-700"
                >
                  <X className="w-4 h-4" /> Rechazar
                </button>
              )}
            </>
          )}
          <button
            onClick={handleOpenInFinder}
            className="p-2 bg-white/5 hover:bg-white/10 text-zinc-300 rounded-xl transition-colors border border-white/5 flex items-center justify-center"
            title="Abrir en Finder"
          >
            <FolderOpen className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
};
