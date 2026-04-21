import React, { useState, useEffect } from 'react';
import { UploadZone } from './UploadZone';
import { LibraryView } from './LibraryView';
import { LiveProcessingWidget } from './LiveProcessingWidget';
import { MissingApiKeyModal } from './MissingApiKeyModal';
import { YouTubeNudge } from '../analytics/YouTubeNudge';
import { ProUpgradeCard } from '../upgrade/ProUpgradeCard';
import { CreatorSignalsCard } from '../upgrade/CreatorSignalsCard';
import { CreditsStatusBanner } from './CreditsStatusBanner';
import { ClipsApi, SettingsApi } from '../../lib/api';
import { supabase } from '../../lib/supabase';
import toast from 'react-hot-toast';

const API_BASE = (import.meta.env?.PUBLIC_API_URL as string) || '/api';

async function fetchWithAuth(endpoint: string, options: RequestInit = {}) {
    const headers = new Headers(options.headers || {});
    try {
        const { data } = await supabase.auth.getSession();
        if (data?.session?.access_token)
            headers.set('Authorization', `Bearer ${data.session.access_token}`);
    } catch (e) { /* continue */ }
    return fetch(`${API_BASE}${endpoint}`, { ...options, headers });
}

const JOB_STORAGE_KEY = 'azelia_active_job_id';

export const DashboardController: React.FC = () => {
    const [userTier, setUserTier] = useState<string | null>(null);
    const [youtubeConnected, setYoutubeConnected] = useState<boolean>(false);
    const [activeJobId, setActiveJobId] = useState<string | null>(() => {
        // Recover active job from localStorage on mount
        if (typeof window !== 'undefined') {
            return localStorage.getItem(JOB_STORAGE_KEY);
        }
        return null;
    });

    // API key guard state
    const [showApiKeyModal, setShowApiKeyModal] = useState(false);
    const [hasApiKey, setHasApiKey] = useState<boolean | null>(null); // null = loading
    const [pendingAction, setPendingAction] = useState<(() => void) | null>(null);

    // Fetch user tier to decide whether to show Pro upgrade card
    useEffect(() => {
        fetchWithAuth('/upgrade/status')
            .then(r => r.ok ? r.json() : null)
            .then(d => { if (d) setUserTier(d.tier); })
            .catch(() => {});
    }, []);

    // Fetch YouTube connection status so the Pro card doesn't nudge
    // users who already connected during onboarding.
    useEffect(() => {
        fetchWithAuth('/analytics/youtube/status')
            .then(r => r.ok ? r.json() : null)
            .then(d => { if (d?.connected) setYoutubeConnected(true); })
            .catch(() => {});
    }, []);

    // Check if user has any API key configured
    useEffect(() => {
        const checkKeys = async () => {
            try {
                const settings = await SettingsApi.getSettings();
                const keys = [
                    settings.groq_api_key,
                    settings.openai_api_key,
                    settings.anthropic_api_key,
                    settings.gcp_project_id,
                ];
                // A key exists if it's long enough. It may be masked (contains '...') if it was loaded from the server's .env.
                // If it's empty, then no key is set.
                const hasReal = keys.some(k => typeof k === 'string' && k.trim().length >= 8);
                setHasApiKey(hasReal);
            } catch {
                setHasApiKey(false);
            }
        };
        checkKeys();
    }, []);

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

    // Guard wrapper: checks for API key before running the action
    const guardWithApiKey = (action: () => void) => {
        if (hasApiKey === false) {
            setPendingAction(() => action);
            setShowApiKeyModal(true);
        } else {
            action();
        }
    };

    const handleProcessEpisode = async (episodeNum: number) => {
        guardWithApiKey(async () => {
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
        });
    };

    const handleUploadProcess = (jobId: string) => {
        setAndPersistJobId(jobId);
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
            <CreditsStatusBanner />
            {userTier === 'free' && (
                <ProUpgradeCard
                    onActivated={() => setUserTier('pro')}
                    youtubeConnected={youtubeConnected}
                    onYouTubeConnected={() => setYoutubeConnected(true)}
                />
            )}
            {/* Creator Signals extracted from the user's own shorts — feeds
                the Clips Ranker. Available to all users with a valid API key.
                Long-form episode analysis lives in Azelia Studio, not Clips. */}
            {youtubeConnected && <CreatorSignalsCard />}
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
                onJobStarted={handleUploadProcess}
                requireApiKey={() => {
                    if (hasApiKey === false) {
                        setShowApiKeyModal(true);
                        return false;
                    }
                    return true;
                }}
            />

            <MissingApiKeyModal
                isOpen={showApiKeyModal}
                onClose={() => {
                    setShowApiKeyModal(false);
                    setPendingAction(null);
                }}
                onKeySaved={() => {
                    setShowApiKeyModal(false);
                    setHasApiKey(true);
                    // Run the pending action if any
                    if (pendingAction) {
                        pendingAction();
                        setPendingAction(null);
                    }
                }}
            />
        </div>
    );
};
