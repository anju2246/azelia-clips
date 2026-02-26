import React, { useState } from 'react';
import { UploadZone } from './UploadZone';
import { LibraryView } from './LibraryView';
import { LiveProcessingWidget } from './LiveProcessingWidget';
import { ClipsApi } from '../../lib/api';
import toast from 'react-hot-toast';

export const DashboardController: React.FC = () => {
    const [activeJobId, setActiveJobId] = useState<string | null>(null);

    const handleProcessEpisode = async (episodeNum: number) => {
        const loadingToast = toast.loading('Starting episode processing...');
        try {
            // Use default config for library episodes
            const response = await ClipsApi.processEpisode(episodeNum, {
                min_duration: 30,
                max_duration: 90,
                min_score: 70,
                subtitle_style: 'highlight',
                transcription_source: 'local_whisper'
            });
            toast.success('Episode processing started!', { id: loadingToast });
            setActiveJobId(response.id);
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
                    // Keep showing it so they can click "Review Clips", or handle state change
                }}
                onCancel={() => setActiveJobId(null)}
            />
        );
    }

    return (
        <div className="flex flex-col gap-12">
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
                onJobStarted={(jobId) => setActiveJobId(jobId)}
            />
        </div>
    );
};
