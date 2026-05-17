import React, { useEffect, useState, useRef, useCallback, useMemo } from 'react';
import { Save, Loader2, Database, Key, FolderOpen, ToggleLeft, ToggleRight, ChevronUp, ChevronDown, CheckCircle2, BarChart3, Shield, FlaskConical } from 'lucide-react';
import { SettingsApi, type SettingsResponse, type UpdateSettingsRequest } from '../../lib/api';
import { DirectoryPicker } from './DirectoryPicker';
import { useAIModels } from '../../hooks/useAIModels';
import { SystemUpdateCard } from '../system/SystemUpdateCard';
import toast, { Toaster } from 'react-hot-toast';

const API_BASE = (import.meta.env?.PUBLIC_API_URL as string) || '/api';

export const SettingsForm: React.FC = () => {
    const [settings, setSettings] = useState<SettingsResponse | null>(null);
    const [formData, setFormData] = useState<UpdateSettingsRequest>({});
    const [isLoading, setIsLoading] = useState(true);
    const [isSaving, setIsSaving] = useState(false);
    const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
    const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const readyForAutoSaveRef = useRef(false);
    const [showBrowser, setShowBrowser] = useState(false);
    const [providerOrder, setProviderOrder] = useState<string[]>(['groq', 'openai', 'anthropic', 'google']);
    const [expandedProvider, setExpandedProvider] = useState<string | null>(null);

    // Telemetry consent state
    const [telemetryEnabled, setTelemetryEnabled] = useState(false);
    const [telemetryLoading, setTelemetryLoading] = useState(false);

    // Live model registry from provider APIs
    const { groupedModels, loading: modelsLoading, refetch: refetchModels } = useAIModels();

    // Settings are grouped into 4 tabs so the 500+ line form isn't an infinite scroll.
    // Tab IDs intentionally match the section order in the JSX below; changing them
    // requires updating the `activeTab === '...'` checks wrapping each <section>.
    // v0.1.0: 3 visible tabs. The 'privacy' tab was removed — there is no
    // telemetry in local-first MVP, so consent UI doesn't apply.
    type TabId = 'workspace' | 'pipeline' | 'integrations';
    const [activeTab, setActiveTab] = useState<TabId>(() => {
        if (typeof window !== 'undefined') {
            const hash = window.location.hash.replace('#', '');
            if (hash === 'workspace' || hash === 'pipeline' || hash === 'integrations') {
                return hash;
            }
        }
        return 'workspace';
    });
    const TABS: Array<{ id: TabId; label: string; icon: React.ComponentType<{ className?: string }> }> = [
        { id: 'workspace',    label: 'Workspace',    icon: FolderOpen },
        { id: 'pipeline',     label: 'Pipeline',     icon: Key },
        { id: 'integrations', label: 'Integrations', icon: Database },
    ];

    const PROVIDERS: Record<string, { name: string, desc: string, field: keyof UpdateSettingsRequest, modelField: keyof UpdateSettingsRequest, ph: string, orProvider: 'meta' | 'openai' | 'anthropic' | 'google', fallbackModels: { id: string, label: string }[] }> = {
        'groq': {
            name: 'Groq (Llama)', desc: 'Extremely fast inference', field: 'groq_api_key', modelField: 'groq_model', ph: 'gsk_...', orProvider: 'meta' as any,
            fallbackModels: [
                { id: "llama-3.3-70b-versatile", label: "Llama 3.3 70B" },
                { id: "llama-3.1-70b-versatile", label: "Llama 3.1 70B" },
            ]
        },
        'openai': {
            name: 'OpenAI (GPT / o-series)', desc: 'High quality reasoning', field: 'openai_api_key', modelField: 'openai_model', ph: 'sk-...', orProvider: 'openai' as any,
            fallbackModels: [
                { id: "gpt-4o", label: "GPT-4o" },
                { id: "gpt-4o-mini", label: "GPT-4o Mini" },
            ]
        },
        'anthropic': {
            name: 'Anthropic (Claude)', desc: 'Excellent nuance for curation', field: 'anthropic_api_key', modelField: 'anthropic_model', ph: 'sk-ant-...', orProvider: 'anthropic' as any,
            fallbackModels: [
                { id: "claude-opus-4-6", label: "Claude Opus 4.6" },
                { id: "claude-sonnet-4-6", label: "Claude Sonnet 4.6" },
                { id: "claude-haiku-3-5", label: "Claude Haiku 3.5" },
            ]
        },
        'google': {
            name: 'Google (Gemini)', desc: 'Gemini via AI Studio — simple API key', field: 'google_api_key', modelField: 'google_model', ph: 'AIza...', orProvider: 'google' as any,
            fallbackModels: [
                { id: "gemini-2.5-pro", label: "Gemini 2.5 Pro" },
                { id: "gemini-2.5-flash", label: "Gemini 2.5 Flash" },
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
    };

    // Debounced auto-save: triggers 1.5s after the last change
    const triggerAutoSave = useCallback(async () => {
        if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
        setSaveStatus('saving');
        saveTimerRef.current = setTimeout(async () => {
            try {
                const payload: UpdateSettingsRequest = { ...formData, ai_provider_order: providerOrder };
                if (payload.groq_api_key === '********' || !payload.groq_api_key) delete payload.groq_api_key;
                if (payload.openai_api_key === '********' || !payload.openai_api_key) delete payload.openai_api_key;
                if (payload.anthropic_api_key === '********' || !payload.anthropic_api_key) delete payload.anthropic_api_key;
                if (payload.google_api_key === 'AIza...' || !payload.google_api_key) delete payload.google_api_key;
                if (payload.transcript_supabase_key === '********' || !payload.transcript_supabase_key) delete payload.transcript_supabase_key;
                const updated = await SettingsApi.updateSettings(payload);
                setSettings(updated);
                setSaveStatus('saved');
                toast.success('Settings saved', { duration: 1500, icon: '✓', style: { background: '#18181b', color: '#a1a1aa', border: '1px solid rgba(255,255,255,0.05)', fontSize: '13px' } });
                setTimeout(() => setSaveStatus('idle'), 2000);
                // If any API key changed, refresh model registry so the selector shows current models
                const hasKeyChange = payload.groq_api_key || payload.openai_api_key || payload.anthropic_api_key || payload.google_api_key;
                if (hasKeyChange) {
                    SettingsApi.refreshModels().then(() => refetchModels()).catch(() => {});
                }
            } catch (error: any) {
                setSaveStatus('error');
                toast.error(error.message || 'Failed to auto-save settings');
                setTimeout(() => setSaveStatus('idle'), 3000);
            }
        }, 1500);
    }, [formData, providerOrder]);

    // Watch for changes and auto-save (skip initial load)
    useEffect(() => {
        if (!readyForAutoSaveRef.current) return;
        triggerAutoSave();
        return () => { if (saveTimerRef.current) clearTimeout(saveTimerRef.current); };
    }, [formData, providerOrder, triggerAutoSave]);

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
            // Mark ready for auto-save after React settles
            setTimeout(() => { readyForAutoSaveRef.current = true; }, 500);

            // Load telemetry consent status
            try {
                const { data: sessionData } = await (await import('../../lib/supabase')).supabase.auth.getSession();
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

    // Manual save is no longer needed — auto-save handles everything
    const handleSave = async (e: React.FormEvent) => {
        e.preventDefault();
        // Force immediate save
        if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
        setSaveStatus('saving');
        try {
            const payload: UpdateSettingsRequest = { ...formData, ai_provider_order: providerOrder };
            if (payload.groq_api_key === '********' || !payload.groq_api_key) delete payload.groq_api_key;
            if (payload.openai_api_key === '********' || !payload.openai_api_key) delete payload.openai_api_key;
            if (payload.anthropic_api_key === '********' || !payload.anthropic_api_key) delete payload.anthropic_api_key;
            if (payload.google_api_key === 'AIza...' || !payload.google_api_key) delete payload.google_api_key;
            if (payload.transcript_supabase_key === '********' || !payload.transcript_supabase_key) delete payload.transcript_supabase_key;
            const updated = await SettingsApi.updateSettings(payload);
            setSettings(updated);
            setSaveStatus('saved');
            setTimeout(() => setSaveStatus('idle'), 2000);
        } catch (error: any) {
            setSaveStatus('error');
            toast.error(error.message || 'Failed to save settings');
            setTimeout(() => setSaveStatus('idle'), 3000);
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
            <Toaster position="top-center" toastOptions={{ style: { background: '#18181b', color: '#e4e4e7', border: '1px solid rgba(255,255,255,0.1)' } }} />
            <div className="mb-8">
                <h2 className="text-3xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-white to-zinc-400">
                    Engine Settings
                </h2>
                <p className="text-zinc-500 mt-2">Configure local intelligence paths, API keys, and pipeline behaviors.</p>
            </div>

            {/* Tab navigation — keeps the long form scannable without refactoring
                the underlying state machine. Each <section> below is wrapped in a
                `activeTab === '...'` gate so only one group is visible at a time. */}
            <div className="mb-8 flex items-center gap-1 p-1 bg-zinc-900/60 border border-white/5 rounded-xl w-fit">
                {TABS.map(t => {
                    const Icon = t.icon;
                    const isActive = activeTab === t.id;
                    return (
                        <button
                            key={t.id}
                            type="button"
                            onClick={() => setActiveTab(t.id)}
                            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all ${isActive ? 'bg-brand-500/20 text-white border border-brand-500/30' : 'text-zinc-400 hover:text-white hover:bg-white/5 border border-transparent'}`}
                        >
                            <Icon className="w-4 h-4" />
                            {t.label}
                        </button>
                    );
                })}
            </div>

            <form onSubmit={handleSave} className="space-y-8">

                {/* Core Settings — Workspace tab */}
                {activeTab === 'workspace' && (<>
                <section className="bg-zinc-900/40 border border-white/5 rounded-2xl overflow-hidden">
                    <div className="px-6 py-4 border-b border-white/5 bg-black/20 flex items-center gap-2">
                        <FolderOpen className="w-5 h-5 text-brand-400" />
                        <h3 className="font-semibold text-white">Local Workspace</h3>
                    </div>
                    <div className="p-6 space-y-6">
                        <div>
                            <label className="block text-sm font-medium text-zinc-300 mb-2">
                                Podcast Name <span className="text-red-400">*</span>
                            </label>
                            <input
                                type="text"
                                value={formData.podcast_name ?? settings?.podcast_name ?? ''}
                                onChange={(e) => { setFormData(prev => ({ ...prev, podcast_name: e.target.value })); }}
                                className="w-full px-4 py-2.5 bg-black border border-zinc-800 rounded-xl focus:outline-none focus:border-brand-500 text-white"
                                placeholder="e.g. The Inminente Podcast"
                            />
                        </div>
                        <div>
                            <label className="block text-sm font-medium text-zinc-300 mb-2">
                                Podcast Root Directory <span className="text-red-400">*</span>
                            </label>
                            <div className="flex gap-2">
                                <input
                                    type="text"
                                    value={formData.podcast_dir ?? settings?.podcast_dir ?? ''}
                                    onChange={(e) => { setFormData(prev => ({ ...prev, podcast_dir: e.target.value })); }}
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
                                            const { data: sessionData } = await (await import('../../lib/supabase')).supabase.auth.getSession();
                                            const token = sessionData?.session?.access_token;
                                            const res = await fetch(`${API_BASE}/resolve-path?name=${encodeURIComponent(folderName)}`, {
                                                headers: token ? { Authorization: `Bearer ${token}` } : {},
                                            });
                                            const data = await res.json();

                                            if (data.count === 1) {
                                                setFormData(prev => ({ ...prev, podcast_dir: data.matches[0] }));
                                                toast.success(`Found: ${data.matches[0]}`, { id: 'resolve' });
                                            } else if (data.count > 1) {
                                                // Multiple matches — let user pick
                                                const choice = data.matches[0]; // Default to first
                                                setFormData(prev => ({ ...prev, podcast_dir: choice }));
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
                                    setFormData(prev => ({ ...prev, podcast_dir: path }));
                                    toast.success(`Selected: ${path}`);
                                }}
                                onClose={() => setShowBrowser(false)}
                            />
                        </div>
                    </div>
                </section>

                {/* System updates card — local-first self-update */}
                <section className="mt-6">
                    <SystemUpdateCard />
                </section>

                {/* end of Workspace tab wrapper */}
                </>)}

                {/* Pipeline tab */}
                {activeTab === 'pipeline' && (<>
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

                            // Get dynamic models from the native model registry, fallback to hardcoded if loading fails
                            const orGroup = groupedModels.find(g => g.provider === config.orProvider);
                            const dynamicModels = orGroup && orGroup.models.length > 0
                                ? orGroup.models.map(m => ({ id: m.id, label: m.name + (m.is_reasoning ? ' 🧠' : '') }))
                                : config.fallbackModels;

                            // Group models by version family for <optgroup> rendering
                            // e.g. claude-opus-4-6 and claude-sonnet-4-6 → "Claude 4.6"
                            //      gpt-4o and gpt-4o-mini → "GPT-4o"
                            //      llama-3.3-70b and llama-3.1-70b → "Llama 3.3" / "Llama 3.1"
                            const groupModelsByFamily = (models: {id: string, label: string}[]) => {
                                const groups: Record<string, {id: string, label: string}[]> = {};
                                for (const m of models) {
                                    const id = m.id.toLowerCase();
                                    let familyKey = 'Other';
                                    // Anthropic: claude-opus-4-6, claude-sonnet-4-6 → "Claude 4.6"
                                    const claudeVer = id.match(/claude-\w+-?(\d+)-(\d+)/);
                                    if (claudeVer) { familyKey = `Claude ${claudeVer[1]}.${claudeVer[2]}`; }
                                    // OpenAI: gpt-4o variants → "GPT-4o", o3/o1 → "o3" / "o1"
                                    else if (id.startsWith('gpt-4o')) { familyKey = 'GPT-4o'; }
                                    else if (id.startsWith('o3')) { familyKey = 'o3'; }
                                    else if (id.startsWith('o1')) { familyKey = 'o1'; }
                                    else if (id.startsWith('gpt-4')) { familyKey = 'GPT-4'; }
                                    // Groq / Llama: llama-3.3-70b → "Llama 3.3", llama-3.1 → "Llama 3.1"
                                    else if (id.includes('llama-3.3')) { familyKey = 'Llama 3.3'; }
                                    else if (id.includes('llama-3.1')) { familyKey = 'Llama 3.1'; }
                                    else if (id.includes('llama-3')) { familyKey = 'Llama 3'; }
                                    // Vertex / Gemini: gemini-2.5-pro → "Gemini 2.5", gemini-2.0 → "Gemini 2.0"
                                    else if (id.includes('gemini-2.5')) { familyKey = 'Gemini 2.5'; }
                                    else if (id.includes('gemini-2.0')) { familyKey = 'Gemini 2.0'; }
                                    else if (id.includes('gemini-1.5')) { familyKey = 'Gemini 1.5'; }
                                    if (!groups[familyKey]) groups[familyKey] = [];
                                    groups[familyKey].push(m);
                                }
                                return Object.entries(groups);
                            };
                            const modelFamilies = groupModelsByFamily(dynamicModels);

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
                                                    type="password"
                                                    // @ts-ignore
                                                    placeholder={settings?.[config.field] ? '********' : config.ph}
                                                    // @ts-ignore
                                                    onChange={(e) => { setFormData(prev => ({ ...prev, [config.field]: e.target.value })); }}
                                                    className="w-full px-3 py-2 bg-black border border-brand-500/30 rounded-lg focus:outline-none focus:border-brand-500 text-white font-mono text-sm shadow-[0_0_15px_rgba(168,85,247,0.1)]"
                                                />
                                            </div>
                                            <div>
                                                <label className="block text-xs font-semibold uppercase tracking-wider text-zinc-500 mb-1.5 flex justify-between items-center">
                                                    <span>Select Model</span>
                                                    {modelsLoading && <Loader2 className="w-3 h-3 text-brand-500 animate-spin" />}
                                                </label>
                                                <select
                                                    // @ts-ignore
                                                    value={formData[config.modelField] ?? settings?.[config.modelField] ?? dynamicModels[0]?.id}
                                                    // @ts-ignore
                                                    onChange={(e) => { setFormData(prev => ({ ...prev, [config.modelField]: e.target.value })); }}
                                                    className="w-full px-3 py-2 bg-black border border-brand-500/30 rounded-lg focus:outline-none focus:border-brand-500 text-white text-sm cursor-pointer hover:border-brand-500/50 transition-colors"
                                                >
                                                    {modelFamilies.length > 1
                                                        ? modelFamilies.map(([family, members]) => (
                                                            <optgroup key={family} label={`── ${family} ──`}>
                                                                {members.map(m => (
                                                                    <option key={m.id} value={m.id} className="bg-zinc-900">{m.label}</option>
                                                                ))}
                                                            </optgroup>
                                                        ))
                                                        : dynamicModels.map(m => (
                                                            <option key={m.id} value={m.id} className="bg-zinc-900 border-none">{m.label}</option>
                                                        ))
                                                    }
                                                </select>
                                                <p className="text-[10px] text-zinc-500 mt-1.5 ml-1">
                                                    {/* @ts-ignore */}
                                                    {dynamicModels.find(m => m.id === (formData[config.modelField] ?? settings?.[config.modelField] ?? dynamicModels[0]?.id))?.id}
                                                </p>
                                            </div>
                                        </div>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                </section>

                {/* end of Pipeline tab wrapper */}
                </>)}

                {/* Integrations tab */}
                {activeTab === 'integrations' && (<>
                <section className="bg-zinc-900/40 border border-white/5 rounded-2xl overflow-hidden">
                    <div className="px-6 py-4 border-b border-white/5 bg-black/20 flex items-center gap-2">
                        <Database className="w-5 h-5 text-emerald-400" />
                        <h3 className="font-semibold text-white">Transcript Source (Supabase)</h3>
                        <span className="text-[10px] bg-zinc-800 text-zinc-500 px-2 py-0.5 rounded uppercase tracking-widest border border-zinc-700 ml-auto">Optional</span>
                    </div>
                    <div className="p-6 space-y-6">
                        <p className="text-sm text-zinc-400 leading-relaxed -mt-2">
                            If you store your episode transcripts in Supabase, connect your database here so the pipeline can pull from it.
                        </p>
                        <div>
                            <label className="block text-sm font-medium text-zinc-300 mb-2">Supabase Project URL</label>
                            <input
                                type="text"
                                value={formData.transcript_supabase_url ?? settings?.transcript_supabase_url ?? ''}
                                onChange={(e) => { setFormData(prev => ({ ...prev, transcript_supabase_url: e.target.value })); }}
                                className="w-full px-4 py-2.5 bg-black border border-zinc-800 rounded-xl focus:outline-none focus:border-brand-500 text-white font-mono text-sm"
                                placeholder="https://your-project.supabase.co"
                            />
                        </div>
                        <div>
                            <label className="block text-sm font-medium text-zinc-300 mb-2">Supabase Service Key</label>
                            <input
                                type="password"
                                placeholder={settings?.transcript_supabase_key ? '********' : 'Enter Service Role Key'}
                                onChange={(e) => { setFormData(prev => ({ ...prev, transcript_supabase_key: e.target.value })); }}
                                className="w-full px-4 py-2.5 bg-black border border-zinc-800 rounded-xl focus:outline-none focus:border-brand-500 text-white font-mono"
                            />
                        </div>
                    </div>
                </section>

                {/* End of Integrations tab wrapper */}
                </>)}

                {/* Privacy tab — DISABLED in v0.1.0 (no telemetry).
                    Code preserved for v0.2 if opt-in central is reintroduced. */}
                {false && ((activeTab as string) === 'privacy') && (<>
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
                                        const { supabase } = await import('../../lib/supabase');
                                        const { data: sessionData } = await supabase.auth.getSession();
                                        if (!sessionData?.session?.access_token) {
                                            toast.error('Please log in to change telemetry settings');
                                            setTelemetryLoading(false);
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
                                            const err = await resp.json().catch(() => ({}));
                                            toast.error(err.detail || 'Failed to update telemetry');
                                        }
                                    } catch (e) {
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
                </>)}

                {/* Auto-Save Status Indicator — always visible across all tabs. */}
                <div className="sticky bottom-6 flex justify-end">
                    <div className={`flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-medium transition-all duration-300 ${saveStatus === 'saving' ? 'bg-brand-600/20 text-brand-400 border border-brand-500/30' :
                        saveStatus === 'saved' ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' :
                            saveStatus === 'error' ? 'bg-red-500/10 text-red-400 border border-red-500/20' :
                                'bg-zinc-800/50 text-zinc-500 border border-white/5'
                        }`}>
                        {saveStatus === 'saving' && <><Loader2 className="w-4 h-4 animate-spin" /> Saving...</>}
                        {saveStatus === 'saved' && <><CheckCircle2 className="w-4 h-4" /> Saved</>}
                        {saveStatus === 'error' && <><Save className="w-4 h-4" /> Save failed</>}
                        {saveStatus === 'idle' && <><Save className="w-4 h-4 opacity-50" /> Auto-save enabled</>}
                    </div>
                </div>

            </form>
        </div>
    );
};
