import React, { useEffect, useState } from 'react';
import { Youtube, CheckCircle2, AlertCircle, RefreshCw, Loader2 } from 'lucide-react';
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

const API_BASE = (import.meta.env?.PUBLIC_API_URL as string) || '/api';

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
        // Check if we have a ?code= from OAuth callback
        const urlParams = new URLSearchParams(window.location.search);
        const code = urlParams.get('code');

        if (code) {
            // Clean URL immediately
            window.history.replaceState({}, '', window.location.pathname);
            handleOAuthCallback(code);
        } else {
            checkStatus();
        }
    }, []);

    const checkStatus = async () => {
        try {
            const res = await fetchWithAuth('/analytics/youtube/status');
            if (res.ok) {
                const data = await res.json();
                setStatus(data);
                if (data.connected && data.total_shorts > 0) {
                    loadInsights();
                }
            }
        } catch (e) { /* not connected */ }
        finally { setIsLoading(false); }
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
        // Use backend OAuth flow — lets user pick ANY Google account
        try {
            const redirectUri = window.location.origin + '/dashboard/intelligence';
            const res = await fetchWithAuth(`/auth/youtube/authorize?redirect_uri=${encodeURIComponent(redirectUri)}`);

            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'Failed to start YouTube authorization');
            }

            const { url } = await res.json();
            // Redirect to Google consent (user picks their YouTube account)
            window.location.href = url;
        } catch (error: any) {
            toast.error(error.message || 'Failed to connect YouTube');
        }
    };

    const handleOAuthCallback = async (code: string) => {
        setIsLoading(true);
        const toastId = toast.loading('Connecting your YouTube channel...');

        try {
            // Exchange the code for an access token via backend
            const redirectUri = window.location.origin + '/dashboard/intelligence';
            const res = await fetchWithAuth('/analytics/youtube/sync-with-code', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ code, redirect_uri: redirectUri })
            });

            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'Failed to connect YouTube');
            }

            const result = await res.json();
            toast.success(`Synced ${result.total_shorts} videos from ${result.channel_name}!`, { id: toastId, icon: '🎬' });

            setStatus({
                connected: true,
                channel_name: result.channel_name,
                total_shorts: result.total_shorts,
                last_synced: new Date().toISOString()
            });

            await loadInsights();
        } catch (error: any) {
            toast.error(error.message || 'Connection failed', { id: toastId });
        } finally {
            setIsLoading(false);
        }
    };

    const handleResync = async () => {
        setIsSyncing(true);
        const toastId = toast.loading('Re-syncing YouTube data...');
        try {
            // Re-sync requires re-auth since tokens expire
            handleConnect();
        } catch (error: any) {
            toast.error(error.message || 'Re-sync failed', { id: toastId });
            setIsSyncing(false);
        }
    };

    if (isLoading) {
        return (
            <div className="flex justify-center items-center py-12">
                <Loader2 className="w-8 h-8 text-red-500 animate-spin" />
                <span className="ml-3 text-zinc-400">Connecting to YouTube...</span>
            </div>
        );
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
                        <h3 className="text-xl font-bold text-white mb-1">YouTube Analytics</h3>
                        {status.connected ? (
                            <>
                                <div className="flex items-center gap-2 text-sm text-green-400">
                                    <CheckCircle2 className="w-4 h-4" /> Connected{status.channel_name ? ` — ${status.channel_name}` : ''}
                                </div>
                                <p className="text-sm text-zinc-500 mt-1">
                                    {status.total_shorts} videos synced{status.last_synced ? ` · Last synced ${new Date(status.last_synced).toLocaleDateString()}` : ''}
                                </p>
                            </>
                        ) : (
                            <>
                                <div className="flex items-center gap-2 text-sm text-zinc-500">
                                    <AlertCircle className="w-4 h-4" /> Not Connected
                                </div>
                                <p className="text-sm text-zinc-400 mt-2 max-w-sm">
                                    Connect your YouTube channel to see performance insights from all your videos.
                                    You can connect any Google account — it doesn't have to be the one you logged in with.
                                </p>
                            </>
                        )}
                    </div>
                </div>

                <div className="z-10 flex gap-3 w-full md:w-auto">
                    {status.connected ? (
                        <button
                            onClick={handleResync}
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

            {/* Insights */}
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
                            <div key={i} className="flex items-center justify-between gap-4 py-2 border-b border-white/5 last:border-0">
                                <div className="flex items-center gap-3 min-w-0">
                                    <span className="text-zinc-600 text-sm font-mono w-5">#{i + 1}</span>
                                    <a href={vid.url} target="_blank" rel="noopener noreferrer"
                                        className="text-zinc-200 text-sm truncate hover:text-white transition-colors">
                                        {vid.title}
                                    </a>
                                </div>
                                <div className="flex items-center gap-2 shrink-0">
                                    <span className="text-sm font-medium text-white">{formatNumber(vid.views)}</span>
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
                            const maxViews = Math.max(...insights.duration_breakdown.map(b => b.avg_views));
                            const pct = maxViews > 0 ? (bucket.avg_views / maxViews) * 100 : 0;
                            return (
                                <div key={bucket.range}>
                                    <div className="flex justify-between text-sm mb-1.5">
                                        <span className="text-zinc-300">{bucket.range}</span>
                                        <span className="text-zinc-500">
                                            {bucket.count} videos · avg {formatNumber(bucket.avg_views)} views
                                        </span>
                                    </div>
                                    <div className="h-2 w-full bg-black rounded-full overflow-hidden">
                                        <div className="h-full rounded-full bg-red-500/70" style={{ width: `${pct}%` }} />
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
