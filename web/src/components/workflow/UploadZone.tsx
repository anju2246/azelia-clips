import React, { useState, useRef } from 'react';
import { Upload, X, Settings2, Video } from 'lucide-react';
import { ClipsApi, type ProcessRequest } from '../../lib/api';
import toast from 'react-hot-toast';

interface UploadZoneProps {
    onJobStarted: (jobId: string) => void;
}

export const UploadZone: React.FC<UploadZoneProps> = ({ onJobStarted }) => {
    const [file, setFile] = useState<File | null>(null);
    const [isHovering, setIsHovering] = useState(false);
    const [isProcessing, setIsProcessing] = useState(false);
    const [showConfig, setShowConfig] = useState(false);

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
        if (!file) return;

        setIsProcessing(true);
        const loadingToast = toast.loading('Uploading and starting process...');

        try {
            const response = await ClipsApi.processVideo(file, config);
            toast.success('Job started successfully!', { id: loadingToast });
            onJobStarted(response.id);
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

                {!file ? (
                    <div className="flex flex-col items-center">
                        <div className="w-16 h-16 rounded-full bg-white/5 flex items-center justify-center mb-4">
                            <Upload className="w-8 h-8 text-zinc-400" />
                        </div>
                        <h3 className="text-lg font-medium text-white mb-2">Drag and drop your video</h3>
                        <p className="text-sm text-zinc-500 mb-6 max-w-sm">
                            Support for MP4, MOV, MKV up to 5GB. Processing time depends on your local hardware.
                        </p>
                        <button
                            onClick={() => fileInputRef.current?.click()}
                            className="px-6 py-2.5 bg-brand-600 hover:bg-brand-500 text-white rounded-xl font-medium transition-colors cursor-pointer"
                        >
                            Browse Files
                        </button>
                    </div>
                ) : (
                    <div className="flex flex-col items-center">
                        <div className="w-16 h-16 rounded-full bg-brand-500/20 text-brand-400 flex items-center justify-center mb-4 relative">
                            <Video className="w-8 h-8" />
                            <button
                                onClick={(e) => { e.stopPropagation(); setFile(null); }}
                                className="absolute -top-2 -right-2 bg-zinc-800 rounded-full p-1 hover:bg-zinc-700 hover:text-white text-zinc-400 cursor-pointer"
                            >
                                <X className="w-4 h-4" />
                            </button>
                        </div>
                        <h3 className="text-lg font-medium text-white mb-2">{file.name}</h3>
                        <p className="text-sm text-zinc-500 mb-8">
                            {(file.size / (1024 * 1024)).toFixed(2)} MB
                        </p>

                        <div className="flex items-center gap-4">
                            <button
                                onClick={() => setShowConfig(!showConfig)}
                                className="px-4 py-2.5 bg-zinc-800 hover:bg-zinc-700 text-white border border-zinc-700 rounded-xl font-medium transition-colors flex items-center gap-2 cursor-pointer"
                            >
                                <Settings2 className="w-4 h-4" />
                                Config
                            </button>
                            <button
                                onClick={handleProcess}
                                disabled={isProcessing}
                                className="px-8 py-2.5 bg-brand-600 hover:bg-brand-500 text-white rounded-xl font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
                            >
                                {isProcessing ? 'Starting...' : 'Process Video'}
                            </button>
                        </div>
                    </div>
                )}
            </div>

            {/* Configuration Panel */}
            {file && showConfig && (
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
                                <option value="supabase">Supabase Serverless (Edge)</option>
                            </select>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};
