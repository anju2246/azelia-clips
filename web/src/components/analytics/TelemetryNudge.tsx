import React, { useState, useEffect } from 'react';
import { BarChart3, X, ArrowRight, Sparkles, Crown } from 'lucide-react';

const DISMISS_KEY = 'azelia_telemetry_nudge_dismissed';

export const TelemetryNudge: React.FC = () => {
    // Same pattern as YouTubeNudge: stay hidden until we know the user's
    // consent state. Otherwise the banner flashes for users who already
    // opted-in during onboarding.
    const [checked, setChecked] = useState(false);
    const [dismissed, setDismissed] = useState(false);
    const [enabled, setEnabled] = useState(false);

    useEffect(() => {
        const wasDismissed = localStorage.getItem(DISMISS_KEY) === 'true';
        if (wasDismissed) {
            setDismissed(true);
            setChecked(true);
            return;
        }

        const checkStatus = async () => {
            try {
                const { supabase } = await import('../../lib/supabase');
                const { data } = await supabase.auth.getSession();
                const token = data?.session?.access_token;
                if (!token) { setChecked(true); return; }

                const API_BASE = (import.meta.env?.PUBLIC_API_URL as string) || '/api';
                const res = await fetch(`${API_BASE}/telemetry/status`, {
                    headers: { Authorization: `Bearer ${token}` }
                });
                if (res.ok) {
                    const status = await res.json();
                    setEnabled(!!status.telemetry_enabled);
                }
            } catch (e) { /* silently fail — surface as not-enabled, user can dismiss */ }
            finally {
                setChecked(true);
            }
        };
        checkStatus();
    }, []);

    const handleDismiss = () => {
        localStorage.setItem(DISMISS_KEY, 'true');
        setDismissed(true);
    };

    // Three suppressions, mirrored from YouTubeNudge:
    //   1. We haven't finished checking status yet (no flash).
    //   2. User dismissed it on this device.
    //   3. Telemetry is already on.
    if (!checked || dismissed || enabled) return null;

    return (
        <div className="relative overflow-hidden rounded-2xl bg-gradient-to-r from-brand-950/40 via-zinc-900/80 to-zinc-900/80 border border-brand-500/20 p-5 mb-6 animate-in fade-in slide-in-from-top-2 duration-500">
            <div className="absolute -top-10 -left-10 w-40 h-40 bg-brand-500/10 rounded-full blur-3xl" />

            <div className="relative flex items-center gap-4">
                <div className="flex-shrink-0 w-12 h-12 rounded-xl bg-brand-500/20 flex items-center justify-center">
                    <BarChart3 className="w-6 h-6 text-brand-400" />
                </div>

                <div className="flex-1 min-w-0">
                    <h3 className="text-white font-semibold text-sm flex items-center gap-2">
                        Activate Collective Intelligence
                        <Sparkles className="w-4 h-4 text-brand-400" />
                    </h3>
                    <p className="text-zinc-400 text-xs mt-0.5 leading-relaxed">
                        Anonymous metrics power niche benchmarks and improve how the Ranker scores your clips.
                        Your videos, audio and transcripts never leave your machine.
                    </p>
                    <p className="text-amber-300/80 text-[11px] mt-1.5 flex items-center gap-1.5">
                        <Crown className="w-3 h-3" />
                        Heads up: Pro users without telemetry miss the niche signals the Ranker depends on.
                    </p>
                </div>

                <a href="/dashboard/settings#privacy"
                    className="flex-shrink-0 flex items-center gap-2 px-4 py-2 bg-brand-600 hover:bg-brand-500 text-white text-sm font-medium rounded-lg transition-all shadow-lg shadow-brand-500/20">
                    Activate <ArrowRight className="w-4 h-4" />
                </a>

                <button onClick={handleDismiss} className="flex-shrink-0 p-1.5 text-zinc-600 hover:text-zinc-400 transition-colors" aria-label="Dismiss">
                    <X className="w-4 h-4" />
                </button>
            </div>
        </div>
    );
};
