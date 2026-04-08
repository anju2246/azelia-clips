import React, { useState, useEffect } from 'react';
import { Folder, FileVideo, ArrowUp, Loader2, X, Check } from 'lucide-react';
import { supabase } from '../../lib/supabase';

interface FileEntry {
    name: string;
    path: string;
    is_dir: boolean;
    size_mb?: string;
    has_children?: boolean;
}

interface BrowseFilesResponse {
    path: string;
    parent: string | null;
    entries: FileEntry[];
    error?: string;
}

interface FilePickerProps {
    isOpen: boolean;
    currentPath: string;
    onSelect: (path: string, name: string) => void;
    onClose: () => void;
}

const API_BASE = (import.meta.env?.PUBLIC_API_URL as string) || '/api';

export const FilePicker: React.FC<FilePickerProps> = ({ isOpen, currentPath, onSelect, onClose }) => {
    const [entries, setEntries] = useState<FileEntry[]>([]);
    const [parentPath, setParentPath] = useState<string | null>(null);
    const [resolvedPath, setResolvedPath] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState('');

    useEffect(() => {
        if (isOpen) {
            // Start from given path or home if empty
            const startPath = currentPath && currentPath !== '' ? currentPath : '~';
            loadDirectory(startPath);
        }
    }, [isOpen]);

    const loadDirectory = async (path: string) => {
        setIsLoading(true);
        setError('');
        try {
            const { data: authData } = await supabase.auth.getSession();
            const token = authData?.session?.access_token;
            const res = await fetch(`${API_BASE}/browse-files?path=${encodeURIComponent(path)}`, {
                headers: token ? { Authorization: `Bearer ${token}` } : {},
            });
            const data: BrowseFilesResponse = await res.json();

            if (!res.ok || data.error) {
                setError(data.error || 'Failed to load files');
                setEntries([]);
            } else {
                setEntries(data.entries ?? []);
            }
            setResolvedPath(data.path ?? path);
            setParentPath(data.parent ?? null);
        } catch (e) {
            setError('Failed to load files');
        } finally {
            setIsLoading(false);
        }
    };

    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
            <div className="bg-zinc-900 border border-white/10 rounded-2xl w-full max-w-2xl shadow-2xl flex flex-col max-h-[85vh]">

                {/* Header */}
                <div className="flex items-center justify-between px-5 py-4 border-b border-white/5">
                    <h3 className="text-white font-semibold text-lg">Select Raw Video File</h3>
                    <button onClick={onClose} className="text-zinc-500 hover:text-white transition-colors cursor-pointer">
                        <X className="w-5 h-5" />
                    </button>
                </div>

                {/* Current Path Bar */}
                <div className="px-5 py-3 bg-black/30 border-b border-white/5">
                    {/* Quick Access Buttons */}
                    <div className="flex items-center gap-2 mb-2">
                        <span className="text-xs text-zinc-500 mr-1">Go to:</span>
                        <button
                            onClick={() => loadDirectory('~')}
                            className="text-xs px-2.5 py-1 rounded-lg bg-white/5 hover:bg-white/10 text-zinc-400 hover:text-white transition-colors cursor-pointer"
                        >
                            🏠 Home
                        </button>
                        <button
                            onClick={() => loadDirectory('/Volumes')}
                            className="text-xs px-2.5 py-1 rounded-lg bg-white/5 hover:bg-white/10 text-zinc-400 hover:text-white transition-colors cursor-pointer"
                        >
                            💾 External Drives
                        </button>
                        <button
                            onClick={() => loadDirectory('~/Desktop')}
                            className="text-xs px-2.5 py-1 rounded-lg bg-white/5 hover:bg-white/10 text-zinc-400 hover:text-white transition-colors cursor-pointer"
                        >
                            🖥️ Desktop
                        </button>
                        <button
                            onClick={() => loadDirectory('~/Downloads')}
                            className="text-xs px-2.5 py-1 rounded-lg bg-white/5 hover:bg-white/10 text-zinc-400 hover:text-white transition-colors cursor-pointer"
                        >
                            📥 Downloads
                        </button>
                    </div>
                    {/* Current Path */}
                    <div className="flex items-center gap-2">
                        {parentPath && (
                            <button
                                onClick={() => loadDirectory(parentPath)}
                                className="p-1.5 hover:bg-white/10 rounded-lg transition-colors text-zinc-400 hover:text-white cursor-pointer"
                                title="Go up"
                            >
                                <ArrowUp className="w-4 h-4" />
                            </button>
                        )}
                        <div className="flex-1 overflow-x-auto no-scrollbar">
                            <code className="text-sm text-brand-400 font-mono whitespace-nowrap">{resolvedPath}</code>
                        </div>
                    </div>
                </div>

                {/* File List */}
                <div className="flex-1 overflow-y-auto min-h-[300px] max-h-[500px]">
                    {isLoading ? (
                        <div className="flex items-center justify-center py-12">
                            <Loader2 className="w-6 h-6 text-brand-500 animate-spin" />
                        </div>
                    ) : error ? (
                        <div className="text-center py-12 text-red-400 text-sm">{error}</div>
                    ) : entries.length === 0 ? (
                        <div className="text-center py-12 text-zinc-500 text-sm">Folder is empty or contains no supported videos</div>
                    ) : (
                        <div className="py-1">
                            {entries.map((entry) => (
                                <button
                                    key={entry.path}
                                    onClick={() => entry.is_dir ? loadDirectory(entry.path) : onSelect(entry.path, entry.name)}
                                    className={`w-full px-5 py-3 flex items-center gap-4 hover:bg-white/5 transition-colors text-left cursor-pointer group ${!entry.is_dir ? 'hover:bg-brand-500/10' : ''}`}
                                >
                                    {entry.is_dir ? (
                                        <Folder className="w-5 h-5 text-zinc-500 group-hover:text-amber-400 transition-colors flex-shrink-0" />
                                    ) : (
                                        <FileVideo className="w-5 h-5 text-brand-400 flex-shrink-0" />
                                    )}

                                    <div className="flex flex-col flex-1 min-w-0">
                                        <span className={`text-sm font-medium truncate transition-colors ${entry.is_dir ? 'text-zinc-300 group-hover:text-white' : 'text-white'}`}>
                                            {entry.name}
                                        </span>
                                    </div>

                                    {!entry.is_dir && entry.size_mb && (
                                        <span className="text-xs text-zinc-500 font-mono whitespace-nowrap">
                                            {entry.size_mb} MB
                                        </span>
                                    )}
                                    {entry.is_dir && entry.has_children && (
                                        <span className="text-xs text-zinc-600 font-mono bg-white/5 px-2 py-0.5 rounded-full">
                                            Folder
                                        </span>
                                    )}
                                </button>
                            ))}
                        </div>
                    )}
                </div>

                {/* Footer */}
                <div className="px-5 py-4 border-t border-white/5 bg-black/20 rounded-b-2xl">
                    <p className="text-xs text-zinc-500 text-center">
                        Select a .mp4, .mov, or .mkv file directly from your hard drive to process it instantly without uploading.
                    </p>
                </div>
            </div>
        </div>
    );
};
