import React, { useEffect, useState } from 'react';
import { Youtube, CheckCircle2, AlertCircle, RefreshCw, Loader2, BarChart3 } from 'lucide-react';
import toast from 'react-hot-toast';
import { supabase } from '../../lib/supabase';

interface YouTubeStatus {
    connected: boolean;
    channel_name?: string;
    total_shorts: number;
    last_synced?: string;
}

interface YouTubeInsights {
    total_shorts: number;
    total_views: number;
    total_likes: number;
    avg_views: number;
    avg_duration: number;
    best_performing: { title: string; views: number; url: string }[];
    duration_breakdown: { range: string; count: number; avg_views: number }[];
}

const API_BASE = import.meta.env?.PUBLIC_API_URL || 'http://localhost:8000/api';

async function fetchWithAuth(endpoint: string, options: RequestInit = {}) {
    const headers = new Headers(options.headers || {});
    try {
        const { data } = await supabase.auth.getSession();
        if (data?.session?.access_token) {
            headers.set('Authorization', `Bearer ${data.session.access_token}`);
        }
    } catch (e) { /* continue */ }
    return fetch(`${API_BASE}${endpoint}`, { ...options, headers });
}

export const YouTubeConnect: React.FC = () => {
    const [status, setStatus] = useState<YouTubeStatus>({ connected: false, total_shorts: 0 });
    const [insights, setInsights] = useState<YouTubeInsights | null>(null);
    const [isLoading, setIsLoading] = useState(true);
    const [isSyncing, setIsSyncing] = useState(false);

    useEffect(() => {
        checkConnectionAndSync();
    }, []);

    const checkConnectionAndSync = async () => {
        try {
            // Check if we already have synced data
            const statusRes = await fetchWithAuth('/analytics/youtube/status');
            if (statusRes.ok) {
                const data = await statusRes.json();
                setStatus(data);
                if (data.connected && data.total_shorts > 0) {
                    loadInsights();
                }
            }

            // Check if we just came back from OAuth and have a provider_token with YouTube access
            const { data: session } = await supabase.auth.getSession();
            if (session?.session?.provider_token) {
                // We have a Google provider token — try to sync if not already done
                const res = await fetchWithAuth('/analytics/youtube/status');
                const currentStatus = await res.json();
                if (!currentStatus.connected || currentStatus.total_shorts === 0) {
                    await handleSync();
                }
            }
        } catch (e) {
            // Not connected yet
        } finally {
            setIsLoading(false);
        }
    };

    const loadInsights = async () => {
        try {
            const res = await fetchWithAuth('/analytics/youtube/insights');
            if (res.ok) {
                const data = await res.json();
                setInsights(data);
            }
        } catch (e) { /* no insights yet */ }
    };

    const handleConnect = async () => {
        // Use Supabase's Google OAuth with incremental YouTube scope
        // This will show a NEW consent screen asking for YouTube read access
        const { error } = await supabase.auth.signInWithOAuth({
            provider: 'google',
            options: {
                scopes: 'https://www.googleapis.com/auth/youtube.readonly',
                redirectTo: `${window.location.origin}/auth/callback?next=/dashboard/intelligence`,
                queryParams: {
                    access_type: 'offline',
                    prompt: 'consent',
                }
            }
        });

        if (error) {
            toast.error('Failed to start YouTube connection: ' + error.message);
        }
        // User will be redirected to Google consent screen
    };

    const handleSync = async () => {
        setIsSyncing(true);
        const toastId = toast.loading('Fetching your YouTube Shorts...');

        try {
            const { data: session } = await supabase.auth.getSession();
            const providerToken = session?.session?.provider_token;

            if (!providerToken) {
                toast.error('No YouTube access token found. Click "Connect YouTube" first.', { id: toastId });
                setIsSyncing(false);
                return;
            }

            const res = await fetchWithAuth('/analytics/youtube/sync', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ provider_token: providerToken })
            });

            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'Sync failed');
            }

            const result = await res.json();
            toast.success(`Synced ${result.total_shorts} shorts from your channel!`, { id: toastId, icon: '🎬' });

            setStatus({
                connected: true,
                channel_name: result.channel_name,
                total_shorts: result.total_shorts,
                last_synced: new Date().toISOString()
            });

            // Load insights after sync
            await loadInsights();
        } catch (error: any) {
            toast.error(error.message || 'Failed to sync', { id: toastId });
        } finally {
            setIsSyncing(false);
        }
    };

    if (isLoading) {
        return <div className="animate-pulse h-32 bg-zinc-900/50 rounded-2xl border border-white/5"></div>;
    }

    return (
        <div className="space-y-6">
            {/* Connection Card */}
            <div className="bg-zinc-900/40 border border-white/5 rounded-2xl p-6 relative overflow-hidden flex flex-col md:flex-row gap-6 items-center justify-between">
                <div className="absolute -right-20 -top-20 w-64 h-64 bg-red-500/10 rounded-full blur-3xl pointer-events-none"></div>

                <div className="flex items-start gap-4 z-10">
                    <div className={`p-3 rounded-xl ${status.connected ? 'bg-red-500/10 text-red-500' : 'bg-zinc-800 text-zinc-400'}`}>
                        <Youtube className="w-8 h-8" />
                    </div>
                    <div>
                        <h3 className="text-xl font-bold text-white mb-1">YouTube Shorts</h3>
                        {status.connected ? (
                            <>
                                <div className="flex items-center gap-2 text-sm text-green-400">
                                    <CheckCircle2 className="w-4 h-4" /> Connected{status.channel_name ? ` — ${status.channel_name}` : ''}
                                </div>
                                <p className="text-sm text-zinc-500 mt-1">
                                    {status.total_shorts} shorts synced{status.last_synced ? ` · Last synced ${new Date(status.last_synced).toLocaleDateString()}` : ''}
                                </p>
                            </>
                        ) : (
                            <>
                                <div className="flex items-center gap-2 text-sm text-zinc-500">
                                    <AlertCircle className="w-4 h-4" /> Not Connected
                                </div>
                                <p className="text-sm text-zinc-400 mt-2 max-w-sm">
                                    Connect your channel to see performance insights from your historical Shorts.
                                </p>
                            </>
                        )}
                    </div>
                </div>

                <div className="z-10 flex gap-3 w-full md:w-auto">
                    {status.connected ? (
                        <button
                            onClick={handleSync}
                            disabled={isSyncing}
                            className="flex-1 md:flex-none flex items-center justify-center gap-2 px-6 py-2.5 bg-white/5 hover:bg-white/10 border border-white/10 text-white rounded-xl font-medium transition-colors disabled:opacity-50"
                        >
                            <RefreshCw className={`w-4 h-4 ${isSyncing ? 'animate-spin' : ''}`} />
                            {isSyncing ? 'Syncing...' : 'Re-sync'}
                        </button>
                    ) : (
                        <button
                            onClick={handleConnect}
                            className="flex-1 md:flex-none flex items-center justify-center gap-2 px-6 py-2.5 bg-red-600 hover:bg-red-500 text-white rounded-xl font-medium transition-colors shadow-lg shadow-red-500/20"
                        >
                            <Youtube className="w-4 h-4" /> Connect YouTube
                        </button>
                    )}
                </div>
            </div>

            {/* Insights Section */}
            {insights && insights.total_shorts > 0 && <YouTubeInsightsView insights={insights} />}
        </div>
    );
};

