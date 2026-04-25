import React, { useEffect, useState } from 'react';
import { Loader2, Sparkles, TrendingUp, AlertTriangle, Tag } from 'lucide-react';
import { supabase } from '../../lib/supabase';
import { CreatorSignalsCard } from '../upgrade/CreatorSignalsCard';

interface TopHook {
    hook_type: string;
    emotional_charge?: string | null;
    duration_bucket?: string | null;
    performance_premium: number;
    confidence: number;
    sample_size: number;
    score: number;
}

interface TopicPerf {
    topic: string;
    avg_performance_premium: number;
    sample_size: number;
}

interface AvoidPattern {
    hook_type?: string | null;
    emotional_charge?: string | null;
    performance_premium: number;
    confidence: number;
    sample_size: number;
}

interface RetentionPattern {
    signal_type: string;
    pattern: Record<string, any>;
    performance_premium: number;
    confidence: number;
}

interface Payload {
    empty: boolean;
    reason?: string;
    signal_count?: number;
    top_hooks?: TopHook[];
    topic_performance?: TopicPerf[];
    avoid_patterns?: AvoidPattern[];
    retention_patterns?: RetentionPattern[];
}

const API_BASE = (import.meta.env?.PUBLIC_API_URL as string) || '/api';

function fmtPct(n: number) { return `${Math.round(n * 100)}%`; }

export const MyContentIntelligence: React.FC = () => {
    const [data, setData] = useState<Payload | null>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => { load(); }, []);

    const load = async () => {
        try {
            const { data: session } = await supabase.auth.getSession();
            const token = session?.session?.access_token;
            if (!token) { setLoading(false); return; }
            const res = await fetch(`${API_BASE}/analytics/my-content-intelligence`, {
                headers: { Authorization: `Bearer ${token}` },
            });
            if (res.ok) {
                setData(await res.json());
            }
        } catch { /* empty state */ }
        finally { setLoading(false); }
    };

    if (loading) {
        return (
            <div className="flex justify-center py-8"><Loader2 className="w-6 h-6 text-brand-500 animate-spin" /></div>
        );
    }

    // No signals yet → show the extraction card as the primary action.
    if (!data || data.empty) {
        return (
            <div className="space-y-4">
                <CreatorSignalsCard />
                <p className="text-sm text-zinc-500">
                    Run <strong>Extract Creator Signals</strong> above to see what patterns work best in your podcast. Your signals never leave your cohort.
                </p>
            </div>
        );
    }

    return (
        <div className="space-y-6">
            {/* Trigger card — always available so user can refresh patterns. */}
            <CreatorSignalsCard />

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                {/* Top Hooks */}
                <div className="bg-zinc-900/40 border border-white/5 rounded-2xl p-6">
                    <div className="flex items-center gap-2 mb-4">
                        <Sparkles className="w-4 h-4 text-brand-400" />
                        <h4 className="text-sm font-medium text-zinc-200 uppercase tracking-widest">Top hooks for your audience</h4>
                    </div>
                    {data.top_hooks && data.top_hooks.length > 0 ? (
                        <div className="space-y-3">
                            {data.top_hooks.map((h, i) => (
                                <div key={`${h.hook_type}-${i}`} className="p-3 bg-black/30 rounded-xl border border-white/5">
                                    <div className="flex items-center justify-between mb-1">
                                        <span className="text-white font-medium text-sm capitalize">{h.hook_type.replace(/_/g, ' ')}</span>
                                        <span className="text-xs font-mono text-emerald-400">×{h.performance_premium.toFixed(2)}</span>
                                    </div>
                                    <div className="flex items-center gap-3 text-[11px] text-zinc-500">
                                        {h.emotional_charge && <span className="capitalize">{h.emotional_charge}</span>}
                                        {h.duration_bucket && <span>{h.duration_bucket}</span>}
                                        <span>conf {fmtPct(h.confidence)}</span>
                                        <span>n={h.sample_size}</span>
                                    </div>
                                </div>
                            ))}
                        </div>
                    ) : (
                        <p className="text-sm text-zinc-500">Not enough data yet. Process more shorts.</p>
                    )}
                </div>

                {/* Topic Performance */}
                <div className="bg-zinc-900/40 border border-white/5 rounded-2xl p-6">
                    <div className="flex items-center gap-2 mb-4">
                        <Tag className="w-4 h-4 text-blue-400" />
                        <h4 className="text-sm font-medium text-zinc-200 uppercase tracking-widest">Topics that perform</h4>
                    </div>
                    {data.topic_performance && data.topic_performance.length > 0 ? (
                        <div className="space-y-3">
                            {data.topic_performance.map(t => (
                                <div key={t.topic} className="flex items-center justify-between">
                                    <span className="text-sm text-zinc-300 capitalize">{t.topic.replace(/_/g, ' ')}</span>
                                    <div className="flex items-center gap-2">
                                        <span className="text-[10px] text-zinc-600">n={t.sample_size}</span>
                                        <span className={`text-xs font-mono ${t.avg_performance_premium >= 1 ? 'text-emerald-400' : 'text-zinc-500'}`}>
                                            ×{t.avg_performance_premium.toFixed(2)}
                                        </span>
                                    </div>
                                </div>
                            ))}
                        </div>
                    ) : (
                        <p className="text-sm text-zinc-500">No topic patterns yet.</p>
                    )}
                </div>
            </div>

            {/* Avoid */}
            {data.avoid_patterns && data.avoid_patterns.length > 0 && (
                <div className="bg-amber-500/5 border border-amber-500/20 rounded-2xl p-6">
                    <div className="flex items-center gap-2 mb-3">
                        <AlertTriangle className="w-4 h-4 text-amber-400" />
                        <h4 className="text-sm font-medium text-amber-300 uppercase tracking-widest">Patterns to avoid</h4>
                    </div>
                    <p className="text-xs text-amber-400/70 mb-4">These underperformed vs. your own median ({data.signal_count} signals analyzed).</p>
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                        {data.avoid_patterns.map((a, i) => (
                            <div key={i} className="p-3 bg-black/30 border border-white/5 rounded-xl">
                                <p className="text-sm text-white font-medium capitalize">{(a.hook_type || 'generic').replace(/_/g, ' ')}</p>
                                {a.emotional_charge && <p className="text-[11px] text-zinc-500 capitalize">{a.emotional_charge}</p>}
                                <p className="text-[11px] font-mono text-amber-400 mt-1">×{a.performance_premium.toFixed(2)} · conf {fmtPct(a.confidence)}</p>
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* Retention */}
            {data.retention_patterns && data.retention_patterns.length > 0 && (
                <div className="bg-zinc-900/40 border border-white/5 rounded-2xl p-6">
                    <div className="flex items-center gap-2 mb-4">
                        <TrendingUp className="w-4 h-4 text-emerald-400" />
                        <h4 className="text-sm font-medium text-zinc-200 uppercase tracking-widest">Retention signals</h4>
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                        {data.retention_patterns.map((r, i) => (
                            <div key={i} className="p-3 bg-black/30 rounded-xl border border-white/5">
                                <p className="text-sm text-white capitalize">{r.signal_type.replace(/_/g, ' ')}</p>
                                <p className="text-[11px] font-mono text-emerald-400 mt-1">×{r.performance_premium.toFixed(2)} · conf {fmtPct(r.confidence)}</p>
                            </div>
                        ))}
                    </div>
                </div>
            )}
        </div>
    );
};
