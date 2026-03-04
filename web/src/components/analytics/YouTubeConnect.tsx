import React, { useEffect, useState } from 'react';
import { Youtube, CheckCircle2, AlertCircle, RefreshCw, Upload, ExternalLink } from 'lucide-react';
import toast from 'react-hot-toast';
import { supabase } from '../../lib/supabase';

interface YouTubeStatus {
    is_connected: boolean;
    channel_name?: string;
    channel_id?: string;
    subscriber_count?: string;
    video_count?: string;
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
    const [status, setStatus] = useState<YouTubeStatus>({ is_connected: false });
    const [isLoading, setIsLoading] = useState(true);
    const [isSyncing, setIsSyncing] = useState(false);
    const [isConnecting, setIsConnecting] = useState(false);

    useEffect(() => {
        checkStatus();

        // Handle OAuth callback if we have a code in the URL
        const urlParams = new URLSearchParams(window.location.search);
        const code = urlParams.get('code');
        if (code) {
            handleOAuthCallback(code);
            // Clean up URL
            window.history.replaceState({}, '', window.location.pathname);
        }
    }, []);

    const checkStatus = async () => {
        try {
            const res = await fetchWithAuth('/connections/youtube');
            if (res.ok) {
                const data = await res.json();
                setStatus(data);
            } else {
                setStatus({ is_connected: false });
            }
        } catch (e) {
            setStatus({ is_connected: false });
        } finally {
            setIsLoading(false);
        }
    };

    const handleConnect = async () => {
        setIsConnecting(true);
        try {
            const redirectUri = `${window.location.origin}/dashboard/intelligence`;
            const res = await fetchWithAuth(`/auth/youtube/authorize?redirect_uri=${encodeURIComponent(redirectUri)}`);

            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'Failed to start YouTube authorization');
            }

            const { url } = await res.json();
            // Redirect to Google OAuth consent screen
            window.location.href = url;
        } catch (error: any) {
            toast.error(error.message || 'Failed to connect YouTube');
            setIsConnecting(false);
        }
    };

    const handleOAuthCallback = async (code: string) => {
        const toastId = toast.loading('Connecting your YouTube channel...');
        try {
            const redirectUri = `${window.location.origin}/dashboard/intelligence`;
            const res = await fetchWithAuth('/auth/youtube/callback', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ code, redirect_uri: redirectUri })
            });

            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'Failed to complete YouTube authorization');
            }

            const data = await res.json();
            toast.success(`Connected to ${data.channel}!`, { id: toastId, icon: '🎬' });
            checkStatus();
        } catch (error: any) {
            toast.error(error.message || 'Connection failed', { id: toastId });
        }
    };

    const handleSync = async () => {
        setIsSyncing(true);
        const toastId = toast.loading('Syncing analytics from YouTube...');
        try {
            // Get the provider token from Supabase session (if user logged in via Google)
            const { data } = await supabase.auth.getSession();
            const providerToken = data?.session?.provider_token;

            if (!providerToken) {
                toast.error('No Google provider token available. Re-login with Google to sync.', { id: toastId });
                return;
            }

            const formData = new FormData();
            formData.append('provider_token', providerToken);

            const res = await fetchWithAuth('/analytics/fetch-youtube', {
                method: 'POST',
                body: formData
            });

            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'Sync failed');
            }

            const result = await res.json();
            toast.success(`Synced! ${result.videos_scanned} videos scanned, ${result.clips_matched} matched.`, { id: toastId });
            checkStatus();
        } catch (error: any) {
            toast.error(error.message || 'Failed to sync analytics', { id: toastId });
        } finally {
            setIsSyncing(false);
        }
    };

    if (isLoading) {
        return <div className="animate-pulse h-32 bg-zinc-900/50 rounded-2xl border border-white/5"></div>;
    }

    const isConnected = status?.is_connected;

    return (
        <div className="bg-zinc-900/40 border border-white/5 rounded-2xl p-6 relative overflow-hidden flex flex-col md:flex-row gap-6 items-center justify-between">
            {/* Decorative background element */}
            <div className="absolute -right-20 -top-20 w-64 h-64 bg-red-500/10 rounded-full blur-3xl pointer-events-none"></div>

            <div className="flex items-start gap-4 z-10">
                <div className={`p-3 rounded-xl ${isConnected ? 'bg-red-500/10 text-red-500' : 'bg-zinc-800 text-zinc-400'}`}>
                    <Youtube className="w-8 h-8" />
                </div>
                <div>
                    <h3 className="text-xl font-bold text-white mb-1">YouTube Integration</h3>
                    {isConnected ? (
                        <div className="flex items-center gap-2 text-sm text-green-400">
                            <CheckCircle2 className="w-4 h-4" /> Connected as {status?.channel_name || 'Channel'}
                        </div>
                    ) : (
                        <div className="flex items-center gap-2 text-sm text-zinc-500">
                            <AlertCircle className="w-4 h-4" /> Not Connected
                        </div>
                    )}
                    <p className="text-sm text-zinc-400 mt-2 max-w-sm">
                        {isConnected
                            ? 'Your local virality scores are actively being correlated with actual YouTube Shorts performance.'
                            : 'Connect your channel to correlate predicted Virality Scores with actual view counts.'}
                    </p>
                </div>
            </div>

            <div className="z-10 flex gap-3 w-full md:w-auto">
                {isConnected ? (
                    <button
                        onClick={handleSync}
                        disabled={isSyncing}
                        className="flex-1 md:flex-none flex items-center justify-center gap-2 px-6 py-2.5 bg-white/5 hover:bg-white/10 border border-white/10 text-white rounded-xl font-medium transition-colors disabled:opacity-50"
                    >
                        <RefreshCw className={`w-4 h-4 ${isSyncing ? 'animate-spin' : ''}`} />
                        {isSyncing ? 'Syncing...' : 'Sync Data'}
                    </button>
                ) : (
                    <button
                        onClick={handleConnect}
                        disabled={isConnecting}
                        className="flex-1 md:flex-none flex items-center justify-center gap-2 px-6 py-2.5 bg-red-600 hover:bg-red-500 text-white rounded-xl font-medium transition-colors shadow-lg shadow-red-500/20 disabled:opacity-50"
                    >
                        <Youtube className="w-4 h-4" />
                        {isConnecting ? 'Connecting...' : 'Connect Channel'}
                    </button>
                )}
            </div>
        </div>
    );
};