// ─── Insights View ──────────────────────────────────────────────────────────

const YouTubeInsightsView: React.FC<{ insights: YouTubeInsights }> = ({ insights }) => {
    const formatNumber = (n: number) => {
        if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
        if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
        return n.toString();
    };

    return (
        <div className="space-y-6">
            {/* Stats Row */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <StatCard label="Total Shorts" value={insights.total_shorts.toString()} />
                <StatCard label="Total Views" value={formatNumber(insights.total_views)} />
                <StatCard label="Avg. Views" value={formatNumber(insights.avg_views)} />
                <StatCard label="Total Likes" value={formatNumber(insights.total_likes)} />
            </div>

            {/* Top Performing Shorts */}
            {insights.best_performing.length > 0 && (
                <div className="bg-zinc-900/40 border border-white/5 rounded-2xl p-6">
                    <h4 className="text-sm font-medium text-zinc-400 uppercase tracking-widest mb-4">
                        🏆 Top Performing Shorts
                    </h4>
                    <div className="space-y-3">
                        {insights.best_performing.map((short, i) => (
                            <div key={i} className="flex items-center justify-between gap-4 py-2 border-b border-white/5 last:border-0">
                                <div className="flex items-center gap-3 min-w-0">
                                    <span className="text-zinc-600 text-sm font-mono w-5">#{i + 1}</span>
                                    <span className="text-zinc-200 text-sm truncate">{short.title}</span>
                                </div>
                                <div className="flex items-center gap-2 shrink-0">
                                    <span className="text-sm font-medium text-white">{formatNumber(short.views)}</span>
                                    <span className="text-xs text-zinc-500">views</span>
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* Duration Breakdown */}
            {insights.duration_breakdown.length > 0 && (
                <div className="bg-zinc-900/40 border border-white/5 rounded-2xl p-6">
                    <h4 className="text-sm font-medium text-zinc-400 uppercase tracking-widest mb-4">
                        ⏱️ Performance by Duration
                    </h4>
                    <div className="space-y-4">
                        {insights.duration_breakdown.map((bucket) => {
                            const maxViews = Math.max(...insights.duration_breakdown.map(b => b.avg_views));
                            const pct = maxViews > 0 ? (bucket.avg_views / maxViews) * 100 : 0;
                            return (
                                <div key={bucket.range}>
                                    <div className="flex justify-between text-sm mb-1.5">
                                        <span className="text-zinc-300">{bucket.range}</span>
                                        <span className="text-zinc-500">
                                            {bucket.count} shorts · avg {formatNumber(bucket.avg_views)} views
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

const StatCard: React.FC<{ label: string; value: string }> = ({ label, value }) => (
    <div className="bg-zinc-900/40 border border-white/5 rounded-xl p-4">
        <p className="text-xs text-zinc-500 mb-1">{label}</p>
        <p className="text-2xl font-bold text-white">{value}</p>
    </div>
);
