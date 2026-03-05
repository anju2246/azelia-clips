import React, { useRef, useState } from 'react';
import { Play, Pause, Download, Check, X, Maximize2, Sparkles } from 'lucide-react';
import type { Clip } from '../../lib/api';
import toast from 'react-hot-toast';

interface ClipReviewCardProps {
    clip: Clip;
    jobId: string;
    onApprove: (id: number) => void;
    onReject: (id: number) => void;
}

export const ClipReviewCard: React.FC<ClipReviewCardProps> = ({ clip, jobId, onApprove, onReject }) => {
    const videoRef = useRef<HTMLVideoElement>(null);
    const [isPlaying, setIsPlaying] = useState(false);
    const [isHovering, setIsHovering] = useState(false);

    const API_BASE = (import.meta.env?.PUBLIC_API_URL as string) || '/api';
    const videoUrl = `${API_BASE}/clips/${jobId}/${clip.filename}`;

    const togglePlay = (e: React.MouseEvent) => {
        e.stopPropagation();
        if (videoRef.current) {
            if (isPlaying) {
                videoRef.current.pause();
            } else {
                videoRef.current.play();
            }
            setIsPlaying(!isPlaying);
        }
    };

    const handleDownload = (e: React.MouseEvent) => {
        e.stopPropagation();
        // In a real app, this would trigger a download instead of open in new tab if configured
        window.open(clip.download_url || videoUrl, '_blank');
        toast.success('Download started');
    };

    return (
        <div className="glass-card rounded-2xl overflow-hidden border border-white/5 bg-zinc-900/40 hover:bg-zinc-900/60 transition-all duration-300 flex flex-col">
            {/* Video Container */}
            <div
                className="relative aspect-[9/16] bg-black group cursor-pointer"
                onMouseEnter={() => setIsHovering(true)}
                onMouseLeave={() => setIsHovering(false)}
                onClick={togglePlay}
            >
                <video
                    ref={videoRef}
                    src={videoUrl}
                    className="w-full h-full object-cover"
                    loop
                    playsInline
                    muted={false}
                    onEnded={() => setIsPlaying(false)}
                    onPause={() => setIsPlaying(false)}
                    onPlay={() => setIsPlaying(true)}
                />

                {/* Play/Pause Overlay */}
                <div className={`absolute inset-0 flex items-center justify-center bg-black/20 transition-opacity duration-300 ${isHovering && !isPlaying ? 'opacity-100' : 'opacity-0'}`}>
                    <div className="w-14 h-14 rounded-full bg-black/50 backdrop-blur-md flex items-center justify-center text-white">
                        {isPlaying ? <Pause className="w-6 h-6" /> : <Play className="w-6 h-6 ml-1" />}
                    </div>
                </div>

                {/* Top Badges */}
                <div className="absolute top-3 left-3 right-3 flex justify-between items-start pointer-events-none">
                    <div className="flex flex-col gap-1.5">
                        <div className="bg-black/60 backdrop-blur-md text-white text-xs font-bold px-2 py-1.5 rounded-lg flex items-center gap-1.5 border border-white/10 shadow-lg">
                            <Sparkles className="w-3.5 h-3.5 text-brand-400" />
                            Score: <span className="text-brand-400">{clip.virality_score}/100</span>
                        </div>
                        <div className="bg-black/60 backdrop-blur-md text-zinc-300 text-[10px] font-medium px-2 py-1 rounded-md border border-white/10 inline-block w-max">
                            {clip.duration.toFixed(1)}s
                        </div>
                    </div>

                    <button
                        className={`pointer-events-auto p-2 bg-black/60 backdrop-blur-md rounded-lg text-white hover:bg-brand-500 hover:text-white transition-colors border border-white/10 ${isHovering ? 'opacity-100' : 'opacity-0'}`}
                        onClick={(e) => {
                            e.stopPropagation();
                            if (videoRef.current) {
                                if (videoRef.current.requestFullscreen) {
                                    videoRef.current.requestFullscreen();
                                }
                            }
                        }}
                    >
                        <Maximize2 className="w-4 h-4" />
                    </button>
                </div>
            </div>

            {/* Metadata & Actions */}
            <div className="p-4 flex flex-col flex-1">
                <h3 className="font-semibold text-sm text-zinc-200 mb-1 line-clamp-2" title={clip.title}>
                    {clip.title}
                </h3>
                <p className="text-xs text-zinc-500 line-clamp-2 mb-4 flex-1">
                    {clip.summary}
                </p>

                {/* Controls */}
                <div className="flex gap-2 mt-auto">
                    {clip.status === 'approved' ? (
                        <div className="flex-1 flex items-center justify-center gap-2 py-2 bg-green-500/10 text-green-400 rounded-xl text-sm font-medium border border-green-500/20">
                            <Check className="w-4 h-4" /> Approved
                        </div>
                    ) : (
                        <>
                            <button
                                onClick={() => onApprove(clip.id)}
                                className="flex-1 py-2 bg-brand-600 hover:bg-brand-500 text-white rounded-xl text-sm font-medium transition-colors flex justify-center items-center gap-1.5"
                            >
                                <Check className="w-4 h-4" /> Approve
                            </button>
                            <button
                                onClick={() => onReject(clip.id)}
                                className="flex-1 py-2 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded-xl text-sm font-medium transition-colors flex justify-center items-center gap-1.5 border border-zinc-700"
                            >
                                <X className="w-4 h-4" /> Reject
                            </button>
                        </>
                    )}
                    <button
                        onClick={handleDownload}
                        className="p-2 bg-white/5 hover:bg-white/10 text-zinc-300 rounded-xl transition-colors border border-white/5 flex items-center justify-center"
                        title="Download Clip"
                    >
                        <Download className="w-4 h-4" />
                    </button>
                </div>
            </div>
        </div>
    );
};
