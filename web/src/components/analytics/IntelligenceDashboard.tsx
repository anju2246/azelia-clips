import React, { useEffect, useState } from 'react';
import { TrendingUp, Users, Activity, Loader2, BarChart3, Clock, Mic2, Zap, Film, ArrowUpRight } from 'lucide-react';
import { supabase } from '../../lib/supabase';
import toast from 'react-hot-toast';

interface PipelineStats {
    totalClips: number;
    totalEpisodes: number;
    avgViralityScore: number;
    topHookTypes: Record<string, number>;
    topCategories: Record<string, number>;
    avgDuration: number;
}

export const IntelligenceDashboard: React.FC = () => {
    const [stats, setStats] = useState<PipelineStats | null>(null);
    const [isLoading, setIsLoading] = useState(true);
    const [hasData, setHasData] = useState(false);

    useEffect(() => {
        loadStats();
    }, []);

    const loadStats = async () => {
        try {
            // Try to fetch real stats from the API
            const API_BASE = (import.meta.env?.PUBLIC_API_URL as string) || '/api';
            const { data: session } = await supabase.auth.getSession();
            const headers: HeadersInit = { 'Accept': 'application/json' };
            if (session?.session?.access_token) {
                headers['Authorization'] = `Bearer ${session.session.access_token}`;
            }

            const res = await fetch(`${API_BASE}/analytics/insights`, { headers });
            if (res.ok) {
                const data = await res.json();
                if (data && (data.total_clips > 0 || data.totalClips > 0)) {
                    setStats({
                        totalClips: data.total_clips || data.totalClips || 0,
                        totalEpisodes: data.total_episodes || data.totalEpisodes || 0,
                        avgViralityScore: data.average_score || data.avgViralityScore || 0,
                        topHookTypes: data.top_hook_types || data.topHookTypes || {},
                        topCategories: data.top_categories || data.topCategories || {},
                        avgDuration: data.avg_duration || data.avgDuration || 0,
                    });
                    setHasData(true);
                }
            }
        } catch (error) {
            // API not available or no data yet — show empty state
        } finally {
            setIsLoading(false);
        }
    };

    if (isLoading) {
        return (
            <div className="flex justify-center py-20">
                <Loader2 className="w-8 h-8 text-brand-500 animate-spin" />
            </div>
        );
    }

    // Empty state — no clips processed yet
    if (!hasData) {
        return (
            <div className="space-y-6">
                {/* Hero Empty State */}
                <div className="relative bg-zinc-900/40 border border-white/5 rounded-2xl p-10 text-center overflow-hidden">
                    <div className="absolute inset-0 bg-gradient-to-br from-brand-500/5 via-transparent to-purple-500/5 pointer-events-none"></div>
                    <div className="relative z-10">
                        <div className="w-16 h-16 mx-auto mb-6 bg-brand-500/10 rounded-2xl flex items-center justify-center">
                            <Zap className="w-8 h-8 text-brand-400" />
                        </div>
                        <h3 className="text-2xl font-bold text-white mb-3">Personal Intelligence</h3>
                        <p className="text-zinc-400 max-w-lg mx-auto mb-6 leading-relaxed">
                            Process your first episode to unlock insights about your content.
                            Celia analyzes hook types, topics, pacing, and virality patterns
                            unique to <strong className="text-zinc-300">your</strong> podcast.
                        </p>
                        <a
                            href="/dashboard"
                            className="inline-flex items-center gap-2 px-6 py-3 bg-brand-600 hover:bg-brand-500 text-white rounded-xl font-medium transition-colors shadow-lg shadow-brand-500/20"
                        >
                            <Film className="w-4 h-4" /> Process Your First Episode
                        </a>
                    </div>
                </div>

                {/* Preview Cards — what they'll see once data exists */}
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <PreviewCard
                        icon={<Activity className="w-5 h-5 text-brand-400" />}
                        title="Avg. Virality Score"
                        description="Your predicted clip virality based on content analysis"
                    />
                    <PreviewCard
                        icon={<TrendingUp className="w-5 h-5 text-blue-400" />}
                        title="Top Hook Patterns"
                        description="Which opening hooks perform best in your clips"
                    />
                    <PreviewCard
                        icon={<Users className="w-5 h-5 text-purple-400" />}
                        title="Speaker Insights"
                        description="Face appearances and speaking patterns across episodes"
                    />
                </div>

                {/* What Personal Intelligence will show */}
                <div className="bg-zinc-900/20 border border-white/5 rounded-2xl p-6">
                    <h4 className="text-sm font-medium text-zinc-400 uppercase tracking-widest mb-4">
                        What you'll discover
                    </h4>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                        {[
                            { icon: '🎯', label: 'Your most viral hook types' },
                            { icon: '⏱️', label: 'Optimal clip duration for your content' },
                            { icon: '🎙️', label: 'Speaker ratio impact on engagement' },
                            { icon: '📊', label: 'Topic performance by category' },
                            { icon: '🔥', label: 'Content patterns that drive views' },
                            { icon: '📈', label: 'YouTube performance correlation' },
                        ].map((item) => (
                            <div key={item.label} className="flex items-center gap-3 text-sm">
                                <span className="text-lg">{item.icon}</span>
                                <span className="text-zinc-300">{item.label}</span>
                            </div>
                        ))}
                    </div>
                </div>
            </div>
        );
    }

    // Real data view
    return (
        <div className="space-y-6">
            {/* Stats Grid */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                {/* Global Average Score */}
                <div className="bg-zinc-900/40 border border-white/5 p-6 rounded-2xl flex flex-col justify-between">
                    <div className="flex justify-between items-start mb-4">
                        <div className="p-3 bg-brand-500/10 rounded-xl">
                            <Activity className="w-6 h-6 text-brand-400" />
                        </div>
                        <span className="text-xs font-medium px-2 py-1 bg-white/5 rounded-md text-zinc-400">All Time</span>
                    </div>
                    <div>
                        <h4 className="text-zinc-400 text-sm font-medium mb-1">Avg. Predicted Virality</h4>
                        <div className="flex items-end gap-2">
                            <span className="text-4xl font-bold text-white">{stats!.avgViralityScore.toFixed(1)}</span>
                            <span className="text-lg text-zinc-500 mb-1">/ 100</span>
                        </div>
                    </div>
                </div>

                {/* Clips Processed */}
                <div className="bg-zinc-900/40 border border-white/5 p-6 rounded-2xl flex flex-col justify-between">
                    <div className="flex justify-between items-start mb-4">
                        <div className="p-3 bg-emerald-500/10 rounded-xl">
                            <Film className="w-6 h-6 text-emerald-400" />
                        </div>
                        <span className="text-xs font-medium px-2 py-1 bg-white/5 rounded-md text-zinc-400">Pipeline</span>
                    </div>
                    <div>
                        <h4 className="text-zinc-400 text-sm font-medium mb-1">Clips Generated</h4>
                        <div className="flex items-end gap-2">
                            <span className="text-4xl font-bold text-white">{stats!.totalClips}</span>
                            <span className="text-sm text-zinc-500 mb-1">from {stats!.totalEpisodes} episodes</span>
                        </div>
                    </div>
                </div>

                {/* Top Performing Hooks */}
                <div className="bg-zinc-900/40 border border-white/5 p-6 rounded-2xl">
                    <div className="flex items-center gap-3 mb-6">
                        <div className="p-2 bg-blue-500/10 rounded-lg">
                            <TrendingUp className="w-5 h-5 text-blue-400" />
                        </div>
                        <h4 className="text-zinc-200 font-medium">Top Hook Patterns</h4>
                    </div>

                    <div className="space-y-4">
                        {Object.entries(stats!.topHookTypes || stats!.topCategories).slice(0, 3).map(([name, score], idx) => (
                            <div key={name}>
                                <div className="flex justify-between text-sm mb-1.5">
                                    <span className="text-zinc-300 capitalize">{name.replace(/_/g, ' ')}</span>
                                    <span className="text-zinc-500 font-mono">{typeof score === 'number' ? score : 0}</span>
                                </div>
                                <div className="h-1.5 w-full bg-black rounded-full overflow-hidden">
                                    <div
                                        className={`h-full rounded-full ${idx === 0 ? 'bg-blue-500' : idx === 1 ? 'bg-blue-500/60' : 'bg-blue-500/30'}`}
                                        style={{ width: `${Math.min(100, typeof score === 'number' ? score : 0)}%` }}
                                    />
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            </div>
        </div>
    );
};

// Small preview card for the empty state
const PreviewCard: React.FC<{ icon: React.ReactNode; title: string; description: string }> = ({ icon, title, description }) => (
    <div className="bg-zinc-900/40 border border-white/5 rounded-2xl p-5 opacity-60">
        <div className="flex items-center gap-3 mb-3">
            <div className="p-2 bg-white/5 rounded-lg">
                {icon}
            </div>
            <h4 className="text-zinc-300 font-medium text-sm">{title}</h4>
        </div>
        <div className="h-8 bg-zinc-800/50 rounded-lg mb-2 animate-pulse"></div>
        <p className="text-xs text-zinc-500">{description}</p>
    </div>
);
