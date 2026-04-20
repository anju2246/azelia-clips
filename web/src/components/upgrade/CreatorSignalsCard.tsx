import React, { useEffect, useState } from 'react';
import { Brain, Loader2, Sparkles, CheckCircle2, X } from 'lucide-react';
import { supabase } from '../../lib/supabase';
import toast from 'react-hot-toast';

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

interface Estimate {
    num_shorts: number;
    batch_size: number;
    total_shorts_available: number;
    cost_usd_est: number;
    model: string;
    input_tokens_est: number;
    output_tokens_est: number;
}

interface RunResult {
    signals_created: number;
    cost_actual_usd: number | null;
    patterns_summary: Array<Record<string, any>>;
}

/**
 * CreatorSignalsCard — opt-in prompt to extract structural patterns from the
 * user's top-performing YouTube shorts and feed them (anonymized via
 * cohort_hash, source_type='creator_self') into the central IC Cascade.
 *
 * Uses the user's own Anthropic key. Shows cost estimate upfront. Nothing
 * runs without explicit confirmation.
 */
export const CreatorSignalsCard: React.FC<{ onDone?: () => void }> = ({ onDone }) => {
    const [estimate, setEstimate] = useState<Estimate | null>(null);
    const [loading, setLoading] = useState(true);
    const [running, setRunning] = useState(false);
    const [result, setResult] = useState<RunResult | null>(null);
    const [dismissed, setDismissed] = useState(false);

    useEffect(() => {
        fetchWithAuth('/analytics/youtube/extract-creator-signals/estimate')
            .then(r => r.ok ? r.json() : null)
            .then(d => { if (d) setEstimate(d); })
            .catch(() => {})
            .finally(() => setLoading(false));
    }, []);

    const handleRun = async () => {
        setRunning(true);
        try {
            const res = await fetchWithAuth('/analytics/youtube/extract-creator-signals', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ confirmed: true, batch_size: estimate?.batch_size ?? 30 }),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `Error ${res.status}`);
            }
            const data: RunResult = await res.json();
            setResult(data);
            toast.success(`Extracted ${data.signals_created} patterns`, { icon: '🧠' });
            onDone?.();
        } catch (e: any) {
            toast.error(e.message || 'Extraction failed');
        } finally {
            setRunning(false);
        }
    };

    if (dismissed) return null;

    if (loading) {
        return (
            <div className="rounded-2xl border border-white/10 bg-zinc-900/40 p-6 flex items-center gap-3">
                <Loader2 className="w-5 h-5 animate-spin text-zinc-400" />
                <span className="text-sm text-zinc-400">Checking what's available to analyze…</span>
            </div>
        );
    }

    if (!estimate || estimate.total_shorts_available < 5) {
        return null; // Not enough shorts to make the extraction useful.
    }

    if (result) {
        return (
            <div className="rounded-2xl border border-green-500/30 bg-gradient-to-br from-green-500/10 to-zinc-900/80 p-6 space-y-3">
                <div className="flex items-center gap-3">
                    <div className="p-2 rounded-xl bg-green-500/20">
                        <CheckCircle2 className="w-5 h-5 text-green-400" />
                    </div>
                    <div>
                        <h3 className="font-semibold text-white text-sm">Creator signals extracted</h3>
                        <p className="text-xs text-green-400">
                            {result.signals_created} patterns added to the IC Cascade
                            {result.cost_actual_usd ? ` · ${result.cost_actual_usd.toFixed(3)} USD billed to your Anthropic key` : ''}
                        </p>
                    </div>
                </div>
                {result.patterns_summary && result.patterns_summary.length > 0 && (
                    <div className="pt-2 grid grid-cols-2 gap-2 text-xs">
                        {result.patterns_summary.slice(0, 6).map((p, i) => (
                            <div key={i} className="px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-zinc-300 font-mono">
                                <span className="text-[10px] uppercase tracking-widest text-zinc-500">{p.signal_type}</span>
                                <div className="text-white">{p.hook_type || p.emotional_charge || p.duration_bucket || p.topic_tag || '—'}</div>
                            </div>
                        ))}
                    </div>
                )}
            </div>
        );
    }

    return (
        <div className="rounded-2xl border border-brand-500/30 bg-gradient-to-br from-brand-500/10 to-zinc-900/80 p-6 space-y-5 relative">
            <button
                aria-label="Dismiss"
                onClick={() => setDismissed(true)}
                className="absolute top-3 right-3 text-zinc-500 hover:text-zinc-300"
            >
                <X className="w-4 h-4" />
            </button>

            <div className="flex items-center gap-3">
                <div className="p-2 rounded-xl bg-brand-500/20">
                    <Brain className="w-5 h-5 text-brand-400" />
                </div>
                <div>
                    <h3 className="font-semibold text-white text-sm">Calibrate the Ranker to your style</h3>
                    <p className="text-xs text-zinc-400">
                        Analyze your top {estimate.batch_size} shorts to enrich the IC Cascade
                    </p>
                </div>
            </div>

            <p className="text-sm text-zinc-400 leading-relaxed">
                We'll send the titles and performance metrics of your top-performing shorts
                to <span className="text-white font-medium">{estimate.model}</span> and extract
                the recurring hooks, emotional patterns, and duration signatures of your
                best-performing content. Those patterns become anonymous signals in the IC
                Cascade — making the Ranker sharper for you <em>and</em> for every creator in your niche.
            </p>

            <div className="grid grid-cols-3 gap-3 text-xs">
                <div className="px-3 py-2 rounded-lg bg-white/5 border border-white/10">
                    <div className="text-[10px] uppercase tracking-widest text-zinc-500">Shorts analyzed</div>
                    <div className="text-white font-semibold text-lg">{estimate.batch_size}</div>
                </div>
                <div className="px-3 py-2 rounded-lg bg-white/5 border border-white/10">
                    <div className="text-[10px] uppercase tracking-widest text-zinc-500">Est. cost</div>
                    <div className="text-white font-semibold text-lg">${estimate.cost_usd_est.toFixed(2)}</div>
                </div>
                <div className="px-3 py-2 rounded-lg bg-white/5 border border-white/10">
                    <div className="text-[10px] uppercase tracking-widest text-zinc-500">Billed to</div>
                    <div className="text-white font-semibold text-sm mt-1">Your Anthropic key</div>
                </div>
            </div>

            <button
                onClick={handleRun}
                disabled={running}
                className="w-full flex items-center justify-center gap-2 rounded-xl bg-brand-500 hover:bg-brand-400 disabled:opacity-60 text-white font-medium text-sm py-3 transition-colors"
            >
                {running ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
                {running ? 'Extracting patterns…' : `Run extraction (~$${estimate.cost_usd_est.toFixed(2)})`}
            </button>

            <button
                onClick={() => setDismissed(true)}
                className="w-full text-xs text-zinc-500 hover:text-zinc-400 text-center"
            >
                Maybe later
            </button>
        </div>
    );
};
