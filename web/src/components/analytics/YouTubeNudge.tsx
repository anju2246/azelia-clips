import React, { useState, useEffect } from 'react';
import { Youtube, X, ArrowRight, Sparkles } from 'lucide-react';

const DISMISS_KEY = 'azelia_yt_nudge_dismissed';

export const YouTubeNudge: React.FC = () => {
    const [dismissed, setDismissed] = useState(true);
    const [connected, setConnected] = useState(true);

    useEffect(() => {
        const wasDismissed = localStorage.getItem(DISMISS_KEY) === 'true';
        if (wasDismissed) return;

        // Check if YouTube is connected
        const checkStatus = async () => {
            try {
                const { supabase } = await import('../../lib/supabase');
                const { data } = await supabase.auth.getSession();
                const token = data?.session?.access_token;
                if (!token) return;

                const API_BASE = (import.meta.env?.PUBLIC_API_URL as string) || '/api';
                const res = await fetch(`${API_BASE}/analytics/youtube/status`, {
                    headers: { Authorization: `Bearer ${token}` }
                });
                if (res.ok) {
                    const status = await res.json();
                    setConnected(status.connected);
                    setDismissed(status.connected || wasDismissed);
                }
            } catch (e) { /* silently fail */ }
        };
        checkStatus();
    }, []);

    const handleDismiss = () => {
        localStorage.setItem(DISMISS_KEY, 'true');
        setDismissed(true);
    };

    if (dismissed || connected) return null;

    return (
        <div className="relative overflow-hidden rounded-2xl bg-gradient-to-r from-red-950/40 via-zinc-900/80 to-zinc-900/80 border border-red-500/20 p-5 mb-6 animate-in fade-in slide-in-from-top-2 duration-500">
            {/* Glow effect */}
            <div className="absolute -top-10 -left-10 w-40 h-40 bg-red-500/10 rounded-full blur-3xl" />

            <div className="relative flex items-center gap-4">
                <div className="flex-shrink-0 w-12 h-12 rounded-xl bg-red-500/20 flex items-center justify-center">
                    <Youtube className="w-6 h-6 text-red-500" />
                </div>

                <div className="flex-1 min-w-0">
                    <h3 className="text-white font-semibold text-sm flex items-center gap-2">
                        Connect YouTube to unlock Intelligence
                        <Sparkles className="w-4 h-4 text-brand-400" />
                    </h3>
                    <p className="text-zinc-400 text-xs mt-0.5 leading-relaxed">
                        Sync your channel to see what's working — duration trends, top-performing hooks, and growth patterns.
                    </p>
                </div>

                <a href="/dashboard/intelligence"
                    className="flex-shrink-0 flex items-center gap-2 px-4 py-2 bg-red-600 hover:bg-red-500 text-white text-sm font-medium rounded-lg transition-all shadow-lg shadow-red-500/20">
                    Connect <ArrowRight className="w-4 h-4" />
                </a>

                <button onClick={handleDismiss} className="flex-shrink-0 p-1.5 text-zinc-600 hover:text-zinc-400 transition-colors" aria-label="Dismiss">
                    <X className="w-4 h-4" />
                </button>
            </div>
        </div>
    );
};
