import React from 'react';
import { Play, Download, Share2, MoreVertical } from 'lucide-react';
import { clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

function cn(...inputs: (string | undefined | null | false)[]) {
    return twMerge(clsx(inputs));
}

interface ClipProps {
    id: string;
    title: string;
    duration: string;
    score: number;
    thumbnailUrl?: string;
    createdAt: string;
}

export default function ClipCard({ clip }: { clip: ClipProps }) {
    return (
        <div className="group relative bg-zinc-900 border border-zinc-800 rounded-xl overflow-hidden hover:border-zinc-700 transition-all hover:shadow-lg hover:shadow-black/50">
            {/* Thumbnail Area */}
            <div className="aspect-[9/16] relative bg-zinc-950">
                {clip.thumbnailUrl ? (
                    <img
                        src={clip.thumbnailUrl}
                        alt={clip.title}
                        className="w-full h-full object-cover opacity-80 group-hover:opacity-100 transition-opacity"
                    />
                ) : (
                    <div className="w-full h-full flex items-center justify-center bg-zinc-800/50">
                        <Play className="text-zinc-600 w-12 h-12" />
                    </div>
                )}

                {/* Score Badge */}
                <div className={cn(
                    "absolute top-3 right-3 px-2 py-1 rounded-md text-xs font-bold shadow-sm backdrop-blur-md border border-white/10",
                    clip.score >= 90 ? "bg-emerald-500/90 text-white" :
                        clip.score >= 80 ? "bg-emerald-500/20 text-emerald-400 border-emerald-500/20" :
                            "bg-zinc-800/90 text-zinc-400"
                )}>
                    {clip.score}
                </div>

                {/* Duration Badge */}
                <div className="absolute bottom-3 right-3 px-2 py-1 rounded-md bg-black/70 text-zinc-200 text-xs font-medium backdrop-blur-md">
                    {clip.duration}
                </div>
            </div>

            {/* Content Area */}
            <div className="p-4 space-y-3">
                <div>
                    <h3 className="font-semibold text-zinc-100 line-clamp-2 leading-tight group-hover:text-brand-400 transition-colors">
                        {clip.title}
                    </h3>
                    <p className="text-xs text-zinc-500 mt-1">{clip.createdAt}</p>
                </div>

                <div className="flex items-center gap-2 pt-2 border-t border-zinc-800/50">
                    <button className="flex-1 flex items-center justify-center gap-2 py-2 px-3 bg-zinc-800 hover:bg-zinc-700 rounded-lg text-sm font-medium text-zinc-200 transition-colors">
                        <Download size={16} />
                        Download
                    </button>
                    <button className="p-2 hover:bg-zinc-800 rounded-lg text-zinc-400 hover:text-zinc-200 transition-colors">
                        <Share2 size={16} />
                    </button>
                </div>
            </div>
        </div>
    );
}
