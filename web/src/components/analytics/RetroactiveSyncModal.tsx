import React, { useState, useEffect } from 'react';
import { Sparkles, BrainCircuit, Loader2, ArrowRight, ShieldAlert, CheckCircle2 } from 'lucide-react';
import { supabase } from '../../lib/supabase';

interface RetroactiveSyncModalProps {
    isOpen: boolean;
    onClose: () => void;
    onSuccess?: (jobId: string) => void;
}

export const RetroactiveSyncModal: React.FC<RetroactiveSyncModalProps> = ({ isOpen, onClose, onSuccess }) => {
    const [loading, setLoading] = useState(false);
    const [estimate, setEstimate] = useState<any>(null);
    const [error, setError] = useState('');
    const [syncing, setSyncing] = useState(false);

    useEffect(() => {
        if (isOpen) {
            fetchEstimate();
        }
    }, [isOpen]);

    const fetchEstimate = async () => {
        setLoading(true);
        setError('');
        try {
            const { data: { session } } = await supabase.auth.getSession();
            const res = await fetch('/api/analytics/youtube/historical/estimate', {
                headers: {
                    'Authorization': session ? `Bearer ${session.access_token}` : ''
                }
            });
            
            if (!res.ok) throw new Error('Failed to fetch estimate');
            const data = await res.json();
            setEstimate(data);
            
            // Auto close if nothing to sync
            if (data.total_shorts === 0) {
                setTimeout(onClose, 2000);
            }
        } catch (err: any) {
            setError(err.message || 'Error calculando costos');
        } finally {
            setLoading(false);
        }
    };

    const handleSync = async () => {
        setSyncing(true);
        setError('');
        try {
            const { data: { session } } = await supabase.auth.getSession();
            const res = await fetch('/api/analytics/youtube/historical/sync', {
                method: 'POST',
                headers: {
                    'Authorization': session ? `Bearer ${session.access_token}` : ''
                }
            });
            
            if (!res.ok) throw new Error('Historical sync failed');
            
            const data = await res.json();
            const jobId = data.job_id;
            
            // Close modal immediately — progress will be tracked by the bubble
            onClose();
            if (onSuccess && jobId) {
                onSuccess(jobId);
            }
        } catch (err: any) {
            setError(err.message || 'Error processing videos');
            setSyncing(false);
        }
    };

    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <div className="absolute inset-0 bg-black/80 backdrop-blur-sm" onClick={syncing ? undefined : onClose} />
            
            <div className="relative bg-zinc-950 border border-brand-500/20 shadow-2xl shadow-brand-500/10 rounded-2xl w-full max-w-lg overflow-hidden animate-in zoom-in-95 duration-200">
                {/* Header Graphic */}
                <div className="absolute top-0 left-0 right-0 h-32 bg-gradient-to-b from-brand-600/20 to-transparent pointer-events-none" />
                
                <div className="p-8 relative">
                    <div className="w-12 h-12 bg-brand-500/20 text-brand-400 rounded-xl flex items-center justify-center mb-6 border border-brand-500/30">
                        <BrainCircuit className="w-7 h-7" />
                    </div>

                    <h2 className="text-2xl font-bold bg-gradient-to-r from-white to-zinc-400 bg-clip-text text-transparent mb-3">
                        Seed Intelligence from Day One
                    </h2>
                            <p className="text-zinc-400 text-sm leading-relaxed mb-6">
                                Azelia detected your past YouTube videos. Let's analyze your previous Shorts using <strong>{estimate?.model || 'your AI'}</strong> to immediately understand which <em>hooks</em> and formats resonate with your audience.
                            </p>

                            {loading ? (
                                <div className="flex flex-col items-center justify-center py-8 text-zinc-500 gap-3">
                                    <Loader2 className="w-8 h-8 animate-spin text-brand-500" />
                                    <span className="text-sm">Calculating tokens and costs in real time…</span>
                                </div>
                            ) : estimate?.total_shorts === 0 ? (
                                <div className="p-4 bg-zinc-900/50 rounded-xl border border-white/5 text-center">
                                    <p className="text-zinc-400 text-sm">No Shorts found in history or they've already been analyzed.</p>
                                </div>
                            ) : (
                                <div className="space-y-4">
                                    <div className="p-4 bg-black/40 border border-white/5 rounded-xl flex items-center justify-between">
                                        <div className="text-sm">
                                            <span className="text-zinc-400">Shorts to process:</span>
                                        </div>
                                        <div className="bg-brand-500/10 text-brand-400 font-bold px-3 py-1 rounded-lg text-sm border border-brand-500/20">
                                            {estimate?.total_shorts} videos
                                        </div>
                                    </div>

                                    <div className="p-4 bg-black/40 border border-white/5 rounded-xl">
                                        <div className="flex justify-between items-center mb-1">
                                            <span className="text-sm text-zinc-400">Estimated LLM cost:</span>
                                            <span className="text-lg font-mono text-emerald-400">${estimate?.estimated_cost_usd < 0.01 ? '< 0.01' : estimate?.estimated_cost_usd?.toFixed(2)} USD</span>
                                        </div>
                                        <div className="text-[10px] text-zinc-600 flex justify-between">
                                            <span>Model: {estimate?.model}</span>
                                            <span>${estimate?.cost_per_1M_tokens}/1M tokens</span>
                                        </div>
                                    </div>

                                    {error && (
                                        <div className="flex items-start gap-2 p-3 bg-red-500/10 border border-red-500/20 rounded-xl text-red-400 text-sm mt-4">
                                            <ShieldAlert className="w-4 h-4 mt-0.5 shrink-0" />
                                            <span>{error}</span>
                                        </div>
                                    )}

                                    <div className="pt-6 flex gap-3">
                                        <button
                                            onClick={onClose}
                                            disabled={syncing}
                                            className="px-6 py-3 rounded-xl border border-white/10 text-zinc-400 hover:text-white hover:bg-white/5 font-medium transition-all disabled:opacity-50"
                                        >
                                            Skip (start from zero)
                                        </button>
                                        <button
                                            onClick={handleSync}
                                            disabled={syncing}
                                            className="flex-1 bg-gradient-to-r from-brand-600 to-brand-500 text-white font-semibold py-3 rounded-xl hover:from-brand-500 transition-all shadow-lg shadow-brand-500/20 flex items-center justify-center gap-2 disabled:opacity-50"
                                        >
                                            {syncing ? (
                                                <><Loader2 className="w-5 h-5 animate-spin" /> Analyzing history…</>
                                            ) : (
                                                <><Sparkles className="w-5 h-5" /> Start analysis</>
                                            )}
                                        </button>
                                    </div>
                                    {syncing && (
                                        <p className="text-xs text-center text-zinc-500 mt-2">
                                            This may take a few minutes depending on downloads and the LLM.
                                        </p>
                                    )}
                                </div>
                            )}
                </div>
            </div>
        </div>
    );
}
