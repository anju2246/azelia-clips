import React, { useEffect, useState } from 'react';
import { Play, Folder, CheckCircle, AlertCircle, Loader2, Upload } from 'lucide-react';

interface Episode {
    id: string;
    number: number;
    title: string;
    has_video: boolean;
    has_transcript: boolean;
    is_processed: boolean;
    path: string;
}

const API_URL = 'http://localhost:8000/api';

export default function EpisodeList() {
    const [episodes, setEpisodes] = useState<Episode[]>([]);
    const [loading, setLoading] = useState(true);
    const [processingId, setProcessingId] = useState<string | null>(null);

    useEffect(() => {
        fetchEpisodes();
    }, []);

    const fetchEpisodes = async () => {
        try {
            const res = await fetch(`${API_URL}/episodes`);
            if (res.ok) {
                const data = await res.json();
                setEpisodes(data);
            }
        } catch (error) {
            console.error("Failed to fetch episodes", error);
        } finally {
            setLoading(false);
        }
    };

    const handleProcess = async (epNumber: number) => {
        setProcessingId(`EP${epNumber}`);
        try {
            // Get settings from LocalStorage
            const transcriptionSource = localStorage.getItem('celia_transcription_source') || 'local_whisper';
            const supabaseUrl = localStorage.getItem('celia_supabase_url') || '';
            const supabaseKey = localStorage.getItem('celia_supabase_key') || '';
            const assemblyKey = localStorage.getItem('celia_assemblyai_key') || '';
            // Default score/style if not set (though SettingsDashboard doesn't save these to LS yet, we should use defaults)
            // TODO: Ensure SettingsDashboard saves min_score to LS if we want it global

            const res = await fetch(`${API_URL}/episodes/${epNumber}/process`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    min_score: 70, // TODO: Read from settings if available
                    subtitle_style: 'highlight', // TODO: Read from settings
                    transcription_source: transcriptionSource,
                    supabase_url: supabaseUrl,
                    supabase_key: supabaseKey,
                    assemblyai_key: assemblyKey
                })
            });
            if (res.ok) {
                alert(`Started processing EP${epNumber}`);
                // Ideally refresh or polling logic here
            } else {
                alert("Failed to start processing");
            }
        } catch (error) {
            console.error("Error starting process", error);
        } finally {
            setProcessingId(null);
        }
    };

    const handleUpload = async (epNumber: number) => {
        if (!confirm(`Upload transcript for EP${epNumber} to Supabase?`)) return;

        try {
            const res = await fetch(`${API_URL}/episodes/${epNumber}/upload-transcript`, {
                method: 'POST'
            });
            if (res.ok) {
                alert(`Uploaded EP${epNumber} successfully!`);
            } else {
                const err = await res.json();
                alert(`Upload failed: ${err.detail}`);
            }
        } catch (error) {
            console.error("Upload error", error);
            alert("Upload failed");
        }
    };

    if (loading) {
        return (
            <div className="flex justify-center py-12">
                <Loader2 className="animate-spin text-brand-500" size={32} />
            </div>
        );
    }

    if (episodes.length === 0) {
        return (
            <div className="text-center py-12 space-y-4">
                <Folder className="mx-auto text-zinc-700" size={48} />
                <h3 className="text-xl font-medium text-zinc-300">No episodes found</h3>
                <p className="text-zinc-500 max-w-sm mx-auto">
                    Check your Podcast Directory setting in Settings page.
                    Current path might be empty or incorrect.
                </p>
            </div>
        );
    }

    return (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {episodes.map((ep) => (
                <div key={ep.id} className="bg-zinc-900 border border-zinc-800 rounded-xl p-5 hover:border-zinc-700 transition-all">
                    <div className="flex justify-between items-start mb-4">
                        <div className="bg-zinc-800 text-zinc-300 text-xs font-bold px-2 py-1 rounded">
                            EP{ep.number}
                        </div>
                        {ep.is_processed ? (
                            <div className="text-emerald-500 flex items-center gap-1 text-xs font-medium">
                                <CheckCircle size={14} /> Processed
                            </div>
                        ) : (
                            <div className="text-zinc-500 flex items-center gap-1 text-xs">
                                <AlertCircle size={14} /> Unprocessed
                            </div>
                        )}
                    </div>

                    <h3 className="text-lg font-semibold text-zinc-100 line-clamp-2 mb-2" title={ep.title}>
                        {ep.title}
                    </h3>

                    <div className="space-y-2 text-sm text-zinc-500 mb-6">
                        <div className="flex items-center gap-2">
                            <span className={ep.has_video ? "text-emerald-400" : "text-red-400"}>
                                {ep.has_video ? "✓" : "✗"} Video
                            </span>
                            <span className="text-zinc-700">|</span>
                            <span className={ep.has_transcript ? "text-emerald-400" : "text-yellow-500"}>
                                {ep.has_transcript ? "✓" : "○"} Transcript
                            </span>
                        </div>
                        <p className="text-xs truncate" title={ep.path}>{ep.path}</p>
                    </div>

                    <div className="flex gap-2">
                        <button
                            onClick={() => handleProcess(ep.number)}
                            disabled={processingId === `EP${ep.number}` || ep.is_processed}
                            className={`
                                flex-1 flex items-center justify-center gap-2 py-2.5 rounded-lg font-medium transition-colors
                                ${ep.is_processed
                                    ? 'bg-zinc-800 text-zinc-400 cursor-default'
                                    : 'bg-brand-600 hover:bg-brand-500 text-white shadow-lg shadow-brand-500/20'}
                            `}
                        >
                            {processingId === `EP${ep.number}` ? (
                                <><Loader2 className="animate-spin" size={18} /> Processing...</>
                            ) : ep.is_processed ? (
                                "View Clips"
                            ) : (
                                <><Play size={18} /> Process Episode</>
                            )}
                        </button>

                        {ep.has_transcript && (
                            <button
                                onClick={() => handleUpload(ep.number)}
                                title="Upload Transcript to Supabase"
                                className="px-3 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded-lg border border-zinc-700 transition-colors flex items-center justify-center"
                            >
                                <Upload size={18} />
                            </button>
                        )}
                    </div>
                </div>
            ))}
        </div>
    );
}
