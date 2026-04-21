import React, { useState, useRef } from 'react';
import { Upload, X, Settings2, Video, HardDrive, Zap, Sliders } from 'lucide-react';
import { ClipsApi, type ProcessRequest, type ProcessLocalRequest } from '../../lib/api';
import toast from 'react-hot-toast';
import { FilePicker } from './FilePicker';

// Preset profiles surface the most common config choices upfront so users
// don't have to hunt for the advanced Config panel. Quick = the default we
// ship; Custom reveals the full panel for power users.
type PresetId = 'quick' | 'custom';
const PRESETS: Record<PresetId, { label: string; blurb: string; config: Partial<ProcessRequest> }> = {
    quick: {
        label: 'Quick',
        blurb: '30–90s, score ≥ 70 — good default for most podcasts.',
        config: { min_duration: 30, max_duration: 90, min_score: 70 },
    },
    custom: {
        label: 'Custom',
        blurb: 'Fine-tune duration, score threshold, and transcription source.',
        config: {},
    },
};

interface UploadZoneProps {
    onJobStarted: (jobId: string) => void;
    requireApiKey?: () => boolean;
}

export const UploadZone: React.FC<UploadZoneProps> = ({ onJobStarted, requireApiKey }) => {
    const [file, setFile] = useState<File | null>(null);
    const [localVideoPath, setLocalVideoPath] = useState<string | null>(null);
    const [localVideoName, setLocalVideoName] = useState<string | null>(null);
    const [isPickerOpen, setIsPickerOpen] = useState(false);
    const [isHovering, setIsHovering] = useState(false);
    const [isProcessing, setIsProcessing] = useState(false);
    const [preset, setPreset] = useState<PresetId>('quick');
    // Config panel is only shown when the user explicitly picks Custom.
    const showConfig = preset === 'custom';

    // Default configuration
    const [config, setConfig] = useState<ProcessRequest>({
        min_duration: 30,
        max_duration: 90,
        min_score: 70,
        subtitle_style: 'highlight',
        transcription_source: 'local_whisper'
    });

    const fileInputRef = useRef<HTMLInputElement>(null);

    const handleDrop = (e: React.DragEvent) => {
        e.preventDefault();
        setIsHovering(false);
        if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
            const droppedFile = e.dataTransfer.files[0];
            if (droppedFile.type.startsWith('video/')) {
                setFile(droppedFile);
            } else {
                toast.error('Please upload a valid video file (.mp4, .mov, etc.)');
            }
        }
    };

    const handleProcess = async () => {
        if (!file && !localVideoPath) return;

        // Check for API key before processing
        if (requireApiKey && !requireApiKey()) return;
        setIsProcessing(true);
        const loadingToast = toast.loading(file ? 'Uploading file to local engine (this may take a moment)...' : 'Starting local process...');

        try {
            let response;
            if (localVideoPath) {
                const req: ProcessLocalRequest = { ...config, video_path: localVideoPath };
                response = await ClipsApi.processLocalVideo(req);
            } else if (file) {
                response = await ClipsApi.processVideo(file, config);
            }
            if (response) {
                toast.success('Job started successfully!', { id: loadingToast });
                onJobStarted(response.id);
            }
        } catch (error: any) {
            console.error(error);
            toast.error(error.message || 'Failed to start processing', { id: loadingToast });
        } finally {
            setIsProcessing(false);
        }
    };

    return (
        <div className="w-full max-w-3xl mx-auto mt-10">
            <div className="text-center mb-8">
                <h1 className="text-3xl font-bold mb-2">Process Raw Video</h1>
                <p className="text-zinc-400">Upload a single file or configure an episode from your library.</p>
            </div>

            <div
                className={`relative border-2 border-dashed rounded-2xl p-12 text-center transition-all duration-300 ${isHovering
                    ? 'border-brand-500 bg-brand-500/5'
                    : file
                        ? 'border-brand-400/50 bg-white/5'
                        : 'border-white/10 hover:border-white/20 hover:bg-white/5'
                    }`}
                onDragOver={(e) => { e.preventDefault(); setIsHovering(true); }}
                onDragLeave={() => setIsHovering(false)}
                onDrop={handleDrop}
            >
                <input
                    type="file"
                    ref={fileInputRef}
                    className="hidden"
                    accept="video/*"
                    onChange={(e) => {
                        if (e.target.files && e.target.files.length > 0) {
                            setFile(e.target.files[0]);
                        }
                    }}
                />

                {!file && !localVideoPath ? (
                    <div className="flex flex-col items-center">
                        <div className="w-16 h-16 rounded-full bg-white/5 flex items-center justify-center mb-4">
                            <Upload className="w-8 h-8 text-zinc-400" />
                        </div>
                        <h3 className="text-lg font-medium text-white mb-2">Select or Drop your video</h3>
                        <p className="text-sm text-zinc-500 mb-6 max-w-sm">
                            Support for MP4, MOV, MKV up to 5GB. Picking a local file skips upload delays.
                        </p>
                        <div className="flex justify-center w-full">
                            <button
                                onClick={() => setIsPickerOpen(true)}
                                className="px-6 py-2.5 bg-brand-600 hover:bg-brand-500 text-white rounded-xl font-medium transition-colors cursor-pointer flex items-center gap-2"
                            >
                                <HardDrive className="w-4 h-4" />
                                Select Local Video
                            </button>
                        </div>
                    </div>
                ) : (
                    <div className="flex flex-col items-center">
                        <div className="w-16 h-16 rounded-full bg-brand-500/20 text-brand-400 flex items-center justify-center mb-4 relative">
                            <Video className="w-8 h-8" />
                            <button
                                onClick={(e) => {
                                    e.stopPropagation();
                                    setFile(null);
                                    setLocalVideoPath(null);
                                    setLocalVideoName(null);
                                }}
                                className="absolute -top-2 -right-2 bg-zinc-800 rounded-full p-1 hover:bg-zinc-700 hover:text-white text-zinc-400 cursor-pointer"
                            >
                                <X className="w-4 h-4" />
                            </button>
                        </div>
                        <h3 className="text-lg font-medium text-white mb-2">{localVideoName || file?.name}</h3>
                        <p className="text-sm text-zinc-500 mb-8 font-mono">
                            {localVideoPath ? 'Linked Local Path' : file ? `${(file.size / (1024 * 1024)).toFixed(2)} MB` : ''}
                        </p>

                        {/* Preset picker — the most common decision surfaced up-front.
                            Switching to Custom reveals the Config panel below. */}
                        <div className="w-full max-w-md mx-auto mb-6">
                            <div className="grid grid-cols-2 gap-2 p-1 bg-zinc-900/60 border border-white/5 rounded-xl">
                                {(Object.keys(PRESETS) as PresetId[]).map(id => {
                                    const p = PRESETS[id];
                                    const Icon = id === 'quick' ? Zap : Sliders;
                                    const isActive = preset === id;
                                    return (
                                        <button
                                            key={id}
                                            type="button"
                                            onClick={() => {
                                                setPreset(id);
                                                if (id === 'quick') {
                                                    setConfig(prev => ({ ...prev, ...PRESETS.quick.config }));
                                                }
                                            }}
                                            className={`flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium transition-all ${isActive ? 'bg-brand-500/20 text-white border border-brand-500/30' : 'text-zinc-400 hover:text-white hover:bg-white/5 border border-transparent'}`}
                                        >
                                            <Icon className="w-4 h-4" />
                                            {p.label}
                                        </button>
                                    );
                                })}
                            </div>
                            <p className="text-xs text-zinc-500 mt-2 text-center">{PRESETS[preset].blurb}</p>
                        </div>

                        <div className="flex items-center gap-4">
                            <button
                                onClick={handleProcess}
                                disabled={isProcessing}
                                className="px-8 py-2.5 bg-brand-600 hover:bg-brand-500 text-white rounded-xl font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
                            >
                                {isProcessing ? 'Starting…' : 'Process Video'}
                            </button>
                        </div>
                    </div>
                )}
            </div>

            <FilePicker
                isOpen={isPickerOpen}
                currentPath="~"
                onSelect={(path, name) => {
                    setLocalVideoPath(path);
                    setLocalVideoName(name);
                    setFile(null); // Clear manual upload state
                    setIsPickerOpen(false);
                }}
                onClose={() => setIsPickerOpen(false)}
            />

            {/* Configuration Panel */}
            {(file || localVideoPath) && showConfig && (
                <div className="mt-6 p-6 bg-zinc-900 border border-zinc-800 rounded-2xl animate-in fade-in slide-in-from-top-4">
                    <h4 className="text-sm font-semibold text-zinc-300 uppercase tracking-wider mb-4">Processing Configuration</h4>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                        <div>
                            <label className="block text-sm font-medium text-zinc-400 mb-2">Duration Limits (seconds)</label>
                            <div className="flex items-center gap-2">
                                <input
                                    type="number"
                                    value={config.min_duration}
                                    onChange={(e) => setConfig({ ...config, min_duration: parseInt(e.target.value) || 30 })}
                                    className="w-full px-3 py-2 bg-black border border-zinc-800 rounded-lg text-sm focus:outline-none focus:border-brand-500"
                                    placeholder="Min"
                                />
                                <span className="text-zinc-600">-</span>
                                <input
                                    type="number"
                                    value={config.max_duration}
                                    onChange={(e) => setConfig({ ...config, max_duration: parseInt(e.target.value) || 90 })}
                                    className="w-full px-3 py-2 bg-black border border-zinc-800 rounded-lg text-sm focus:outline-none focus:border-brand-500"
                                    placeholder="Max"
                                />
                            </div>
                        </div>

                        <div>
                            <label className="block text-sm font-medium text-zinc-400 mb-2">Target Virality Score (0-100)</label>
                            <input
                                type="number"
                                value={config.min_score}
                                onChange={(e) => setConfig({ ...config, min_score: parseInt(e.target.value) || 70 })}
                                className="w-full px-3 py-2 bg-black border border-zinc-800 rounded-lg text-sm focus:outline-none focus:border-brand-500"
                            />
                        </div>

                        <div>
                            <label className="block text-sm font-medium text-zinc-400 mb-2">Transcription Source</label>
                            <select
                                value={config.transcription_source}
                                onChange={(e) => setConfig({ ...config, transcription_source: e.target.value })}
                                className="w-full px-3 py-2 bg-black border border-zinc-800 rounded-lg text-sm focus:outline-none focus:border-brand-500 text-white cursor-pointer"
                            >
                                <option value="local_whisper">Local Whisper (Free, Slower)</option>
                                <option value="assemblyai">AssemblyAI (Cloud, Faster)</option>
                                <option value="supabase_custom">My Supabase (custom transcripts)</option>
                            </select>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};
