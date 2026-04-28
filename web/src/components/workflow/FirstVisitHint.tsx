import React, { useEffect, useState } from 'react';
import { Sparkles, ArrowDown, X } from 'lucide-react';
import { supabase } from '../../lib/supabase';

const API_BASE = (import.meta.env?.PUBLIC_API_URL as string) || '/api';
const LOCAL_FLAG = 'azelia_first_visit_hint_shown';

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

/**
 * FirstVisitHint — subtle acknowledgment banner shown once to a user who just
 * finished onboarding. It does NOT send the user back to Settings or anywhere
 * else — everything they need was collected in the wizard (API key, YouTube,
 * podcast dir, profile). It simply says "you're ready, upload an episode".
 *
 * Dismissal is tracked in two places:
 *   - localStorage: instant client-side dismissal so refresh doesn't re-show.
 *   - profiles.first_dashboard_visit_at (Supabase): server-side truth. When
 *     set, the hint never shows again on any device.
 */
export const FirstVisitHint: React.FC<{ onScrollToUpload?: () => void }> = ({ onScrollToUpload }) => {
    const [visible, setVisible] = useState(false);

    useEffect(() => {
        if (typeof window === 'undefined') return;
        if (localStorage.getItem(LOCAL_FLAG) === 'true') return;

        (async () => {
            try {
                const { data } = await supabase.auth.getSession();
                const user = data?.session?.user;
                if (!user) return;
                const svc = (import.meta.env?.PUBLIC_SUPABASE_URL as string) || '';
                const key = (import.meta.env?.PUBLIC_SUPABASE_ANON_KEY as string) || '';
                if (!svc || !key) return;
                const res = await fetch(
                    `${svc}/rest/v1/profiles?id=eq.${user.id}&select=first_dashboard_visit_at`,
                    {
                        headers: {
                            apikey: key,
                            Authorization: `Bearer ${data?.session?.access_token ?? ''}`,
                        },
                    }
                );
                if (!res.ok) return;
                const rows = await res.json();
                const already = rows?.[0]?.first_dashboard_visit_at;
                if (!already) setVisible(true);
            } catch { /* silent — hint is non-critical */ }
        })();
    }, []);

    const dismiss = async (markServer: boolean) => {
        setVisible(false);
        try {
            localStorage.setItem(LOCAL_FLAG, 'true');
        } catch { /* storage may be blocked */ }
        if (!markServer) return;
        try {
            const { data } = await supabase.auth.getSession();
            const user = data?.session?.user;
            if (!user) return;
            const svc = (import.meta.env?.PUBLIC_SUPABASE_URL as string) || '';
            const key = (import.meta.env?.PUBLIC_SUPABASE_ANON_KEY as string) || '';
            if (!svc || !key) return;
            await fetch(
                `${svc}/rest/v1/profiles?id=eq.${user.id}`,
                {
                    method: 'PATCH',
                    headers: {
                        apikey: key,
                        Authorization: `Bearer ${data?.session?.access_token ?? ''}`,
                        'Content-Type': 'application/json',
                        Prefer: 'return=minimal',
                    },
                    body: JSON.stringify({ first_dashboard_visit_at: new Date().toISOString() }),
                }
            );
        } catch { /* silent */ }
    };

    if (!visible) return null;

    return (
        <div className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-brand-500/10 via-zinc-900/70 to-zinc-900/80 border border-brand-500/30 p-5">
            <div className="absolute -top-10 -right-10 w-40 h-40 bg-brand-500/15 rounded-full blur-3xl pointer-events-none" />
            <div className="relative flex items-center gap-4">
                <div className="flex-shrink-0 w-11 h-11 rounded-xl bg-brand-500/20 flex items-center justify-center">
                    <Sparkles className="w-5 h-5 text-brand-400" />
                </div>
                <div className="flex-1 min-w-0">
                    <h3 className="text-white font-semibold text-sm">You're all set.</h3>
                    <p className="text-zinc-400 text-xs mt-0.5 leading-relaxed">
                        Everything from onboarding is saved. Pick an episode from your podcast directory below to run your first pipeline. Azelia processes everything locally — nothing is uploaded.
                    </p>
                </div>
                <button
                    onClick={() => {
                        onScrollToUpload?.();
                        dismiss(true);
                    }}
                    className="flex-shrink-0 flex items-center gap-2 px-4 py-2 bg-brand-600 hover:bg-brand-500 text-white text-sm font-medium rounded-lg transition-all shadow-lg shadow-brand-500/20"
                >
                    Pick an episode <ArrowDown className="w-4 h-4" />
                </button>
                <button
                    onClick={() => dismiss(true)}
                    className="flex-shrink-0 p-1.5 text-zinc-500 hover:text-zinc-300 transition-colors"
                    aria-label="Dismiss"
                >
                    <X className="w-4 h-4" />
                </button>
            </div>
        </div>
    );
};
