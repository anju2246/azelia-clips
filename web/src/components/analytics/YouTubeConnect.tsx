import React, { useEffect, useState } from 'react';
import { Youtube, CheckCircle2, AlertCircle, RefreshCw } from 'lucide-react';
import { IntelligenceApi } from '../../lib/api';
import toast from 'react-hot-toast';

export const YouTubeConnect: React.FC = () => {
    const [status, setStatus] = useState<any>(null);
    const [isLoading, setIsLoading] = useState(true);
    const [isSyncing, setIsSyncing] = useState(false);

    useEffect(() => {
        checkStatus();
    }, []);

    const checkStatus = async () => {
        try {
            // In a real app we'd fetch actual status. We simulate for MVP or fetch real if implemented.
            const res = await IntelligenceApi.getYouTubeStatus();
            setStatus(res);
        } catch (e) {
            // API might return 404 if not connected
            setStatus({ is_connected: false });
        } finally {
            setIsLoading(false);
        }
    };

    const handleConnect = () => {
        // Redirect to OAuth
        window.location.href = 'http://localhost:8000/api/auth/youtube/authorize';
    };

    const handleSync = async () => {
        setIsSyncing(true);
        const toastId = toast.loading('Syncing analytics from YouTube...');
        try {
            await IntelligenceApi.fetchYouTubeAnalytics();
            toast.success('Analytics synced successfully!', { id: toastId });
            checkStatus(); // Refresh data
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
                        className="flex-1 md:flex-none flex items-center justify-center gap-2 px-6 py-2.5 bg-red-600 hover:bg-red-500 text-white rounded-xl font-medium transition-colors shadow-lg shadow-red-500/20"
                    >
                        <Youtube className="w-4 h-4" /> Connect Channel
                    </button>
                )}
            </div>
        </div>
    );
};
