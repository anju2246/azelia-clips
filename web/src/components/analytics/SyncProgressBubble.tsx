import React, { useState, useEffect, useRef } from 'react';
import { BrainCircuit, CheckCircle2, XCircle, X, ChevronDown, ChevronUp } from 'lucide-react';
import { supabase } from '../../lib/supabase';

const API_BASE = (import.meta.env?.PUBLIC_API_URL as string) || '/api';

interface SyncProgressBubbleProps {
    jobId: string;
    onComplete?: () => void;
    onDismiss: () => void;
}

type JobStatus = 'pending' | 'processing' | 'completed' | 'error' | 'failed';

interface JobData {
    job_id: string;
    status: JobStatus;
    progress: number;
    message: string;
    error?: string;
}

export const SyncProgressBubble: React.FC<SyncProgressBubbleProps> = ({ jobId, onComplete, onDismiss }) => {
    const [job, setJob] = useState<JobData>({ job_id: jobId, status: 'pending', progress: 0, message: 'Iniciando...' });
    const [expanded, setExpanded] = useState(true);
    const [dismissed, setDismissed] = useState(false);
    const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

    useEffect(() => {
        const pollStatus = async () => {
            try {
                const headers: Record<string, string> = {};
                try {
                    const { data } = await supabase.auth.getSession();
                    if (data?.session?.access_token) {
                        headers['Authorization'] = `Bearer ${data.session.access_token}`;
                    }
                } catch { /* continue */ }

                const res = await fetch(`${API_BASE}/analytics/youtube/historical/status/${jobId}`, { headers });
                if (!res.ok) return;
                const data: JobData = await res.json();
                setJob(data);

                if (data.status === 'completed' || data.status === 'error' || data.status === 'failed') {
                    if (intervalRef.current) clearInterval(intervalRef.current);
                    if (data.status === 'completed' && onComplete) {
                        onComplete();
                    }
                    // Auto-dismiss success after 8 seconds
                    if (data.status === 'completed') {
                        setTimeout(() => setDismissed(true), 8000);
                    }
                }
            } catch {
                // Silently continue polling
            }
        };

        // Initial poll immediately
        pollStatus();
        // Then poll every 2 seconds
        intervalRef.current = setInterval(pollStatus, 2000);

        return () => {
            if (intervalRef.current) clearInterval(intervalRef.current);
        };
    }, [jobId]);

    if (dismissed) return null;

    const isFinished = job.status === 'completed' || job.status === 'error' || job.status === 'failed';
    const isError = job.status === 'error' || job.status === 'failed';

    return (
        <div
            className="fixed bottom-6 right-6 z-50 animate-in slide-in-from-bottom-4 duration-300"
            style={{ maxWidth: '380px', width: '100%' }}
        >
            <div className={`
                bg-zinc-950 border rounded-2xl shadow-2xl overflow-hidden transition-all duration-300
                ${isError ? 'border-red-500/30 shadow-red-500/10' : isFinished ? 'border-emerald-500/30 shadow-emerald-500/10' : 'border-brand-500/30 shadow-brand-500/10'}
            `}>
                {/* Header - always visible */}
                <div
                    className="flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-white/[0.02] transition-colors"
                    onClick={() => setExpanded(!expanded)}
                >
                    <div className={`
                        w-8 h-8 rounded-lg flex items-center justify-center shrink-0
                        ${isError ? 'bg-red-500/20 text-red-400' : isFinished ? 'bg-emerald-500/20 text-emerald-400' : 'bg-brand-500/20 text-brand-400'}
                    `}>
                        {isError ? (
                            <XCircle className="w-4.5 h-4.5" />
                        ) : isFinished ? (
                            <CheckCircle2 className="w-4.5 h-4.5" />
                        ) : (
                            <BrainCircuit className="w-4.5 h-4.5 animate-pulse" />
                        )}
                    </div>

                    <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-white truncate">
                            {isError ? 'Error en análisis' : isFinished ? '¡Análisis completo!' : 'Analizando histórico...'}
                        </p>
                        {!expanded && (
                            <p className="text-xs text-zinc-500 truncate">{job.message}</p>
                        )}
                    </div>

                    <div className="flex items-center gap-1.5">
                        {!isFinished && (
                            <span className="text-xs font-mono text-brand-400">{job.progress}%</span>
                        )}
                        {expanded ? (
                            <ChevronDown className="w-4 h-4 text-zinc-500" />
                        ) : (
                            <ChevronUp className="w-4 h-4 text-zinc-500" />
                        )}
                        <button
                            onClick={(e) => { e.stopPropagation(); setDismissed(true); onDismiss(); }}
                            className="ml-1 p-1 rounded-lg hover:bg-white/10 text-zinc-500 hover:text-white transition-colors"
                        >
                            <X className="w-3.5 h-3.5" />
                        </button>
                    </div>
                </div>

                {/* Progress bar */}
                {!isFinished && (
                    <div className="h-0.5 bg-zinc-800 mx-4">
                        <div
                            className="h-full bg-gradient-to-r from-brand-600 to-brand-400 rounded-full transition-all duration-700 ease-out"
                            style={{ width: `${job.progress}%` }}
                        />
                    </div>
                )}

                {/* Expanded detail */}
                {expanded && (
                    <div className="px-4 py-3 border-t border-white/5">
                        <p className="text-xs text-zinc-400 leading-relaxed">
                            {job.message}
                        </p>
                        {isError && job.error && (
                            <p className="text-xs text-red-400/80 mt-2 p-2 bg-red-500/5 rounded-lg border border-red-500/10">
                                {job.error.substring(0, 200)}
                            </p>
                        )}
                        {isFinished && !isError && (
                            <p className="text-xs text-emerald-400/80 mt-1">
                                Tu Dashboard de Inteligencia ha sido actualizado con los insights de tus videos.
                            </p>
                        )}
                    </div>
                )}
            </div>
        </div>
    );
};
