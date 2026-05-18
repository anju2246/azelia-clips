import React, { useEffect, useState, useRef } from "react";
import { Loader2, Trash2, RotateCcw, Play } from "lucide-react";
import { ClipsApi } from "../../lib/api";
import toast from "react-hot-toast";

interface RejectedClip {
  filename: string;
  rejected_at: number;
  days_remaining: number;
  duration: number;
  download_url: string;
}

interface RejectedClipsListProps {
  jobId: string;
  onRestored: () => void;
  onClipClick: (index: number, clips: any[]) => void;
  version?: number;
}

export const RejectedClipsList: React.FC<RejectedClipsListProps> = ({
  jobId,
  onRestored,
  onClipClick,
  version = 0,
}) => {
  const [clips, setClips] = useState<RejectedClip[]>([]);
  const [loading, setLoading] = useState(true);

  const loadClips = async () => {
    try {
      setLoading(true);
      const data = await ClipsApi.getRejectedClips(jobId);
      setClips(data || []);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadClips();
  }, [jobId, version]);

  const handleRestore = async (filename: string) => {
    try {
      await ClipsApi.restoreClip(jobId, filename);
      toast.success("Clip restored to review");
      await loadClips();
      onRestored();
    } catch (e) {
      toast.error("Could not restore the clip");
    }
  };

  if (loading) {
    return (
      <div className="flex justify-center p-8">
        <Loader2 className="w-6 h-6 animate-spin text-zinc-500" />
      </div>
    );
  }

  if (clips.length === 0) {
    return (
      <div className="text-center py-20 px-4">
        <div className="w-16 h-16 bg-red-500/10 rounded-full flex items-center justify-center mx-auto mb-4">
          <Trash2 className="w-8 h-8 text-red-500/50" />
        </div>
        <h3 className="text-xl font-bold text-white mb-2">
          The trash is empty
        </h3>
        <p className="text-zinc-500 max-w-sm mx-auto">
          Clips you reject will show up here. They're automatically removed from
          the server after 30 days.
        </p>
      </div>
    );
  }

  return (
    <div className="animate-in fade-in duration-300">
      <div className="flex items-center gap-3 mb-2">
        <div className="p-2 rounded-lg bg-red-500/10 text-red-500">
          <Trash2 className="w-5 h-5" />
        </div>
        <div>
          <h3 className="text-xl font-bold text-white">Trash</h3>
          <p className="text-sm text-zinc-500">
            Automatically deleted after 30 days.
          </p>
        </div>
        <div className="ml-auto bg-red-500/20 text-red-400 text-xs font-medium px-3 py-1 rounded-full">
          {clips.length} {clips.length === 1 ? "clip" : "clips"}
        </div>
      </div>

      <div className="mt-8 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
        {clips.map((clip) => (
          <RejectedClipCard
            key={clip.filename}
            clip={clip}
            onRestore={() => handleRestore(clip.filename)}
            onClick={() => onClipClick(clips.indexOf(clip), clips)}
          />
        ))}
      </div>
    </div>
  );
};

const RejectedClipCard: React.FC<{
  clip: RejectedClip;
  onRestore: () => void;
  onClick: () => void;
}> = ({ clip, onRestore, onClick }) => {
  const videoRef = useRef<HTMLVideoElement>(null);
  const API_BASE = (import.meta.env?.PUBLIC_API_URL as string) || "/api";
  const videoUrl = `${API_BASE}/clips/${clip.download_url.split("/clips/")[1]}`;
  const previewTime = 0.5;

  return (
    <div className="glass-card rounded-xl overflow-hidden border border-red-500/20 bg-zinc-900/40 flex flex-col opacity-80 hover:opacity-100 transition-opacity">
      <div
        className="relative aspect-[9/16] bg-black group cursor-pointer"
        onMouseEnter={() => {
          if (videoRef.current) videoRef.current.play().catch(() => {});
        }}
        onMouseLeave={() => {
          if (videoRef.current) {
            videoRef.current.pause();
            videoRef.current.currentTime = previewTime;
          }
        }}
        onClick={onClick}
      >
        <video
          ref={videoRef}
          src={`${videoUrl}#t=${previewTime}`}
          preload="metadata"
          className="w-full h-full object-cover opacity-70 group-hover:opacity-90 transition-opacity"
          loop
          playsInline
          muted={true}
        />

        <div className="absolute top-2 left-2 flex flex-col gap-1 pointer-events-none">
          <div className="bg-black/80 backdrop-blur-md text-red-400 text-[10px] font-bold px-2 py-1 rounded border border-red-500/30">
            Deletes in {clip.days_remaining} days
          </div>
        </div>
        <div className="absolute top-2 right-2 pointer-events-none">
          <div className="bg-black/60 backdrop-blur-md text-zinc-300 text-[10px] font-medium px-2 py-1 rounded border border-white/10">
            {clip.duration}s
          </div>
        </div>
      </div>
      <div className="p-3 flex items-center justify-between bg-zinc-900 gap-3">
        <span
          className="text-xs text-zinc-400 truncate flex-1"
          title={clip.filename}
        >
          {clip.filename}
        </span>
        <button
          onClick={onRestore}
          className="p-1.5 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 hover:text-white rounded-lg transition-colors border border-zinc-700 flex items-center gap-1.5 shrink-0"
          title="Restore to review"
        >
          <RotateCcw className="w-3.5 h-3.5" />
          <span className="text-[10px] font-medium pr-1">Restore</span>
        </button>
      </div>
    </div>
  );
};
