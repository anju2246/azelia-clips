import React, { useEffect, useState } from 'react';
import { ClipReviewCard } from './ClipReviewCard';
import { ClipPlayerModal } from './ClipPlayerModal';
import { RejectedClipsList } from './RejectedClipsList';
import { ClipsApi, type JobResponse, type Clip, type EpisodeResponse } from '../../lib/api';
import { ArrowLeft, Loader2, VideoOff, Trash2 } from 'lucide-react';
import toast from 'react-hot-toast';

export const ClipReviewList: React.FC = () => {
    const [job, setJob] = useState<JobResponse | null>(null);
    const [loading, setLoading] = useState(true);
    const [jobId, setJobId] = useState<string | null>(null);
    const [history, setHistory] = useState<any[]>([]);
    const [loadingHistory, setLoadingHistory] = useState(false);
    const [selectedClipIndex, setSelectedClipIndex] = useState<number | null>(null);
    const [trashVersion, setTrashVersion] = useState(0);
    const [showTrash, setShowTrash] = useState(false);
    const [selectedRejectedIndex, setSelectedRejectedIndex] = useState<number | null>(null);
    const [rejectedClips, setRejectedClips] = useState<any[]>([]);

    useEffect(() => {
        // Parse jobId from URL query parameters (e.g., ?job=12345)
        const urlParams = new URLSearchParams(window.location.search);
        const id = urlParams.get('job');

        if (id) {
            setJobId(id);
            loadJob(id);
        } else {
            setLoading(false);
        }
        
        loadHistory();
    }, []);

    const loadHistory = async () => {
        setLoadingHistory(true);
        try {
            const data = await ClipsApi.getHistory();
            // Only show history items that actually have clips generated
            setHistory(data.filter(item => item.has_clips));
        } catch (error) {
            console.error('Failed to load history', error);
        } finally {
            setLoadingHistory(false);
        }
    };

    const loadJob = async (id: string) => {
        setLoading(true);
        try {
            const data = await ClipsApi.getJob(id);
            setJob(data);
        } catch (error) {
            toast.error('Failed to load generated clips');
        } finally {
            setLoading(false);
        }
    };

    const handleApprove = async (clipId: number) => {
        if (!job || !jobId) return;
        const clip = job.clips.find(c => c.id === clipId);
        if (!clip) return;

        try {
            await ClipsApi.approveClip(jobId, clip.filename);
            toast.success('Clip aprobado ✓');

            // Update local state
            const updatedClips = job.clips.map(c =>
                c.id === clipId ? { ...c, status: 'approved' } : c
            );
            setJob({ ...job, clips: updatedClips });
        } catch (error: any) {
            toast.error(error.message || 'Error al aprobar clip');
        }
    };

    const handleReject = async (clipId: number) => {
        if (!job || !jobId) return;
        const clip = job.clips.find(c => c.id === clipId);
        if (!clip) return;

        try {
            await ClipsApi.rejectClip(jobId, clip.filename);

            // Remove from UI
            const updatedClips = job.clips.filter(c => c.id !== clipId);
            setJob({ ...job, clips: updatedClips });
            // If we're in modal, adjust index
            if (selectedClipIndex !== null && selectedClipIndex >= updatedClips.length) {
                setSelectedClipIndex(updatedClips.length > 0 ? updatedClips.length - 1 : null);
            }
            setTrashVersion(v => v + 1);
            toast.success('Clip rejected (will be deleted in 30 days)');
        } catch (error: any) {
            toast.error(error.message || 'Error rejecting clip');
        }
    };

    const handleRejectedClipClick = (index: number, clipsList: any[]) => {
        setRejectedClips(clipsList);
        setSelectedRejectedIndex(index);
    };

    if (loading) {
        return (
            <div className="flex flex-col items-center justify-center h-[60vh]">
                <Loader2 className="w-10 h-10 text-brand-500 animate-spin mb-4" />
                <p className="text-zinc-400">Loading generated clips...</p>
            </div>
        );
    }
    const clips = job?.clips || [];

    return (
        <div className="w-full">
            {jobId && (
                <>
                    <div className="flex items-center justify-between mb-8">
                        <div>
                            <button
                                onClick={() => {
                                    const url = new URL(window.location.href);
                                    url.searchParams.delete('job');
                                    window.history.pushState({}, '', url.toString());
                                    setJobId(null);
                                    setJob(null);
                                    setSelectedClipIndex(null);
                                    setShowTrash(false);
                                }}
                                className="text-brand-400 text-sm flex items-center gap-1 hover:text-brand-300 mb-2 w-max transition-colors"
                            >
                                <ArrowLeft className="w-4 h-4" /> Volver al Historial
                            </button>
                            <h2 className="text-3xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-white to-zinc-400">
                                Review Clips
                            </h2>
                            <p className="text-zinc-500 mt-1">
                                {clips.length} clips generados
                            </p>
                        </div>
                        
                        <button
                            onClick={() => setShowTrash(!showTrash)}
                            className={`flex items-center gap-2 px-4 py-2 rounded-xl transition-all duration-300 border font-medium ${
                                showTrash 
                                    ? 'bg-zinc-800 text-zinc-200 border-zinc-700 hover:bg-zinc-700 hover:text-white' 
                                    : 'bg-zinc-900/50 border-white/10 text-zinc-300 hover:text-red-400 hover:border-red-500/30 hover:bg-red-500/10'
                            }`}
                        >
                            {showTrash ? <ArrowLeft className="w-4 h-4" /> : <Trash2 className="w-4 h-4" />}
                            {showTrash ? 'Volver a Clips' : 'Ver Papelera'}
                        </button>
                    </div>

                    {showTrash ? (
                        <div className="bg-zinc-900/30 border border-red-500/10 rounded-3xl p-6">
                            <RejectedClipsList 
                                jobId={jobId} 
                                onRestored={() => loadJob(jobId)} 
                                onClipClick={handleRejectedClipClick}
                                version={trashVersion} 
                            />
                        </div>
                    ) : clips.length === 0 ? (
                        <div className="text-center py-20 bg-zinc-900/40 border border-white/5 rounded-2xl">
                            <p className="text-zinc-400">No clips found for this job. It might have failed or not generated any results.</p>
                        </div>
                    ) : (
                        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
                            {clips.map((clip, index) => (
                                <ClipReviewCard
                                    key={clip.id}
                                    clip={clip}
                                    jobId={jobId}
                                    onApprove={handleApprove}
                                    onReject={handleReject}
                                    onClick={() => setSelectedClipIndex(index)}
                                />
                            ))}
                        </div>
                    )}
                </>
            )}

            {/* History Section */}
            {(!jobId || history.length > 0) && (
                <div className={jobId ? "mt-16 pt-8 border-t border-white/5" : ""}>
                    <h3 className="text-xl font-bold text-white mb-6">Historial de Clips</h3>
                    
                    {loadingHistory ? (
                        <div className="flex justify-center items-center h-32">
                            <Loader2 className="w-6 h-6 text-brand-500 animate-spin" />
                        </div>
                    ) : history.length > 0 ? (
                        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
                            {history.map((item) => (
                                <div
                                    key={item.id}
                                    onClick={() => {
                                        // The job ID is the unique ID for the processing job
                                        const url = new URL(window.location.href);
                                        url.searchParams.set('job', item.id);
                                        window.history.pushState({}, '', url.toString());
                                        setJobId(item.id);
                                        loadJob(item.id);
                                    }}
                                    className="group cursor-pointer glass-card rounded-2xl p-5 border border-white/5 bg-zinc-900/40 hover:bg-zinc-900/80 transition-all duration-300 hover:-translate-y-1 hover:border-brand-500/30 flex flex-col"
                                >
                                    <div className="flex justify-between items-start mb-4">
                                        <div className="bg-brand-500/10 text-brand-400 text-xs font-bold px-2 py-1 rounded-md">
                                            {item.type === 'episode' ? `EP ${item.number.toString().padStart(3, '0')}` : 'Ad-Hoc'}
                                        </div>
                                        <div className="flex items-center gap-1 text-zinc-400 text-xs">
                                            {new Date(item.created_at).toLocaleDateString()}
                                        </div>
                                    </div>

                                    <h3 className="font-semibold text-lg text-zinc-200 mb-2 line-clamp-2" title={item.filename}>
                                        {item.filename}
                                    </h3>
                                    <p className="text-xs text-zinc-500 mb-4">
                                        {item.clips_generated} clips extracted
                                    </p>

                                    <div className="mt-auto pt-4">
                                        <div className="w-full text-center py-2 rounded-lg bg-white/5 group-hover:bg-white/10 text-white border border-white/10 text-sm font-medium transition-colors">
                                            Ver Clips Generados
                                        </div>
                                    </div>
                                </div>
                            ))}
                        </div>
                    ) : !jobId ? (
                        <div className="text-center py-20 bg-zinc-900/40 border border-white/5 rounded-2xl max-w-2xl mx-auto mt-10">
                            <VideoOff className="w-12 h-12 text-zinc-600 mx-auto mb-4" />
                            <h3 className="text-lg font-medium text-zinc-300">Sin historial</h3>
                            <p className="text-sm text-zinc-500 mt-2">
                                No tienes clips procesados. Ve al Dashboard para procesar un video o episodio.
                            </p>
                            <a
                                href="/dashboard"
                                className="inline-flex items-center gap-2 px-6 py-2.5 bg-brand-600 hover:bg-brand-500 text-white rounded-xl font-medium transition-colors mt-6"
                            >
                                <ArrowLeft className="w-4 h-4" /> Volver al Dashboard
                            </a>
                        </div>
                    ) : null}
                </div>
            )}

            {/* Modal */}
            {(selectedClipIndex !== null || selectedRejectedIndex !== null) && jobId && (
                <ClipPlayerModal
                    clips={selectedRejectedIndex !== null ? rejectedClips : (job?.clips || [])}
                    initialClipIndex={selectedRejectedIndex !== null ? selectedRejectedIndex : (selectedClipIndex || 0)}
                    jobId={jobId}
                    onClose={() => {
                        setSelectedClipIndex(null);
                        setSelectedRejectedIndex(null);
                    }}
                    onApprove={async (id) => {
                        if (selectedRejectedIndex !== null) {
                            // If it's a rejected clip, Approve = Restore
                            const clip = rejectedClips[selectedRejectedIndex];
                            if (clip) {
                                try {
                                    await ClipsApi.restoreClip(jobId, clip.filename);
                                    toast.success('Clip restaurado');
                                    loadJob(jobId);
                                    setTrashVersion(v => v + 1);
                                    setSelectedRejectedIndex(null);
                                } catch (e) {
                                    toast.error('Error al restaurar');
                                }
                            }
                        } else {
                            handleApprove(id);
                        }
                    }}
                    onReject={handleReject}
                />
            )}
        </div>
    );
};
