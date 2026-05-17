import React from 'react';
import type { YouTubeInsights } from '../../../lib/youtubeApi';

const formatNumber = (n: number) => {
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
    if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
    return n.toString();
};

const StatCard: React.FC<{ label: string; value: string }> = ({ label, value }) => (
    <div className="bg-zinc-900/40 border border-white/5 rounded-xl p-4">
        <p className="text-xs text-zinc-500 mb-1">{label}</p>
        <p className="text-2xl font-bold text-white">{value}</p>
    </div>
);

export const YouTubeInsightsView: React.FC<{ insights: YouTubeInsights }> = ({ insights }) => {
    return (
        <div className="space-y-6">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <StatCard label="Total Videos" value={insights.total_shorts.toString()} />
                <StatCard label="Total Views" value={formatNumber(insights.total_views)} />
                <StatCard label="Avg. Views" value={formatNumber(insights.avg_views)} />
                <StatCard label="Total Likes" value={formatNumber(insights.total_likes)} />
            </div>

            {insights.best_performing.length > 0 && (
                <div className="bg-zinc-900/40 border border-white/5 rounded-2xl p-6">
                    <h4 className="text-sm font-medium text-zinc-400 uppercase tracking-widest mb-4">
                        🏆 Top Performing Videos
                    </h4>
                    <div className="space-y-3">
                        {insights.best_performing.map((vid, i) => (
                            <div
                                key={i}
                                className="flex items-center justify-between gap-4 py-2 border-b border-white/5 last:border-0"
                            >
                                <div className="flex items-center gap-3 min-w-0">
                                    <span className="text-zinc-600 text-sm font-mono w-5">
                                        #{i + 1}
                                    </span>
                                    <a
                                        href={vid.url}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        className="text-zinc-200 text-sm truncate hover:text-white transition-colors"
                                    >
                                        {vid.title}
                                    </a>
                                </div>
                                <div className="flex items-center gap-2 shrink-0">
                                    <span className="text-sm font-medium text-white">
                                        {formatNumber(vid.views)}
                                    </span>
                                    <span className="text-xs text-zinc-500">views</span>
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {insights.duration_breakdown.length > 0 && (
                <div className="bg-zinc-900/40 border border-white/5 rounded-2xl p-6">
                    <h4 className="text-sm font-medium text-zinc-400 uppercase tracking-widest mb-4">
                        ⏱️ Performance by Duration
                    </h4>
                    <div className="space-y-4">
                        {insights.duration_breakdown.map((bucket) => {
                            const maxViews = Math.max(
                                ...insights.duration_breakdown.map((b) => b.avg_views)
                            );
                            const pct = maxViews > 0 ? (bucket.avg_views / maxViews) * 100 : 0;
                            return (
                                <div key={bucket.range}>
                                    <div className="flex justify-between text-sm mb-1.5">
                                        <span className="text-zinc-300">{bucket.range}</span>
                                        <span className="text-zinc-500">
                                            {bucket.count} videos · avg{' '}
                                            {formatNumber(bucket.avg_views)} views
                                        </span>
                                    </div>
                                    <div className="h-2 w-full bg-black rounded-full overflow-hidden">
                                        <div
                                            className="h-full rounded-full bg-red-500/70"
                                            style={{ width: `${pct}%` }}
                                        />
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                </div>
            )}
        </div>
    );
};
