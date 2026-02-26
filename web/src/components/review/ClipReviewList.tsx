import React, { useEffect, useState } from 'react';
import { ClipReviewCard } from './ClipReviewCard';
import { ClipsApi, type JobResponse, type Clip } from '../../lib/api';
import { ArrowLeft, Loader2, VideoOff } from 'lucide-react';
import toast from 'react-hot-toast';

export const ClipReviewList: React.FC = () => {
    const [job, setJob] = useState<JobResponse | null>(null);
    const [loading, setLoading] = useState(true);
    const [jobId, setJobId] = useState<string | null>(null);

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
    }, []);

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
        try {
            await ClipsApi.approveClip(clipId);
            toast.success('Clip approved and saved to output folder!');

            // Update local state to reflect approval
            if (job) {
                const updatedClips = job.clips.map(c =>
                    c.id === clipId ? { ...c, status: 'approved' } : c
                );
                setJob({ ...job, clips: updatedClips });
            }
        } catch (error: any) {
            toast.error(error.message || 'Failed to approve clip');
        }
    };

    const handleReject = async (clipId: number) => {
        try {
            // For MVP, rejecting might just remove it from the UI or call an endpoint
            // We'll simulate removal from UI for now since API deletion isn't fully spec'd
            if (job) {
                const updatedClips = job.clips.filter(c => c.id !== clipId);
                setJob({ ...job, clips: updatedClips });
            }
            toast.success('Clip rejected');
        } catch (error: any) {
            toast.error('Failed to reject clip');
        }
    };

    if (loading) {
        return (
            <div className="flex flex-col items-center justify-center h-[60vh]">
                <Loader2 className="w-10 h-10 text-brand-500 animate-spin mb-4" />
                <p className="text-zinc-400">Loading generated clips...</p>
            </div>
        );
    }

    if (!jobId) {
        return (
            <div className="text-center py-20 bg-zinc-900/40 border border-white/5 rounded-2xl max-w-2xl mx-auto mt-10">
                <VideoOff className="w-12 h-12 text-zinc-600 mx-auto mb-4" />
                <h3 className="text-lg font-medium text-zinc-300">No Job Selected</h3>
                <p className="text-sm text-zinc-500 mt-2">
                    Please process an episode from the Dashboard first to review clips.
                </p>
                <a
                    href="/dashboard"
                    className="inline-flex items-center gap-2 px-6 py-2.5 bg-brand-600 hover:bg-brand-500 text-white rounded-xl font-medium transition-colors mt-6"
                >
                    <ArrowLeft className="w-4 h-4" /> Return to Dashboard
                </a>
            </div>
        );
    }

    const clips = job?.clips || [];

    return (
        <div className="w-full">
            <div className="flex items-center justify-between mb-8">
                <div>
                    <a href="/dashboard" className="text-brand-400 text-sm flex items-center gap-1 hover:text-brand-300 mb-2 w-max transition-colors">
                        <ArrowLeft className="w-4 h-4" /> Back to Dashboard
                    </a>
                    <h2 className="text-3xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-white to-zinc-400">
                        Review Clips
                    </h2>
                    <p className="text-zinc-500 mt-1">
                        Job ID: <span className="font-mono">{jobId}</span> • {clips.length} clips generated
                    </p>
                </div>
            </div>

            {clips.length === 0 ? (
                <div className="text-center py-20 bg-zinc-900/40 border border-white/5 rounded-2xl">
                    <p className="text-zinc-400">No clips found for this job. It might have failed or not generated any results.</p>
                </div>
            ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
                    {clips.map(clip => (
                        <ClipReviewCard
                            key={clip.id}
                            clip={clip}
                            jobId={jobId}
                            onApprove={handleApprove}
                            onReject={handleReject}
                        />
                    ))}
                </div>
            )}
        </div>
    );
};
