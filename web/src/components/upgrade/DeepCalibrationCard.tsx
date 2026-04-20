import React, { useEffect, useState, useRef } from 'react';
import { Telescope, Loader2, Sparkles, CheckCircle2, X, AlertCircle } from 'lucide-react';
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
    available_episodes: number;
    podcast_dir: string | null;
    cost_usd_est?: number;
    per_episode_avg_usd?: number;
    model?: string;
    note?: string;
}

interface JobStatus {
    status: 'running' | 'complete' | 'failed';
    total: number;
    processed: number;
    signals_created: number;
    errors: string[];
    cost_actual_usd: number;
}

/**
 * DeepCalibrationCard — opt-in, expensive-by-design. Analyzes the user's
 * full historical episode transcripts and extracts structural patterns
 * into the IC Cascade (source_type='creator_deep').
 */
export const DeepCalibrationCard: React.FC = () => {
    const [estimate, setEstimate] = useState<Estimate | null>(null);
    const [loading, setLoading] = useState(true);
    const [jobId, setJobId] = useState<string | null>(null);
    const [job, setJob] = useState<JobStatus | null>(null);
    const [dismissed, setDismissed] = useState(false);
    const pollRef = useRef<number | null>(null);

    useEffect(() => {
        fetchWithAuth('/analytics/episodes/deep-calibration/estimate')
            .then(r => r.ok ? r.json() : null)
            .then(d => { if (d) setEstimate(d); })
            .catch(() => {})
            .finally(() => setLoading(false));
    }, []);

    // Poll job every 3s while running.
    useEffect(() => {
        if (!jobId || job?.status === 'complete' || job?.status === 'failed') return;
        pollRef.current = window.setInterval(async () => {
            try {
                const res = await fetchWithAuth(`/analytics/episodes/deep-calibration/status/${jobId}`);
                if (res.ok) {
                    const data: JobStatus = await res.json();
                    setJob(data);
                    if (data.status === 'complete' || data.status === 'failed') {
                        if (pollRef.current) window.clearInterval(pollRef.current);
                        if (data.status === 'complete') {
                            toast.success(`Deep calibration done — ${data.signals_created} signals added`, { icon: '🔭' });
                        } else {
                            toast.error('Deep calibration failed');
                        }
                    }
                }
            } catch (e) { /* keep polling */ }
        }, 3000);
        return () => { if (pollRef.current) window.clearInterval(pollRef.current); };
    }, [jobId, job?.status]);

    const handleRun = async () => {
        try {
            const res = await fetchWithAuth('/analytics/episodes/deep-calibration', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ confirmed: true, max_episodes: Math.min(20, estimate?.available_episodes ?? 0) }),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `Error ${res.status}`);
            }
            const data = await res.json();
            setJobId(data.job_id);
            setJob({ status: 'running', total: data.episodes_queued, processed: 0, signals_created: 0, errors: [], cost_actual_usd: 0 });
        } catch (e: any) {
            toast.error(e.message || 'Could not start deep calibration');
        }
    };

    if (dismissed || loading) return null;
    if (!estimate || estimate.available_episodes === 0) return null;

    if (job) {
        const pct = job.total ? Math.round((job.processed / job.total) * 100) : 0;
        return (
            <div className="rounded-2xl border border-arctic-500/30 bg-gradient-to-br from-arctic-500/10 to-zinc-900/80 p-6 space-y-4">
                <div className="flex items-center gap-3">
                    <div className="p-2 rounded-xl bg-arctic-500/20">
                        {job.status === 'complete' ? (
                            <CheckCircle2 className="w-5 h-5 text-green-400" />
                        ) : job.status === 'failed' ? (
                            <AlertCircle className="w-5 h-5 text-red-400" />
                        ) : (
                            <Loader2 className="w-5 h-5 text-arctic-400 animate-spin" />
                        )}
                    </div>
                    <div className="flex-1">
                        <h3 className="font-semibold text-white text-sm">
                            Deep calibration — {job.status === 'complete' ? 'done' : job.status === 'failed' ? 'failed' : 'running'}
                        </h3>
                        <p className="text-xs text-zinc-400">
                            {job.processed}/{job.total} episodes · {job.signals_created} signals · ${job.cost_actual_usd.toFixed(3)} so far
                        </p>
                    </div>
                </div>

                {job.status === 'running' && (
                    <div className="w-full h-1.5 rounded-full bg-white/5 overflow-hidden">
                        <div
                            className="h-full bg-arctic-500 transition-all"
                            style={{ width: `${pct}%` }}
                        />
                    </div>
                )}

                {job.errors && job.errors.length > 0 && (
                    <details className="text-xs text-zinc-500">
                        <summary className="cursor-pointer">{job.errors.length} warnings</summary>
                        <ul className="pt-2 space-y-0.5 font-mono">
                            {job.errors.slice(0, 5).map((e, i) => (<li key={i}>· {e}</li>))}
                        </ul>
                    </details>
                )}
            </div>
        );
    }

    return (
        <div className="rounded-2xl border border-arctic-500/30 bg-gradient-to-br from-arctic-500/10 to-zinc-900/80 p-6 space-y-5 relative">
            <button
                aria-label="Dismiss"
                onClick={() => setDismissed(true)}
                className="absolute top-3 right-3 text-zinc-500 hover:text-zinc-300"
            >
                <X className="w-4 h-4" />
            </button>

            <div className="flex items-center gap-3">
                <div className="p-2 rounded-xl bg-arctic-500/20">
                    <Telescope className="w-5 h-5 text-arctic-400" />
                </div>
                <div>
                    <h3 className="font-semibold text-white text-sm">Deep calibration (optional)</h3>
                    <p className="text-xs text-zinc-400">
                        Analyze your full episode transcripts — deeper patterns than shorts alone
                    </p>
                </div>
            </div>

            <p className="text-sm text-zinc-400 leading-relaxed">
                We'll send your episode transcripts to <span className="text-white font-medium">{estimate.model}</span>, extract
                structural patterns (topic arcs, pacing, emotional segmentation, hook cadence), and contribute
                them as anonymous signals to the IC Cascade. More thorough than
                Creator Signals — 10x more expensive.
            </p>

            <div className="grid grid-cols-3 gap-3 text-xs">
                <div className="px-3 py-2 rounded-lg bg-white/5 border border-white/10">
                    <div className="text-[10px] uppercase tracking-widest text-zinc-500">Episodes</div>
                    <div className="text-white font-semibold text-lg">{Math.min(20, estimate.available_episodes)}</div>
                </div>
                <div className="px-3 py-2 rounded-lg bg-white/5 border border-white/10">
                    <div className="text-[10px] uppercase tracking-widest text-zinc-500">Est. cost</div>
                    <div className="text-white font-semibold text-lg">${(estimate.cost_usd_est ?? 0).toFixed(2)}</div>
                </div>
                <div className="px-3 py-2 rounded-lg bg-white/5 border border-white/10">
                    <div className="text-[10px] uppercase tracking-widest text-zinc-500">Avg / episode</div>
                    <div className="text-white font-semibold text-sm mt-1">${(estimate.per_episode_avg_usd ?? 0).toFixed(3)}</div>
                </div>
            </div>

            <button
                onClick={handleRun}
                className="w-full flex items-center justify-center gap-2 rounded-xl bg-arctic-500 hover:bg-arctic-400 text-white font-medium text-sm py-3 transition-colors"
            >
                <Sparkles className="w-4 h-4" />
                Run deep calibration (~${(estimate.cost_usd_est ?? 0).toFixed(2)})
            </button>

            <button
                onClick={() => setDismissed(true)}
                className="w-full text-xs text-zinc-500 hover:text-zinc-400 text-center"
            >
                Not now
            </button>
        </div>
    );
};
