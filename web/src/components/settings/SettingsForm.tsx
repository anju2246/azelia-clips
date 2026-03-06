import React, { useEffect, useState } from 'react';
import { Save, Loader2, Database, Key, FolderOpen, ToggleLeft, ToggleRight, ChevronUp, ChevronDown, CheckCircle2, BarChart3, Shield } from 'lucide-react';
import { SettingsApi, type SettingsResponse, type UpdateSettingsRequest } from '../../lib/api';
import { DirectoryPicker } from './DirectoryPicker';
import { supabase } from '../../lib/supabase';
import toast from 'react-hot-toast';

const API_BASE = (import.meta.env?.PUBLIC_API_URL as string) || '/api';

export const SettingsForm: React.FC = () => {
    const [settings, setSettings] = useState<SettingsResponse | null>(null);
    const [formData, setFormData] = useState<UpdateSettingsRequest>({});
    const [isLoading, setIsLoading] = useState(true);
    const [isSaving, setIsSaving] = useState(false);
    const [isDirty, setIsDirty] = useState(false);
    const [showBrowser, setShowBrowser] = useState(false);
    const [generateTeasers, setGenerateTeasers] = useState(false);
    const [providerOrder, setProviderOrder] = useState<string[]>(['groq', 'openai', 'anthropic', 'vertex']);
    const [expandedProvider, setExpandedProvider] = useState<string | null>(null);

    // Telemetry consent state
    const [telemetryEnabled, setTelemetryEnabled] = useState(false);
    const [telemetryLoading, setTelemetryLoading] = useState(false);

    const PROVIDERS: Record<string, { name: string, desc: string, field: keyof UpdateSettingsRequest, modelField: keyof UpdateSettingsRequest, ph: string, models: { id: string, label: string }[] }> = {
        'groq': {
            name: 'Groq (Llama 3.3)', desc: 'Extremely fast inference', field: 'groq_api_key', modelField: 'groq_model', ph: 'gsk_...',
            models: [
                { id: "llama-3.3-70b-versatile", label: "Llama 3.3 70B Versatile" },
                { id: "meta-llama/llama-4-maverick-17b-128e-instruct", label: "Llama 4 Maverick 17B" },
                { id: "llama-3.1-70b-versatile", label: "Llama 3.1 70B Versatile" },
                { id: "deepseek-r1-distill-llama-70b", label: "DeepSeek R1 Distill 70B 💎" }
            ]
        },
        'openai': {
            name: 'OpenAI (GPT-4 / 5)', desc: 'High quality reasoning', field: 'openai_api_key', modelField: 'openai_model', ph: 'sk-...',
            models: [
                { id: "gpt-5.1", label: "GPT-5.1 (2026)" },
                { id: "gpt-5-mini", label: "GPT-5 mini" },
                { id: "gpt-4o-2025-xx-xx", label: "GPT-4o latest 2026" }
            ]
        },
        'anthropic': {
            name: 'Anthropic (Claude)', desc: 'Excellent nuance for curation', field: 'anthropic_api_key', modelField: 'anthropic_model', ph: 'sk-ant-...',
            models: [
                { id: "claude-opus-4-6-20260204", label: "Claude Opus 4.6" },
                { id: "claude-3.7-sonnet-20260201", label: "Claude 3.7 Sonnet" },
                { id: "claude-3.5-haiku-latest", label: "Claude 3.5 Haiku" }
            ]
        },
        'vertex': {
            name: 'Vertex AI (GCP)', desc: 'Requires local gcloud auth', field: 'gcp_project_id', modelField: 'vertex_model', ph: 'e.g. ce-video-engine',
            models: [
                { id: "gemini-3.1-pro", label: "Gemini 3.1 Pro" },
                { id: "gemini-3.1-flash-exp", label: "Gemini 3.1 Flash" },
                { id: "claude-opus-4.6", label: "Claude Opus 4.6 (Vertex)" }
            ]
        },
    };

    const moveProvider = (e: React.MouseEvent, idx: number, dir: number) => {
        e.stopPropagation();
        const newOrder = [...providerOrder];
        const temp = newOrder[idx];
        newOrder[idx] = newOrder[idx + dir];
        newOrder[idx + dir] = temp;
        setProviderOrder(newOrder);
        setIsDirty(true);
    };

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
            if (data.ai_provider_order && data.ai_provider_order.length > 0) {
                setProviderOrder(data.ai_provider_order);
            }

            // Load telemetry consent status
            try {
                const { data: sessionData } = await supabase.auth.getSession();
                if (sessionData?.session?.access_token) {
                    const telResp = await fetch(`${API_BASE}/telemetry/status`, {
                        headers: { 'Authorization': `Bearer ${sessionData.session.access_token}` }
                    });
                    if (telResp.ok) {
                        const telData = await telResp.json();
                        setTelemetryEnabled(telData.telemetry_enabled);
                    }
                }
            } catch { /* telemetry status is non-critical */ }

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
            const payload: UpdateSettingsRequest = { ...formData, ai_provider_order: providerOrder };

            if (payload.groq_api_key === '********' || !payload.groq_api_key) delete payload.groq_api_key;
            if (payload.openai_api_key === '********' || !payload.openai_api_key) delete payload.openai_api_key;
            if (payload.anthropic_api_key === '********' || !payload.anthropic_api_key) delete payload.anthropic_api_key;
            if (payload.gcp_project_id === 'e.g. ce-video-engine' || !payload.gcp_project_id) delete payload.gcp_project_id;
            if (payload.supabase_key === '********' || !payload.supabase_key) delete payload.supabase_key;

            const updated = await SettingsApi.updateSettings(payload);
            setSettings(updated);
            toast.success('Settings saved successfully', { id: loadingToast });
            setIsDirty(false);
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
                                onChange={(e) => { setFormData({ ...formData, podcast_name: e.target.value }); setIsDirty(true); }}
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
                                    onChange={(e) => { setFormData({ ...formData, podcast_dir: e.target.value }); setIsDirty(true); }}
                                    className="flex-1 px-4 py-2.5 bg-black border border-zinc-800 rounded-xl focus:outline-none focus:border-brand-500 text-white font-mono text-sm"
                                    placeholder="/Users/name/Documents/Podcasts/"
                                />
                                <button
                                    type="button"
                                    onClick={async () => {
                                        try {
                                            // @ts-ignore — File System Access API
                                            const dirHandle = await window.showDirectoryPicker({ mode: 'read' });
                                            const folderName = dirHandle.name;
                                            toast.loading(`Resolving path for "${folderName}"...`, { id: 'resolve' });

                                            // Ask server to find the full path
                                            const res = await fetch(`${API_BASE}/resolve-path?name=${encodeURIComponent(folderName)}`);
                                            const data = await res.json();

                                            if (data.count === 1) {
                                                setFormData({ ...formData, podcast_dir: data.matches[0] });
                                                setIsDirty(true);
                                                toast.success(`Found: ${data.matches[0]}`, { id: 'resolve' });
                                            } else if (data.count > 1) {
                                                // Multiple matches — let user pick
                                                const choice = data.matches[0]; // Default to first
                                                setFormData({ ...formData, podcast_dir: choice });
                                                setIsDirty(true);
                                                toast.success(`Found ${data.count} matches, using: ${choice}`, { id: 'resolve' });
                                            } else {
                                                toast.error(`Could not find "${folderName}" on disk. Try the manual picker.`, { id: 'resolve' });
                                                setShowBrowser(true);
                                            }
                                        } catch (err: any) {
                                            if (err.name === 'AbortError') return;
                                            // Fallback: native picker not supported
                                            setShowBrowser(true);
                                        }
                                    }}
                                    className="px-4 py-2.5 bg-white/5 hover:bg-white/10 border border-zinc-800 rounded-xl text-sm text-zinc-300 transition-colors flex items-center gap-2 whitespace-nowrap cursor-pointer"
                                >
                                    <FolderOpen className="w-4 h-4" /> Browse
                                </button>
                            </div>
                            <p className="text-xs text-zinc-500 mt-2">
                                Uses your native file picker. You can also type the full path manually.
                            </p>

                            {/* Fallback server-side picker for browsers without native support */}
                            <DirectoryPicker
                                isOpen={showBrowser}
                                currentPath={formData.podcast_dir ?? settings?.podcast_dir ?? ''}
                                onSelect={(path) => {
                                    setFormData({ ...formData, podcast_dir: path });
                                    setIsDirty(true);
                                    toast.success(`Selected: ${path}`);
                                }}
                                onClose={() => setShowBrowser(false)}
                            />
                        </div>
                    </div>
                </section>

                {/* API Keys */}
                <section className="bg-zinc-900/40 border border-white/5 rounded-2xl overflow-hidden">
                    <div className="px-6 py-4 border-b border-white/5 bg-black/20 flex items-center justify-between">
                        <div className="flex items-center gap-2">
                            <Key className="w-5 h-5 text-purple-400" />
                            <h3 className="font-semibold text-white">Intelligence Pipeline</h3>
                        </div>
                        <span className="text-xs text-zinc-500 bg-white/5 px-2 py-1 rounded-md">Order defines failover priority</span>
                    </div>
                    <div className="p-4 space-y-2">
                        {providerOrder.map((providerId, idx) => {
                            const config = PROVIDERS[providerId];
                            if (!config) return null;
                            const isExpanded = expandedProvider === providerId;
                            const isPrimary = idx === 0;
                            // @ts-ignore
                            const hasValue = !!settings?.[config.field] || !!formData[config.field];

                            return (
                                <div key={providerId} className={`border ${isExpanded ? 'border-brand-500/50 bg-black/40' : 'border-white/5 hover:border-white/10 bg-zinc-900/20'} rounded-xl overflow-hidden transition-all duration-200`}>
                                    <div
                                        className="p-4 flex items-center gap-4 cursor-pointer"
                                        onClick={() => setExpandedProvider(isExpanded ? null : providerId)}
                                    >
                                        {/* Reorder Controls */}
                                        <div className="flex flex-col items-center gap-1 opacity-50 hover:opacity-100">
                                            <button
                                                type="button"
                                                onClick={(e) => moveProvider(e, idx, -1)}
                                                disabled={idx === 0}
                                                className={`p-1 rounded hover:bg-white/10 ${idx === 0 ? 'invisible' : ''}`}
                                            >
                                                <ChevronUp className="w-4 h-4" />
                                            </button>
                                            <button
                                                type="button"
                                                onClick={(e) => moveProvider(e, idx, 1)}
                                                disabled={idx === providerOrder.length - 1}
                                                className={`p-1 rounded hover:bg-white/10 ${idx === providerOrder.length - 1 ? 'invisible' : ''}`}
                                            >
                                                <ChevronDown className="w-4 h-4" />
                                            </button>
                                        </div>

                                        <div className="flex-1">
                                            <div className="flex items-center gap-3">
                                                <h4 className={`font-medium ${isPrimary ? 'text-brand-400' : 'text-zinc-300'}`}>
                                                    {config.name}
                                                </h4>
                                                {isPrimary && <span className="text-[10px] uppercase tracking-wider bg-brand-500/10 text-brand-400 px-2 py-0.5 rounded border border-brand-500/20">Primary</span>}
                                                {!isPrimary && <span className="text-[10px] uppercase tracking-wider bg-zinc-800 text-zinc-500 px-2 py-0.5 rounded border border-zinc-700">Fallback {idx}</span>}
                                                {hasValue && <CheckCircle2 className="w-4 h-4 text-emerald-500 ml-auto" />}
                                            </div>
                                            <p className="text-xs text-zinc-500 mt-1">{config.desc}</p>
                                        </div>
                                    </div>

                                    {/* Expanded Input Area */}
                                    {isExpanded && (
                                        <div className="px-4 pb-4 pt-4 border-t border-white/5 bg-black/40 ml-[4.5rem] space-y-4">
                                            <div>
                                                <label className="block text-xs font-semibold uppercase tracking-wider text-zinc-500 mb-1.5">API Key / Auth</label>
                                                <input
                                                    type={providerId === 'vertex' ? 'text' : 'password'}
                                                    // @ts-ignore
                                                    placeholder={settings?.[config.field] ? '********' : config.ph}
                                                    // @ts-ignore
                                                    onChange={(e) => { setFormData({ ...formData, [config.field]: e.target.value }); setIsDirty(true); }}
                                                    className="w-full px-3 py-2 bg-black border border-brand-500/30 rounded-lg focus:outline-none focus:border-brand-500 text-white font-mono text-sm shadow-[0_0_15px_rgba(168,85,247,0.1)]"
                                                />
                                            </div>
                                            <div>
                                                <label className="block text-xs font-semibold uppercase tracking-wider text-zinc-500 mb-1.5">Select Model</label>
                                                <select
                                                    // @ts-ignore
                                                    value={formData[config.modelField] ?? settings?.[config.modelField] ?? config.models[0].id}
                                                    // @ts-ignore
                                                    onChange={(e) => { setFormData({ ...formData, [config.modelField]: e.target.value }); setIsDirty(true); }}
                                                    className="w-full px-3 py-2 bg-black border border-brand-500/30 rounded-lg focus:outline-none focus:border-brand-500 text-white text-sm cursor-pointer hover:border-brand-500/50 transition-colors"
                                                >
                                                    {config.models.map(m => (
                                                        <option key={m.id} value={m.id} className="bg-zinc-900 border-none">{m.label}</option>
                                                    ))}
                                                </select>
                                                <p className="text-[10px] text-zinc-500 mt-1.5 ml-1">
                                                    // @ts-ignore
                                                    {config.models.find(m => m.id === (formData[config.modelField] ?? settings?.[config.modelField] ?? config.models[0].id))?.id}
                                                </p>
                                            </div>
                                        </div>
                                    )}
                                </div>
                            );
                        })}
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
                                onChange={(e) => { setFormData({ ...formData, supabase_url: e.target.value }); setIsDirty(true); }}
                                className="w-full px-4 py-2.5 bg-black border border-zinc-800 rounded-xl focus:outline-none focus:border-brand-500 text-white font-mono text-sm"
                            />
                        </div>
                        <div>
                            <label className="block text-sm font-medium text-zinc-300 mb-2">Supabase Service Key</label>
                            <input
                                type="password"
                                placeholder={settings?.supabase_key ? '********' : 'Enter Service Role Key'}
                                onChange={(e) => { setFormData({ ...formData, supabase_key: e.target.value }); setIsDirty(true); }}
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

                {/* Telemetry & Collective Intelligence */}
                <section className="bg-zinc-900/40 border border-white/5 rounded-2xl overflow-hidden">
                    <div className="p-6">
                        <div className="flex items-start justify-between">
                            <div className="space-y-1 pr-6">
                                <h3 className="font-semibold text-white flex items-center gap-2">
                                    <BarChart3 className="w-5 h-5 text-brand-400" /> Collective Intelligence (Telemetry)
                                </h3>
                                <p className="text-sm text-zinc-400 leading-relaxed">
                                    Share anonymized clip metrics (scores, durations, hook types) to power the IC Engine.
                                    <strong className="text-zinc-300"> We never upload video, audio, or transcripts.</strong>
                                </p>
                                <div className="flex items-center gap-2 mt-2">
                                    <Shield className="w-3.5 h-3.5 text-green-400" />
                                    <span className="text-xs text-green-400/80">Data is anonymized before leaving your machine</span>
                                </div>
                            </div>
                            <button
                                type="button"
                                disabled={telemetryLoading}
                                onClick={async () => {
                                    setTelemetryLoading(true);
                                    try {
                                        const { data: sessionData } = await supabase.auth.getSession();
                                        if (!sessionData?.session?.access_token) {
                                            toast.error('Not authenticated');
                                            return;
                                        }
                                        const resp = await fetch(`${API_BASE}/telemetry/consent`, {
                                            method: 'POST',
                                            headers: {
                                                'Authorization': `Bearer ${sessionData.session.access_token}`,
                                                'Content-Type': 'application/json',
                                            },
                                            body: JSON.stringify({ enabled: !telemetryEnabled }),
                                        });
                                        if (resp.ok) {
                                            const result = await resp.json();
                                            setTelemetryEnabled(result.telemetry_enabled);
                                            toast.success(result.message);
                                        } else {
                                            toast.error('Failed to update telemetry');
                                        }
                                    } catch {
                                        toast.error('Failed to update telemetry');
                                    } finally {
                                        setTelemetryLoading(false);
                                    }
                                }}
                                className={`cursor-pointer transition-colors flex-shrink-0 ${telemetryEnabled ? 'text-brand-500' : 'text-zinc-600'} ${telemetryLoading ? 'opacity-50' : ''}`}
                            >
                                {telemetryEnabled ? <ToggleRight className="w-10 h-10" /> : <ToggleLeft className="w-10 h-10" />}
                            </button>
                        </div>
                    </div>
                </section>

                {/* Action Bar */}
                <div className="sticky bottom-6 flex justify-end">
                    <button
                        type="submit"
                        disabled={isSaving || !isDirty}
                        className={`cursor-pointer flex items-center gap-2 px-8 py-3 rounded-xl font-medium transition-all disabled:cursor-not-allowed ${isDirty
                            ? 'bg-brand-600 hover:bg-brand-500 text-white shadow-lg shadow-brand-500/20'
                            : 'bg-zinc-800 text-zinc-500'
                            } disabled:opacity-50`}
                    >
                        {isSaving ? <Loader2 className="w-5 h-5 animate-spin" /> : <Save className="w-5 h-5" />}
                        {isSaving ? 'Saving...' : isDirty ? 'Save Configuration' : 'No Changes'}
                    </button>
                </div>

            </form>
        </div>
    );
};
