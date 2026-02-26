import React, { useEffect, useState } from 'react';
import { Save, Loader2, Database, Key, FolderOpen, ToggleLeft, ToggleRight } from 'lucide-react';
import { SettingsApi, type SettingsResponse, type UpdateSettingsRequest } from '../../lib/api';
import toast from 'react-hot-toast';

export const SettingsForm: React.FC = () => {
    const [settings, setSettings] = useState<SettingsResponse | null>(null);
    const [formData, setFormData] = useState<UpdateSettingsRequest>({});
    const [isLoading, setIsLoading] = useState(true);
    const [isSaving, setIsSaving] = useState(false);
    const [generateTeasers, setGenerateTeasers] = useState(false);

    useEffect(() => {
        loadSettings();
    }, []);

    const loadSettings = async () => {
        try {
            const data = await SettingsApi.getSettings();
            setSettings(data);
            setFormData({
                podcast_name: data.podcast_name,
                podcast_dir: data.podcast_dir,
            });
        } catch (error) {
            toast.error('Failed to load settings');
        } finally {
            setIsLoading(false);
        }
    };

    const handleSave = async (e: React.FormEvent) => {
        e.preventDefault();
        setIsSaving(true);
        const loadingToast = toast.loading('Saving settings...');

        try {
            // Only send fields that have been explicitly modified or are non-empty strings
            // For API keys, if they are exactly 8 asterisks (masked), we don't send them.
            const payload: UpdateSettingsRequest = { ...formData };

            if (payload.groq_api_key === '********' || !payload.groq_api_key) delete payload.groq_api_key;
            if (payload.supabase_key === '********' || !payload.supabase_key) delete payload.supabase_key;

            const updated = await SettingsApi.updateSettings(payload);
            setSettings(updated);
            toast.success('Settings saved successfully', { id: loadingToast });
        } catch (error: any) {
            toast.error(error.message || 'Failed to save settings', { id: loadingToast });
        } finally {
            setIsSaving(false);
        }
    };

    if (isLoading) {
        return (
            <div className="flex justify-center py-20">
                <Loader2 className="w-8 h-8 text-brand-500 animate-spin" />
            </div>
        );
    }

    return (
        <div className="max-w-4xl mx-auto pb-12">
            <div className="mb-8">
                <h2 className="text-3xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-white to-zinc-400">
                    Engine Settings
                </h2>
                <p className="text-zinc-500 mt-2">Configure local intelligence paths, API keys, and pipeline behaviors.</p>
            </div>

            <form onSubmit={handleSave} className="space-y-8">

                {/* Core Settings */}
                <section className="bg-zinc-900/40 border border-white/5 rounded-2xl overflow-hidden">
                    <div className="px-6 py-4 border-b border-white/5 bg-black/20 flex items-center gap-2">
                        <FolderOpen className="w-5 h-5 text-brand-400" />
                        <h3 className="font-semibold text-white">Local Workspace</h3>
                    </div>
                    <div className="p-6 space-y-6">
                        <div>
                            <label className="block text-sm font-medium text-zinc-300 mb-2">Podcast Name</label>
                            <input
                                type="text"
                                value={formData.podcast_name ?? settings?.podcast_name ?? ''}
                                onChange={(e) => setFormData({ ...formData, podcast_name: e.target.value })}
                                className="w-full px-4 py-2.5 bg-black border border-zinc-800 rounded-xl focus:outline-none focus:border-brand-500 text-white"
                                placeholder="e.g. The Inminente Podcast"
                            />
                        </div>
                        <div>
                            <label className="block text-sm font-medium text-zinc-300 mb-2">Podcast Root Directory</label>
                            <div className="flex gap-2">
                                <input
                                    type="text"
                                    value={formData.podcast_dir ?? settings?.podcast_dir ?? ''}
                                    onChange={(e) => setFormData({ ...formData, podcast_dir: e.target.value })}
                                    className="flex-1 px-4 py-2.5 bg-black border border-zinc-800 rounded-xl focus:outline-none focus:border-brand-500 text-white font-mono text-sm"
                                    placeholder="/Users/name/Documents/Podcasts/"
                                />
                                <button
                                    type="button"
                                    onClick={async () => {
                                        try {
                                            // @ts-ignore — File System Access API
                                            const dirHandle = await window.showDirectoryPicker({ mode: 'read' });
                                            setFormData({ ...formData, podcast_dir: dirHandle.name });
                                            toast.success(`Selected: ${dirHandle.name}`);
                                        } catch (err: any) {
                                            if (err.name !== 'AbortError') toast.error('Folder selection failed');
                                        }
                                    }}
                                    className="px-4 py-2.5 bg-white/5 hover:bg-white/10 border border-zinc-800 rounded-xl text-sm text-zinc-300 transition-colors flex items-center gap-2 whitespace-nowrap"
                                >
                                    <FolderOpen className="w-4 h-4" /> Browse
                                </button>
                            </div>
                            <p className="text-xs text-zinc-500 mt-2">
                                Click <strong>Browse</strong> to pick your folder visually, or type the path manually.
                            </p>
                        </div>
                    </div>
                </section>

                {/* API Keys */}
                <section className="bg-zinc-900/40 border border-white/5 rounded-2xl overflow-hidden">
                    <div className="px-6 py-4 border-b border-white/5 bg-black/20 flex items-center gap-2">
                        <Key className="w-5 h-5 text-purple-400" />
                        <h3 className="font-semibold text-white">Intelligence API Keys</h3>
                    </div>
                    <div className="p-6 space-y-6">
                        <div>
                            <label className="block text-sm font-medium text-zinc-300 mb-2">Groq API Key (Llama 3)</label>
                            <input
                                type="password"
                                placeholder={settings?.groq_api_key ? '********' : 'Enter Groq API Key'}
                                onChange={(e) => setFormData({ ...formData, groq_api_key: e.target.value })}
                                className="w-full px-4 py-2.5 bg-black border border-zinc-800 rounded-xl focus:outline-none focus:border-brand-500 text-white font-mono"
                            />
                            <p className="text-xs text-zinc-500 mt-2">Used for rapid curation and transcript analysis.</p>
                        </div>
                    </div>
                </section>

                {/* Supabase Core */}
                <section className="bg-zinc-900/40 border border-white/5 rounded-2xl overflow-hidden">
                    <div className="px-6 py-4 border-b border-white/5 bg-black/20 flex items-center gap-2">
                        <Database className="w-5 h-5 text-emerald-400" />
                        <h3 className="font-semibold text-white">Database & Sync (Supabase)</h3>
                    </div>
                    <div className="p-6 space-y-6">
                        <div>
                            <label className="block text-sm font-medium text-zinc-300 mb-2">Supabase URL</label>
                            <input
                                type="text"
                                value={formData.supabase_url ?? settings?.supabase_url ?? ''}
                                onChange={(e) => setFormData({ ...formData, supabase_url: e.target.value })}
                                className="w-full px-4 py-2.5 bg-black border border-zinc-800 rounded-xl focus:outline-none focus:border-brand-500 text-white font-mono text-sm"
                            />
                        </div>
                        <div>
                            <label className="block text-sm font-medium text-zinc-300 mb-2">Supabase Service Key</label>
                            <input
                                type="password"
                                placeholder={settings?.supabase_key ? '********' : 'Enter Service Role Key'}
                                onChange={(e) => setFormData({ ...formData, supabase_key: e.target.value })}
                                className="w-full px-4 py-2.5 bg-black border border-zinc-800 rounded-xl focus:outline-none focus:border-brand-500 text-white font-mono"
                            />
                        </div>
                    </div>
                </section>

                {/* Experimental Features */}
                <section className="bg-zinc-900/40 border border-white/5 rounded-2xl overflow-hidden p-6 flex items-center justify-between">
                    <div>
                        <h3 className="font-semibold text-white flex items-center gap-2">
                            Generate Teasers & Intros <span className="text-[10px] bg-brand-500/20 text-brand-400 px-2 py-0.5 rounded uppercase tracking-widest border border-brand-500/30">Beta</span>
                        </h3>
                        <p className="text-sm text-zinc-500 mt-1">Automatically stitch the best hook to the start of the full episode.</p>
                    </div>
                    <button
                        type="button"
                        onClick={() => setGenerateTeasers(!generateTeasers)}
                        className={`cursor-pointer transition-colors ${generateTeasers ? 'text-brand-500' : 'text-zinc-600'}`}
                    >
                        {generateTeasers ? <ToggleRight className="w-10 h-10" /> : <ToggleLeft className="w-10 h-10" />}
                    </button>
                </section>

                {/* Action Bar */}
                <div className="sticky bottom-6 flex justify-end">
                    <button
                        type="submit"
                        disabled={isSaving}
                        className="cursor-pointer flex items-center gap-2 px-8 py-3 bg-brand-600 hover:bg-brand-500 text-white rounded-xl font-medium transition-all shadow-lg shadow-brand-500/20 disabled:opacity-50"
                    >
                        {isSaving ? <Loader2 className="w-5 h-5 animate-spin" /> : <Save className="w-5 h-5" />}
                        {isSaving ? 'Saving...' : 'Save Configuration'}
                    </button>
                </div>

            </form>
        </div>
    );
};
