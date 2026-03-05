import React, { useState, useEffect } from 'react';
import { UploadZone } from './UploadZone';
import { LibraryView } from './LibraryView';
import { LiveProcessingWidget } from './LiveProcessingWidget';
import { YouTubeNudge } from '../analytics/YouTubeNudge';
import { ClipsApi } from '../../lib/api';
import toast from 'react-hot-toast';

const JOB_STORAGE_KEY = 'celia_active_job_id';

export const DashboardController: React.FC = () => {
    const [activeJobId, setActiveJobId] = useState<string | null>(() => {
        // Recover active job from localStorage on mount
        if (typeof window !== 'undefined') {
            return localStorage.getItem(JOB_STORAGE_KEY);
        }
        return null;
    });

    // Check if recovered job is still active
    useEffect(() => {
        if (!activeJobId) return;

        const checkJob = async () => {
            try {
                const job = await ClipsApi.getJob(activeJobId);
                if (job.status === 'completed' || job.status === 'error' || job.status === 'failed') {
                    // Job already finished — clear it
                    clearActiveJob();
                    if (job.status === 'completed') {
                        toast.success(`Previous job completed: ${job.message}`);
                    } else {
                        toast.error(`Previous job failed: ${job.error || job.message}`);
                    }
                }
                // If still running, the LiveProcessingWidget will take over
            } catch {
                // Job not found — clear stale reference
                clearActiveJob();
            }
        };

        checkJob();
    }, []);

    const setAndPersistJobId = (jobId: string) => {
        setActiveJobId(jobId);
        localStorage.setItem(JOB_STORAGE_KEY, jobId);
    };

    const clearActiveJob = () => {
        setActiveJobId(null);
        localStorage.removeItem(JOB_STORAGE_KEY);
    };

    const handleProcessEpisode = async (episodeNum: number) => {
        const loadingToast = toast.loading('Starting episode processing...');
        try {
            const response = await ClipsApi.processEpisode(episodeNum, {
                min_duration: 30,
                max_duration: 90,
                min_score: 70,
                subtitle_style: 'highlight',
                transcription_source: 'local_whisper'
            });
            toast.success('Episode processing started!', { id: loadingToast });
            setAndPersistJobId(response.id);
        } catch (error: any) {
            console.error(error);
            toast.error(error.message || 'Failed to process episode', { id: loadingToast });
        }
    };

    // If a job is active, show the live processing widget
    if (activeJobId) {
        return (
            <LiveProcessingWidget
                jobId={activeJobId}
                onJobComplete={() => {
                    // Keep showing so user can click "Review Clips"
                }}
                onCancel={() => clearActiveJob()}
            />
        );
    }

    return (
        <div className="flex flex-col gap-12">
            <YouTubeNudge />
            <LibraryView onProcessEpisode={handleProcessEpisode} />

            <div className="relative">
                <div className="absolute inset-0 flex items-center" aria-hidden="true">
                    <div className="w-full border-t border-white/5"></div>
                </div>
                <div className="relative flex justify-center">
                    <span className="bg-zinc-950 px-4 text-sm text-zinc-500 uppercase tracking-widest">Or upload manually</span>
                </div>
            </div>

            <UploadZone
                onJobStarted={(jobId) => setAndPersistJobId(jobId)}
            />
        </div>
    );
};
