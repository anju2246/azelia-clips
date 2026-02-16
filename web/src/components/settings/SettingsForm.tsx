import React, { useState, useEffect } from 'react';
import { Save, Key, Sliders, Type, Folder, Database } from 'lucide-react';

const API_URL = 'http://localhost:8000/api';

export default function SettingsForm() {
    const [settings, setSettings] = useState({
        podcast_name: '',
        podcast_dir: '',
        groq_api_key: '',
        supabase_url: '',
        supabase_key: '',
        min_duration: 30,
        max_duration: 90,
        subtitle_style: 'highlight'
    });
    const [loading, setLoading] = useState(true);
    const [isSaved, setIsSaved] = useState(false);

    // Load from API on mount
    useEffect(() => {
        fetch(`${API_URL}/settings`)
            .then(res => res.json())
            .then(data => {
                setSettings(prev => ({ ...prev, ...data }));
                setLoading(false);
            })
            .catch(err => console.error("Failed to load settings", err));
    }, []);

    const handleChange = (field: string, value: any) => {
        setSettings(prev => ({ ...prev, [field]: value }));
    };

    const handleSave = async (e: React.FormEvent) => {
        e.preventDefault();
        try {
            const res = await fetch(`${API_URL}/settings`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(settings)
            });
            if (res.ok) {
                setIsSaved(true);
                setTimeout(() => setIsSaved(false), 2000);
            }
        } catch (err) {
            console.error("Failed to save settings", err);
        }
    };

    if (loading) return <div className="text-zinc-500">Loading settings...</div>;

    return (
        <form onSubmit={handleSave} className="space-y-8">

            {/* Local Library Config */}
            <section className="space-y-4">
                <div className="flex items-center gap-2 pb-2 border-b border-zinc-800">
                    <Folder className="text-brand-500" size={20} />
                    <h2 className="text-xl font-semibold text-zinc-100">Local Library</h2>
                </div>
                <div className="grid gap-4 max-w-xl">
                    <div className="space-y-2">
                        <label className="text-sm font-medium text-zinc-300">Podcast Name</label>
                        <input
                            type="text"
                            value={settings.podcast_name}
                            onChange={(e) => handleChange('podcast_name', e.target.value)}
                            placeholder="My Awesome Podcast"
                            className="w-full bg-zinc-900 border border-zinc-700 rounded-lg px-4 py-2 text-zinc-100 focus:ring-2 focus:ring-brand-500 focus:border-brand-500 outline-none transition-all font-mono text-sm"
                        />
                        <p className="text-xs text-zinc-500">Used for generating context-aware captions & hashtags</p>
                    </div>

                    <div className="space-y-2">
                        <label className="text-sm font-medium text-zinc-300">Podcast Directory</label>
                        <input
                            type="text"
                            value={settings.podcast_dir}
                            onChange={(e) => handleChange('podcast_dir', e.target.value)}
                            placeholder="/Volumes/Backup/Podcasts"
                            className="w-full bg-zinc-900 border border-zinc-700 rounded-lg px-4 py-2 text-zinc-100 focus:ring-2 focus:ring-brand-500 focus:border-brand-500 outline-none transition-all font-mono text-sm"
                        />
                        <p className="text-xs text-zinc-500">Absolute path to your episodes folder (e.g. /Users/name/podcasts)</p>
                    </div>
                </div>
            </section>

            {/* API Keys Section */}
            <section className="space-y-4">
                <div className="flex items-center gap-2 pb-2 border-b border-zinc-800">
                    <Key className="text-brand-500" size={20} />
                    <h2 className="text-xl font-semibold text-zinc-100">AI Providers</h2>
                </div>

                <div className="grid gap-4 max-w-xl">
                    <div className="space-y-2">
                        <label className="text-sm font-medium text-zinc-300">Groq API Key (Recommended)</label>
                        <input
                            type="password"
                            value={settings.groq_api_key}
                            onChange={(e) => handleChange('groq_api_key', e.target.value)}
                            placeholder="gsk_..."
                            className="w-full bg-zinc-900 border border-zinc-700 rounded-lg px-4 py-2 text-zinc-100 focus:ring-2 focus:ring-brand-500 focus:border-brand-500 outline-none transition-all"
                        />
                    </div>
                </div>
            </section>

            {/* Supabase Config (Optional) */}
            <section className="space-y-4">
                <div className="flex items-center gap-2 pb-2 border-b border-zinc-800">
                    <Database className="text-brand-500" size={20} />
                    <h2 className="text-xl font-semibold text-zinc-100">Supabase (Optional)</h2>
                </div>

                <div className="grid gap-4 max-w-xl">
                    <div className="space-y-2">
                        <label className="text-sm font-medium text-zinc-300">Project URL</label>
                        <input
                            type="text"
                            value={settings.supabase_url}
                            onChange={(e) => handleChange('supabase_url', e.target.value)}
                            placeholder="https://xyz.supabase.co"
                            className="w-full bg-zinc-900 border border-zinc-700 rounded-lg px-4 py-2 text-zinc-100 focus:ring-2 focus:ring-brand-500 focus:border-brand-500 outline-none transition-all"
                        />
                    </div>
                    <div className="space-y-2">
                        <label className="text-sm font-medium text-zinc-300">Anon/Service Key</label>
                        <input
                            type="password"
                            value={settings.supabase_key}
                            onChange={(e) => handleChange('supabase_key', e.target.value)}
                            placeholder="eyJ..."
                            className="w-full bg-zinc-900 border border-zinc-700 rounded-lg px-4 py-2 text-zinc-100 focus:ring-2 focus:ring-brand-500 focus:border-brand-500 outline-none transition-all"
                        />
                    </div>
                </div>
            </section>
            {/* Processing Config */}
            <section className="space-y-4">
                <div className="flex items-center gap-2 pb-2 border-b border-zinc-800">
                    <Sliders className="text-brand-500" size={20} />
                    <h2 className="text-xl font-semibold text-zinc-100">Processing</h2>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-6 max-w-xl">
                    <div className="space-y-2">
                        <label className="text-sm font-medium text-zinc-300">Min Clip Duration (sec)</label>
                        <input
                            type="number"
                            value={settings.min_duration}
                            onChange={(e) => handleChange('min_duration', parseInt(e.target.value))}
                            min={15}
                            className="w-full bg-zinc-900 border border-zinc-700 rounded-lg px-4 py-2 text-zinc-100 focus:ring-2 focus:ring-brand-500 focus:border-brand-500 outline-none"
                        />
                    </div>
                    <div className="space-y-2">
                        <label className="text-sm font-medium text-zinc-300">Max Clip Duration (sec)</label>
                        <input
                            type="number"
                            value={settings.max_duration}
                            onChange={(e) => handleChange('max_duration', parseInt(e.target.value))}
                            max={300}
                            className="w-full bg-zinc-900 border border-zinc-700 rounded-lg px-4 py-2 text-zinc-100 focus:ring-2 focus:ring-brand-500 focus:border-brand-500 outline-none"
                        />
                    </div>
                </div>
            </section>

            {/* Subtitles */}
            <section className="space-y-4">
                <div className="flex items-center gap-2 pb-2 border-b border-zinc-800">
                    <Type className="text-brand-500" size={20} />
                    <h2 className="text-xl font-semibold text-zinc-100">Subtitles</h2>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-4 max-w-3xl">
                    {['highlight', 'karaoke', 'word-by-word'].map((style) => (
                        <div
                            key={style}
                            onClick={() => handleChange('subtitle_style', style)}
                            className={`
                cursor-pointer border rounded-xl p-4 flex flex-col items-center gap-2 transition-all
                ${settings.subtitle_style === style
                                    ? 'bg-brand-500/10 border-brand-500 ring-1 ring-brand-500'
                                    : 'bg-zinc-900 border-zinc-800 hover:border-zinc-600'}
              `}
                        >
                            <span className="capitalize font-medium text-zinc-200">{style.replace(/-/g, ' ')}</span>
                            {/* Mock visualization */}
                            <div className="w-full h-12 bg-zinc-950 rounded flex items-center justify-center text-xs text-zinc-500">
                                Preview
                            </div>
                        </div>
                    ))}
                </div>
            </section>

            <div className="pt-4 border-t border-zinc-800">
                <button
                    type="submit"
                    className="flex items-center gap-2 bg-brand-600 hover:bg-brand-500 text-white px-6 py-2.5 rounded-lg font-medium transition-colors shadow-lg shadow-brand-500/20"
                >
                    <Save size={18} />
                    {isSaved ? 'Settings Saved to .env!' : 'Save Settings'}
                </button>
            </div>

        </form>
    );
}
