import React, { useState, useCallback } from 'react';
import { Upload, FileVideo, Music, Loader2 } from 'lucide-react';
import { clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

function cn(...inputs: (string | undefined | null | false)[]) {
    return twMerge(clsx(inputs));
}

export default function UploadWidget() {
    const [isDragging, setIsDragging] = useState(false);
    const [file, setFile] = useState<File | null>(null);
    const [isUploading, setIsUploading] = useState(false);

    const handleDragOver = useCallback((e: React.DragEvent) => {
        e.preventDefault();
        setIsDragging(true);
    }, []);

    const handleDragLeave = useCallback((e: React.DragEvent) => {
        e.preventDefault();
        setIsDragging(false);
    }, []);

    const handleDrop = useCallback((e: React.DragEvent) => {
        e.preventDefault();
        setIsDragging(false);

        if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
            const droppedFile = e.dataTransfer.files[0];
            setFile(droppedFile);
        }
    }, []);

    const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
        if (e.target.files && e.target.files.length > 0) {
            const selectedFile = e.target.files[0];
            setFile(selectedFile);
        }
    }, []);

    const handleUpload = async (e: React.MouseEvent) => {
        e.stopPropagation();
        if (!file) return;

        setIsUploading(true);
        const formData = new FormData();
        formData.append('file', file);

        // Get settings
        const settings = JSON.parse(localStorage.getItem('celia-settings') || '{}');
        formData.append('min_duration', settings.minDuration || 30);
        formData.append('max_duration', settings.maxDuration || 90);
        formData.append('subtitle_style', settings.subtitleStyle || 'highlight');
        // Default score
        formData.append('min_score', '70');

        try {
            // In dev, we point to localhost:8000. In prod, this would be relative or configured.
            const API_URL = import.meta.env.PUBLIC_API_URL || 'http://localhost:8001';

            // Get Auth Token if available
            let token = null;
            const SUPABASE_URL = import.meta.env.PUBLIC_SUPABASE_URL;
            const SUPABASE_KEY = import.meta.env.PUBLIC_SUPABASE_ANON_KEY;

            if (SUPABASE_URL && SUPABASE_KEY) {
                try {
                    // Dynamic import to avoid issues if dependency missing, though it should be there now
                    const { createClient } = await import('@supabase/supabase-js');
                    const supabase = createClient(SUPABASE_URL, SUPABASE_KEY);
                    const { data } = await supabase.auth.getSession();
                    token = data.session?.access_token;
                } catch (e) {
                    console.warn("Auth check failed:", e);
                }
            }

            const res = await fetch(`${API_URL}/api/process`, {
                method: 'POST',
                body: formData,
                headers: {
                    ...(token ? { 'Authorization': `Bearer ${token}` } : {})
                }
            });

            if (!res.ok) throw new Error('Upload failed');

            const data = await res.json();
            console.log('Job created:', data);

            alert(`Job started! ID: ${data.id}`);
            setFile(null);

        } catch (error) {
            console.error(error);
            alert('Error uploading file');
        } finally {
            setIsUploading(false);
        }
    };

    return (
        <div
            className={cn(
                "border-2 border-dashed rounded-xl p-12 flex flex-col items-center justify-center gap-4 transition-all cursor-pointer group relative overflow-hidden",
                isDragging ? "border-brand-500 bg-brand-500/10 scale-[1.02]" : "border-zinc-800 hover:border-brand-500/50 hover:bg-zinc-900/50"
            )}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            onClick={() => document.getElementById('file-upload')?.click()}
        >
            <input
                type="file"
                id="file-upload"
                className="hidden"
                accept="video/*,audio/*"
                onChange={handleFileSelect}
            />

            {file ? (
                <div className="flex flex-col items-center gap-2 animate-in fade-in zoom-in duration-300">
                    <div className="w-16 h-16 rounded-full bg-brand-500/20 text-brand-500 flex items-center justify-center mb-2">
                        {file.type.startsWith('audio') ? <Music size={32} /> : <FileVideo size={32} />}
                    </div>
                    <p className="font-medium text-zinc-100 text-lg">{file.name}</p>
                    <p className="text-zinc-500">{(file.size / (1024 * 1024)).toFixed(2)} MB</p>

                    <button
                        className="mt-4 px-6 py-2 bg-brand-400 hover:bg-brand-600 text-white rounded-full font-medium transition-all shadow-lg shadow-brand-400/20 flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
                        onClick={handleUpload}
                        disabled={isUploading}
                    >
                        {isUploading ? (
                            <>
                                <Loader2 className="animate-spin" size={18} />
                                Uploading...
                            </>
                        ) : (
                            'Start Processing'
                        )}
                    </button>
                </div>
            ) : (
                <>
                    <div className={cn(
                        "w-16 h-16 rounded-full flex items-center justify-center transition-transform duration-300",
                        isDragging ? "bg-brand-500 text-white scale-110" : "bg-zinc-900 text-zinc-400 group-hover:scale-110 group-hover:text-brand-400"
                    )}>
                        <Upload size={32} />
                    </div>
                    <div className="text-center space-y-1 z-10">
                        <p className="font-medium text-zinc-200 text-lg">
                            {isDragging ? "Drop file here" : "Upload an episode"}
                        </p>
                        <p className="text-sm text-zinc-500">MP4, MOV or MKV up to 2GB</p>
                    </div>
                </>
            )}
        </div>
    );
}
