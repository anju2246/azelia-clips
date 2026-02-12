import React, { useState, useEffect } from 'react';
import { Save, Key, Sliders, Type } from 'lucide-react';

export default function SettingsForm() {
    const [groqKey, setGroqKey] = useState('');
    const [minDuration, setMinDuration] = useState(30);
    const [maxDuration, setMaxDuration] = useState(90);
    const [subtitleStyle, setSubtitleStyle] = useState('highlight');
    const [isSaved, setIsSaved] = useState(false);

    // Load from localStorage on mount
    useEffect(() => {
        const saved = localStorage.getItem('celia-settings');
        if (saved) {
            const parsed = JSON.parse(saved);
            setGroqKey(parsed.groqKey || '');
            setMinDuration(parsed.minDuration || 30);
            setMaxDuration(parsed.maxDuration || 90);
            setSubtitleStyle(parsed.subtitleStyle || 'highlight');
        }
    }, []);

    const handleSave = (e: React.FormEvent) => {
        e.preventDefault();
        const settings = {
            groqKey,
            minDuration,
            maxDuration,
            subtitleStyle
        };
        localStorage.setItem('celia-settings', JSON.stringify(settings));
        setIsSaved(true);
        setTimeout(() => setIsSaved(false), 2000);
    };

    return (
        <form onSubmit={handleSave} className="space-y-8">

            {/* API Keys Section */}
            <section className="space-y-4">
                <div className="flex items-center gap-2 pb-2 border-b border-zinc-800">
                    <Key className="text-brand-500" size={20} />
                    <h2 className="text-xl font-semibold text-zinc-100">API Keys</h2>
                </div>

                <div className="grid gap-4 max-w-xl">
                    <div className="space-y-2">
                        <label className="text-sm font-medium text-zinc-300">Groq API Key (Required)</label>
                        <input
                            type="password"
                            value={groqKey}
                            onChange={(e) => setGroqKey(e.target.value)}
                            placeholder="gsk_..."
                            className="w-full bg-zinc-900 border border-zinc-700 rounded-lg px-4 py-2 text-zinc-100 focus:ring-2 focus:ring-brand-500 focus:border-brand-500 outline-none transition-all"
                        />
                        <p className="text-xs text-zinc-500">Used for fast transcription and local LLM inference.</p>
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
                            value={minDuration}
                            onChange={(e) => setMinDuration(parseInt(e.target.value))}
                            min={15}
                            className="w-full bg-zinc-900 border border-zinc-700 rounded-lg px-4 py-2 text-zinc-100 focus:ring-2 focus:ring-brand-500 focus:border-brand-500 outline-none"
                        />
                    </div>
                    <div className="space-y-2">
                        <label className="text-sm font-medium text-zinc-300">Max Clip Duration (sec)</label>
                        <input
                            type="number"
                            value={maxDuration}
                            onChange={(e) => setMaxDuration(parseInt(e.target.value))}
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
                            onClick={() => setSubtitleStyle(style)}
                            className={`
                cursor-pointer border rounded-xl p-4 flex flex-col items-center gap-2 transition-all
                ${subtitleStyle === style
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
                    {isSaved ? 'Settings Saved!' : 'Save Settings'}
                </button>
            </div>

        </form>
    );
}
