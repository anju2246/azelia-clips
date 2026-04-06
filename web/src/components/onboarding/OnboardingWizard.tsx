import React, { useEffect, useRef, useState } from 'react';
import { SettingsApi, type UpdateSettingsRequest } from '../../lib/api';
import { supabase } from '../../lib/supabase';
import { DirectoryPicker } from '../settings/DirectoryPicker';
import { ChevronDown, ChevronRight, Key, Loader2, Sparkles, FolderOpen, ArrowRight, ArrowLeft, CheckCircle2, User, Target, BarChart, Youtube, Link as LinkIcon, Shield } from 'lucide-react';
import toast from 'react-hot-toast';
import { RetroactiveSyncModal } from '../analytics/RetroactiveSyncModal';
import { useAIModels } from '../../hooks/useAIModels';
import { ProUpgradeCard } from '../upgrade/ProUpgradeCard';

const API_BASE = (import.meta.env?.PUBLIC_API_URL as string) || '/api';

async function fetchWithAuth(endpoint: string, options: RequestInit = {}) {
    const headers = new Headers(options.headers || {});
    try {
        const { data } = await supabase.auth.getSession();
        if (data?.session?.access_token) {
            headers.set('Authorization', `Bearer ${data.session.access_token}`);
        }
    } catch (e) { /* continue */ }
    return fetch(`${API_BASE}${endpoint}`, { ...options, headers });
}

export const OnboardingWizard: React.FC = () => {
    const [showProCard, setShowProCard] = useState(false);
    const [step, setStep] = useState<1 | 2 | 3 | 4>(() => {
        if (typeof window !== 'undefined') {
            const saved = localStorage.getItem('az_onboard_step');
            if (saved) return parseInt(saved) as 1 | 2 | 3 | 4;
        }
        return 1;
    });
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [showDirPicker, setShowDirPicker] = useState(false);
    const boxRef = useRef<HTMLDivElement>(null);

    // Core settings
    const [formData, setFormData] = useState<Partial<UpdateSettingsRequest>>({});

    // New Model-Centric Selection
    const [selectedModelId, setSelectedModelId] = useState<string>('');

    // Strategic Profiling (Step 2)
    const [profile, setProfile] = useState(() => {
        if (typeof window !== 'undefined') {
            const saved = localStorage.getItem('az_onboard_profile');
            if (saved) return JSON.parse(saved);
        }
        return {
            content_niche: '',
            user_role: '',
            primary_goal: '',
            region: '',
            episode_format: ''
        };
    });

    // Telemetry (Step 3) - Opt-in: default OFF, user must explicitly enable
    const [telemetry, setTelemetry] = useState(() => {
        if (typeof window !== 'undefined') {
            return localStorage.getItem('az_onboard_telemetry') === 'true';
        }
        return false;
    });

    // Terms & Conditions
    const [acceptedTerms, setAcceptedTerms] = useState(false);

    // YouTube connection state
    const [ytConnected, setYtConnected] = useState(false);
    const [ytChannelName, setYtChannelName] = useState('');
    const [ytConnecting, setYtConnecting] = useState(false);
    const [ytChannels, setYtChannels] = useState<any[]>([]);
    const [ytAccessToken, setYtAccessToken] = useState<string | null>(null);
    const [ytShowPicker, setYtShowPicker] = useState(false);
    const [ytManualHandle, setYtManualHandle] = useState('');
    const [showRetroactiveModal, setShowRetroactiveModal] = useState(false);
    const [hasSyncedHistorical, setHasSyncedHistorical] = useState(() => {
        if (typeof window !== 'undefined') {
            return localStorage.getItem('az_historical_synced') === 'true';
        }
        return false;
    });

    // AI Provider config — selected provider
    const [selectedProvider, setSelectedProvider] = useState<string>('');
    const { groupedModels } = useAIModels();

    const PROVIDERS: Record<string, { name: string, desc: string, color: string, field: keyof UpdateSettingsRequest, modelField: keyof UpdateSettingsRequest, ph: string, keyUrl: string, models: { id: string, label: string, badge?: string }[] }> = {
        'anthropic': {
            name: 'Anthropic (Claude)', desc: 'Excelente para curación de contenido', color: 'border-orange-500/50 bg-orange-500/10',
            field: 'anthropic_api_key', modelField: 'anthropic_model', ph: 'sk-ant-...',
            keyUrl: 'https://console.anthropic.com/settings/keys',
            models: groupedModels.find(g => g.provider === 'anthropic')?.models.map(m => ({ id: m.id, label: m.name })) || []
        },
        'openai': {
            name: 'OpenAI (GPT)', desc: 'Razonamiento de alta calidad', color: 'border-green-500/50 bg-green-500/10',
            field: 'openai_api_key', modelField: 'openai_model', ph: 'sk-...',
            keyUrl: 'https://platform.openai.com/api-keys',
            models: groupedModels.find(g => g.provider === 'openai')?.models.map(m => ({ id: m.id, label: m.name })) || []
        },
        'groq': {
            name: 'Groq (Llama)', desc: 'Inferencia ultra rapida, gratis limitado', color: 'border-yellow-500/50 bg-yellow-500/10',
            field: 'groq_api_key', modelField: 'groq_model', ph: 'gsk_...',
            keyUrl: 'https://console.groq.com/keys',
            models: groupedModels.find(g => g.provider === 'groq')?.models.map(m => ({ id: m.id, label: m.name })) || []
        },
        'vertex': {
            name: 'Google (Vertex AI)', desc: 'Requiere gcloud auth local', color: 'border-blue-500/50 bg-blue-500/10',
            field: 'gcp_project_id', modelField: 'vertex_model', ph: 'mi-proyecto-gcp',
            keyUrl: 'https://console.cloud.google.com',
            models: groupedModels.find(g => g.provider === 'vertex')?.models.map(m => ({ id: m.id, label: m.name })) || []
        },
    };

    const providerOrder = ['anthropic', 'openai', 'groq', 'vertex'];

    const NICHES = ['Negocios & Emprendimiento', 'Comedia', 'Educación & Ciencia', 'Tecnología', 'True Crime', 'Gaming', 'Salud & Fitness', 'Estilo de Vida'];
    const ROLES = [
        { id: 'solo_creator', label: 'Creador Local / Solitario' },
        { id: 'video_editor', label: 'Editor de Video Freelance' },
        { id: 'agency', label: 'Agencia (Multi-cliente)' },
        { id: 'network_producer', label: 'Productor de Network' }
    ];
    const GOALS = [
        { id: 'grow_audience', label: 'Crecer mi Audiencia (Viralidad)' },
        { id: 'save_time', label: 'Ahorrar Tiempo de Edición' },
        { id: 'monetize', label: 'Monetizar / Vender Productos' }
    ];
    const REGIONS = [
        { id: 'Mexico', label: 'México' },
        { id: 'Colombia', label: 'Colombia' },
        { id: 'Argentina', label: 'Argentina' },
        { id: 'Spain', label: 'España' },
        { id: 'USA', label: 'Estados Unidos' },
        { id: 'Chile', label: 'Chile' },
        { id: 'Peru', label: 'Perú' },
    ];
    const FORMATS = [
        { id: 'interview', label: 'Entrevista (Host + Invitado)' },
        { id: 'solo', label: 'Solo / Monólogo' },
        { id: 'co_host', label: 'Co-hosts (2+ presentadores)' },
        { id: 'panel', label: 'Panel (3+ participantes)' },
        { id: 'narrative', label: 'Narrativo / Storytelling' },
    ];

    useEffect(() => {
        const init = async () => {
            try {
                const existing = await SettingsApi.getSettings();
                const savedForm = localStorage.getItem('az_onboard_form');
                if (savedForm) {
                    setFormData({ ...existing, ...JSON.parse(savedForm) });
                } else {
                    setFormData(existing);
                }
            } catch (e) {
                console.warn("Could not load existing settings", e);
            }

            // Check for YouTube OAuth callback
            const urlParams = new URLSearchParams(window.location.search);
            const code = urlParams.get('code');
            if (code) {
                window.history.replaceState({}, '', window.location.pathname);
                setStep(3);
                setLoading(false);
                handleYouTubeCallback(code);
                return;
            }

            // Check if YouTube is already connected
            try {
                const res = await fetchWithAuth('/analytics/youtube/status');
                if (res.ok) {
                    const data = await res.json();
                    if (data.connected) {
                        setYtConnected(true);
                        setYtChannelName(data.channel_name || 'Connected');
                    }
                }
            } catch (e) { /* not connected */ }

            setLoading(false);
        };
        init();
    }, []);
    // Save state to localStorage as it changes
    useEffect(() => {
        if (typeof window !== 'undefined') {
            localStorage.setItem('az_onboard_step', String(step));
            localStorage.setItem('az_onboard_profile', JSON.stringify(profile));
            localStorage.setItem('az_onboard_telemetry', String(telemetry));
            localStorage.setItem('az_historical_synced', String(hasSyncedHistorical));
            if (Object.keys(formData).length > 0) {
                localStorage.setItem('az_onboard_form', JSON.stringify(formData));
            }
        }
    }, [step, profile, telemetry, formData]);

    useEffect(() => {
        boxRef.current?.scrollTo({ top: 0, behavior: 'smooth' });
    }, [step]);

    const handleUpdate = (updates: Partial<UpdateSettingsRequest>) => {
        setFormData(prev => ({ ...prev, ...updates }));
    };

    const handleNext = () => setStep(prev => (prev + 1) as 1 | 2 | 3 | 4);
    const handlePrev = () => setStep(prev => (prev - 1) as 1 | 2 | 3 | 4);

    const handleFinish = async () => {
        setSaving(true);
        try {
            // 1. Sync Profile to Supabase (Central DB)
            const { data: { user } } = await supabase.auth.getUser();
            if (user) {
                await supabase.from('profiles').update({
                    content_niche: profile.content_niche,
                    user_role: profile.user_role,
                    primary_goal: profile.primary_goal,
                    preferences: {
                        region: profile.region,
                        episode_format: profile.episode_format,
                    }
                }).eq('id', user.id);
            }

            // 2. Sync Local Settings (Env)
            await SettingsApi.updateSettings({ ...formData });

            // 3. Save Telemetry Consent via API
            try {
                await fetchWithAuth('/telemetry/consent', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ enabled: telemetry }),
                });
            } catch { /* non-critical — telemetry preference saved on next settings visit */ }
            // 4. Clear local storage checkpoints & mark as complete (DB + localStorage)
            localStorage.removeItem('az_onboard_step');
            localStorage.removeItem('az_onboard_profile');
            localStorage.removeItem('az_onboard_telemetry');
            localStorage.removeItem('az_onboard_form');
            localStorage.setItem('az_onboarding_complete', 'true');
            try {
                await fetchWithAuth('/auth/onboarding-complete', { method: 'POST' });
            } catch { /* non-critical — gate will re-check on next login */ }

            toast.success("¡Bienvenido a Azelia Clips!");
            setShowProCard(true);

        } catch (e) {
            console.error("Failed to save onboarding data", e);
            toast.error("Hubo un error guardando tu perfil.");
            setSaving(false);
        }
    };

    const handleYouTubeConnect = async () => {
        try {
            // Google OAuth requires exact string matching for redirect URIs, and generally prefers localhost over IPs.
            const baseOrigin = window.location.origin.replace('127.0.0.1', 'localhost').replace('0.0.0.0', 'localhost');
            const redirectUri = baseOrigin + '/onboarding';
            const res = await fetchWithAuth(`/auth/youtube/authorize?redirect_uri=${encodeURIComponent(redirectUri)}`);
            if (!res.ok) throw new Error('Failed to start authorization');
            const { url } = await res.json();
            window.location.href = url;
        } catch (error: any) {
            toast.error(error.message || 'Failed to connect YouTube');
        }
    };

    const handleYouTubeCallback = async (code: string) => {
        setYtConnecting(true);
        const toastId = toast.loading('Connecting YouTube...');
        try {
            const baseOrigin = window.location.origin.replace('127.0.0.1', 'localhost').replace('0.0.0.0', 'localhost');
            const redirectUri = baseOrigin + '/onboarding';
            const res = await fetchWithAuth('/analytics/youtube/sync-with-code', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ code, redirect_uri: redirectUri })
            });
            if (!res.ok) throw new Error((await res.json()).detail || 'Connection failed');
            const result = await res.json();

            if (result.needs_channel_selection) {
                toast.dismiss(toastId);
                setYtChannels(result.channels || []);
                setYtAccessToken(result.access_token);
                setYtShowPicker(true);
                toast.success(`Found ${result.channels?.length || 0} channel(s). Pick the one to sync.`, { icon: '📺' });
            } else {
                toast.success(`Connected! Synced ${result.total_shorts} videos from ${result.channel_name}.`, { id: toastId, icon: '🔗' });
                setYtConnected(true);
                setYtChannelName(result.channel_name);
                if (!hasSyncedHistorical) {
                    setTimeout(() => setShowRetroactiveModal(true), 1500);
                }
            }
        } catch (error: any) {
            toast.error(error.message || 'Connection failed', { id: toastId });
        } finally {
            setYtConnecting(false);
        }
    };

    const handleYtSelectChannel = async (channelId: string) => {
        if (!ytAccessToken) return;
        setYtConnecting(true);
        const toastId = toast.loading('Syncing channel...');
        try {
            const res = await fetchWithAuth('/analytics/youtube/sync-with-code', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ access_token: ytAccessToken, channel_id: channelId })
            });
            if (!res.ok) throw new Error((await res.json()).detail || 'Sync failed');
            const result = await res.json();
            toast.success(`Synced ${result.total_shorts} videos from ${result.channel_name}!`, { id: toastId, icon: '🎬' });
            setYtConnected(true);
            setYtChannelName(result.channel_name);
            setYtShowPicker(false);
            if (!hasSyncedHistorical) {
                setTimeout(() => setShowRetroactiveModal(true), 1500);
            }
        } catch (error: any) {
            toast.error(error.message || 'Sync failed', { id: toastId });
        } finally {
            setYtConnecting(false);
        }
    };

    const handleYtManualHandle = async () => {
        if (!ytAccessToken || !ytManualHandle.trim()) return;
        let handle = ytManualHandle.trim();
        if (handle.includes('youtube.com/')) {
            const match = handle.match(/@[\w-]+/);
            if (match) handle = match[0];
        }
        if (!handle.startsWith('@')) handle = `@${handle}`;
        setYtConnecting(true);
        const toastId = toast.loading(`Looking up ${handle}...`);
        try {
            const searchRes = await fetch(
                `https://www.googleapis.com/youtube/v3/channels?part=snippet,statistics,contentDetails&forHandle=${encodeURIComponent(handle.replace('@', ''))}`,
                { headers: { Authorization: `Bearer ${ytAccessToken}` } }
            );
            if (!searchRes.ok) throw new Error(`Channel ${handle} not found`);
            const data = await searchRes.json();
            if (!data.items?.length) throw new Error(`Channel ${handle} not found`);
            toast.dismiss(toastId);
            await handleYtSelectChannel(data.items[0].id);
        } catch (error: any) {
            toast.error(error.message || 'Channel not found', { id: toastId });
            setYtConnecting(false);
        }
    };

    const handleSocialConnect = (platform: string) => {
        toast('Próximamente — TikTok integration', { icon: '🔜' });
    };

    const hasAnyKey = [formData.groq_api_key, formData.openai_api_key, formData.anthropic_api_key, formData.gcp_project_id].some(
        key => typeof key === 'string' && key.trim().length >= 20 && !key.includes('...')
    );

    if (loading) return (
        <div className="flex justify-center items-center py-20"><Loader2 className="w-8 h-8 text-brand-500 animate-spin" /></div>
    );

    if (showProCard) return (
        <div className="bg-zinc-900/60 border border-white/10 rounded-3xl p-8 backdrop-blur-xl shadow-2xl space-y-4">
            <div>
                <h2 className="text-2xl font-bold text-white">¡Ya estás listo!</h2>
                <p className="text-zinc-400 mt-1">Una última cosa antes de entrar al dashboard.</p>
            </div>
            <ProUpgradeCard onActivated={() => window.location.replace('/dashboard')} />
            <button
                onClick={() => window.location.replace('/dashboard')}
                className="w-full text-center text-xs text-zinc-500 hover:text-zinc-400 transition-colors py-1"
            >
                Continuar con Free por ahora →
            </button>
        </div>
    );

    return (
        <div ref={boxRef} className="bg-zinc-900/60 border border-white/10 rounded-3xl p-8 backdrop-blur-xl shadow-2xl relative transition-all duration-500 h-[75vh] overflow-y-auto">
            {/* Progress indicator */}
            <div className="flex items-center gap-2 mb-8">
                {[1, 2, 3, 4].map((i) => (
                    <div key={i} className={`flex-1 h-1.5 rounded-full transition-colors duration-300 ${step >= i ? 'bg-brand-500 shadow-[0_0_10px_rgba(168,85,247,0.5)]' : 'bg-zinc-800'}`} />
                ))}
            </div>

            {/* STEP 1: WORKSPACE */}
            {step === 1 && (
                <div className="space-y-6 animate-in fade-in slide-in-from-right-4 duration-500">
                    <div>
                        <h1 className="text-3xl font-bold bg-gradient-to-r from-white to-zinc-400 bg-clip-text text-transparent">Configuremos tu espacio</h1>
                        <p className="text-zinc-400 mt-2 text-lg">Azelia analiza tus videos localmente. Dile cómo se llama tu proyecto y dónde encontrar el material.</p>
                    </div>

                    <div className="space-y-5 mt-8">
                        <div>
                            <label className="block text-sm font-medium text-zinc-300 mb-2">Nombre del Podcast</label>
                            <input
                                type="text"
                                className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-3 text-white placeholder-zinc-600 focus:outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500 transition-all font-mono"
                                placeholder="Ej: The Inminente Podcast"
                                value={formData.podcast_name || ''}
                                onChange={(e) => handleUpdate({ podcast_name: e.target.value })}
                            />
                        </div>

                        <div>
                            <label className="block text-sm font-medium text-zinc-300 mb-2">Directorio de Videos Base</label>
                            <div className="flex gap-2">
                                <input
                                    type="text"
                                    value={formData.podcast_dir || ''}
                                    onChange={(e) => handleUpdate({ podcast_dir: e.target.value })}
                                    className="flex-1 bg-black/40 border border-white/10 rounded-xl px-4 py-3 text-white placeholder-zinc-600 focus:outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500 transition-all font-mono text-sm"
                                    placeholder="/Users/name/Documents/Podcasts/"
                                />
                                <button
                                    type="button"
                                    onClick={async () => {
                                        try {
                                            // @ts-ignore — File System Access API
                                            const dirHandle = await window.showDirectoryPicker({ mode: 'read' });
                                            const folderName = dirHandle.name;
                                            toast.loading(`Buscando "${folderName}"...`, { id: 'resolve' });

                                            const API_BASE = (import.meta.env?.PUBLIC_API_URL as string) || '/api';
                                            const res = await fetch(`${API_BASE}/resolve-path?name=${encodeURIComponent(folderName)}`);
                                            const data = await res.json();

                                            if (data.count === 1) {
                                                handleUpdate({ podcast_dir: data.matches[0] });
                                                toast.success(`Encontrado: ${data.matches[0]}`, { id: 'resolve' });
                                            } else if (data.count > 1) {
                                                handleUpdate({ podcast_dir: data.matches[0] });
                                                toast.success(`${data.count} coincidencias, usando: ${data.matches[0]}`, { id: 'resolve' });
                                            } else {
                                                toast.error(`No se encontró "${folderName}". Usa el picker manual.`, { id: 'resolve' });
                                                setShowDirPicker(true);
                                            }
                                        } catch (err: any) {
                                            if (err.name === 'AbortError') return;
                                            setShowDirPicker(true);
                                        }
                                    }}
                                    className="px-4 py-3 bg-white/5 hover:bg-white/10 border border-white/10 rounded-xl text-sm text-zinc-300 transition-colors flex items-center gap-2 whitespace-nowrap cursor-pointer"
                                >
                                    <FolderOpen className="w-4 h-4" /> Buscar
                                </button>
                            </div>
                            <p className="text-xs text-zinc-500 mt-2">Usa el selector nativo o escribe la ruta. Los videos deben estar aquí o en subcarpetas.</p>

                            {/* Fallback: server-side picker */}
                            <DirectoryPicker
                                isOpen={showDirPicker}
                                currentPath={formData.podcast_dir || ''}
                                onSelect={(path) => handleUpdate({ podcast_dir: path })}
                                onClose={() => setShowDirPicker(false)}
                            />
                        </div>

                    </div>

                    <div className="flex items-center justify-between pt-8 border-t border-white/10 mt-8">
                        <button onClick={handleNext} className="text-zinc-500 hover:text-white transition-colors text-sm font-medium">
                            Saltar (Subiré manuales)
                        </button>
                        <button onClick={handleNext} disabled={!formData.podcast_name} className="flex items-center gap-2 px-6 py-3 bg-white text-black font-semibold rounded-xl hover:bg-zinc-200 focus:ring-4 focus:ring-white/20 transition-all disabled:opacity-50">
                            Siguiente <ArrowRight className="w-4 h-4" />
                        </button>
                    </div>
                </div>
            )}

            {/* STEP 2: STRATEGIC PROFILING */}
            {step === 2 && (
                <div className="space-y-6 animate-in fade-in slide-in-from-right-4 duration-500">
                    <div>
                        <h1 className="text-3xl font-bold bg-gradient-to-r from-white to-zinc-400 bg-clip-text text-transparent">Conozcámonos un poco</h1>
                        <p className="text-zinc-400 mt-2 text-lg">Esta información afina los algoritmos de recomendación de Azelia para tu nicho específico.</p>
                    </div>

                    <div className="space-y-6 mt-6">
                        <div>
                            <label className="flex items-center gap-2 text-sm font-medium text-zinc-300 mb-3"><User className="w-4 h-4 text-brand-400" /> ¿Cuál es tu rol principal?</label>
                            <div className="grid grid-cols-2 gap-3">
                                {ROLES.map(r => (
                                    <button
                                        key={r.id}
                                        onClick={() => setProfile({ ...profile, user_role: r.id })}
                                        className={`px-4 py-3 rounded-xl border text-left text-sm transition-all ${profile.user_role === r.id ? 'bg-brand-500/20 border-brand-500 text-white' : 'bg-black/20 border-white/5 hover:border-white/20 text-zinc-400'}`}
                                    >
                                        {r.label}
                                    </button>
                                ))}
                            </div>
                        </div>

                        <div>
                            <label className="flex items-center gap-2 text-sm font-medium text-zinc-300 mb-3"><Target className="w-4 h-4 text-brand-400" /> ¿Cuál es tu objetivo?</label>
                            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                                {GOALS.map(g => (
                                    <button
                                        key={g.id}
                                        onClick={() => setProfile({ ...profile, primary_goal: g.id })}
                                        className={`px-4 py-3 rounded-xl border text-center text-sm transition-all ${profile.primary_goal === g.id ? 'bg-brand-500/20 border-brand-500 text-white' : 'bg-black/20 border-white/5 hover:border-white/20 text-zinc-400'}`}
                                    >
                                        {g.label}
                                    </button>
                                ))}
                            </div>
                        </div>

                        <div>
                            <label className="block text-sm font-medium text-zinc-300 mb-3 ml-1">Nicho del Contenido</label>
                            <select
                                value={profile.content_niche}
                                onChange={(e) => setProfile({ ...profile, content_niche: e.target.value })}
                                className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-3 text-white appearance-none focus:border-brand-500 outline-none"
                            >
                                <option value="" disabled>Selecciona un nicho principal...</option>
                                {NICHES.map(n => <option key={n} value={n} className="bg-zinc-900">{n}</option>)}
                            </select>
                        </div>

                        <div>
                            <label className="block text-sm font-medium text-zinc-300 mb-3 ml-1">Región Principal</label>
                            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                                {REGIONS.map(r => (
                                    <button
                                        key={r.id}
                                        onClick={() => setProfile({ ...profile, region: r.id })}
                                        className={`px-4 py-3 rounded-xl border text-center text-sm transition-all ${profile.region === r.id ? 'bg-brand-500/20 border-brand-500 text-white' : 'bg-black/20 border-white/5 hover:border-white/20 text-zinc-400'}`}
                                    >
                                        {r.label}
                                    </button>
                                ))}
                            </div>
                        </div>

                        <div>
                            <label className="block text-sm font-medium text-zinc-300 mb-3 ml-1">Formato de Episodio</label>
                            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                                {FORMATS.map(f => (
                                    <button
                                        key={f.id}
                                        onClick={() => setProfile({ ...profile, episode_format: f.id })}
                                        className={`px-4 py-3 rounded-xl border text-center text-sm transition-all ${profile.episode_format === f.id ? 'bg-brand-500/20 border-brand-500 text-white' : 'bg-black/20 border-white/5 hover:border-white/20 text-zinc-400'}`}
                                    >
                                        {f.label}
                                    </button>
                                ))}
                            </div>
                        </div>
                    </div>

                    <div className="flex items-center justify-between pt-8 border-t border-white/10 mt-8">
                        <button onClick={handlePrev} className="text-zinc-400 hover:text-white transition-colors text-sm font-medium flex items-center gap-2">
                            <ArrowLeft className="w-4 h-4" /> Atrás
                        </button>
                        <button onClick={handleNext} disabled={!profile.user_role || !profile.primary_goal || !profile.content_niche} className="flex items-center gap-2 px-6 py-3 bg-white text-black font-semibold rounded-xl hover:bg-zinc-200 focus:ring-4 focus:ring-white/20 transition-all disabled:opacity-50">
                            Siguiente <ArrowRight className="w-4 h-4" />
                        </button>
                    </div>
                </div>
            )}

            {/* STEP 3: SOCIAL & TELEMETRY */}
            {step === 3 && (
                <div className="space-y-6 animate-in fade-in slide-in-from-right-4 duration-500">
                    <div>
                        <h1 className="text-3xl font-bold bg-gradient-to-r from-white to-zinc-400 bg-clip-text text-transparent">Expande el Cerebro</h1>
                        <p className="text-zinc-400 mt-2 text-lg">Conecta tus redes y únete al motor colectivo que hace que los clips sean más virales cada día.</p>
                    </div>

                    <div className="space-y-6 mt-6">
                        {/* Telemetry Card */}
                        <div className={`p-5 rounded-2xl border transition-all ${telemetry ? 'bg-brand-500/10 border-brand-500/30' : 'bg-zinc-900/50 border-white/10'}`}>
                            <div className="flex items-start justify-between">
                                <div className="space-y-1 pr-6">
                                    <h3 className="text-white font-medium flex items-center gap-2">
                                        <BarChart className="w-4 h-4 text-brand-400" /> Inteligencia Colectiva (Telemetría)
                                    </h3>
                                    <p className="text-sm text-zinc-400 leading-relaxed">
                                        ¿Quieres que tus clips sean cada vez más virales? Azelia aprende de la comunidad. Al unirte, envías datos anónimos sobre métricas de retención y qué hooks logran más vistas en tu nicho.
                                        <br /><br />
                                        <strong className="text-brand-300">¿Por qué activarlo?</strong><br />
                                        • Mejoras el algoritmo de tu propio nicho.<br />
                                        • Obtienes prioridad en nuevas funciones "Beta".<br />
                                        • NUNCA enviamos tus videos, audios ni guiones. Solo números y clasificaciones.
                                    </p>
                                </div>
                                <label className="relative inline-flex items-center cursor-pointer flex-shrink-0 mt-1">
                                    <input type="checkbox" className="sr-only peer" checked={telemetry} onChange={(e) => setTelemetry(e.target.checked)} />
                                    <div className="w-11 h-6 bg-zinc-700 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-brand-500"></div>
                                </label>
                            </div>
                        </div>

                        {/* Social Connections */}
                        <div className="pt-4">
                            <h4 className="text-sm font-medium text-zinc-300 mb-3 flex items-center gap-2"><LinkIcon className="w-4 h-4" /> Conexiones Sociales</h4>
                            <div className="space-y-3">
                                {/* YouTube Button */}
                                {ytConnected ? (
                                    <div className="p-4 rounded-xl bg-green-500/10 border border-green-500/30 flex items-center justify-between">
                                        <div className="flex items-center gap-3">
                                            <CheckCircle2 className="w-6 h-6 text-green-500" />
                                            <div>
                                                <div className="text-white font-medium text-sm">YouTube Connected</div>
                                                <div className="text-green-400 text-xs mt-0.5">{ytChannelName}</div>
                                            </div>
                                        </div>
                                        {!hasSyncedHistorical ? (
                                            <button 
                                                onClick={() => setShowRetroactiveModal(true)}
                                                className="px-3 py-1.5 bg-brand-500/20 hover:bg-brand-500/40 border border-brand-500/50 text-brand-300 text-xs rounded-lg transition-colors flex items-center gap-1.5 font-medium"
                                            >
                                                <Sparkles className="w-3.5 h-3.5" />
                                                Sync Histórico
                                            </button>
                                        ) : (
                                            <div className="px-3 py-1.5 bg-zinc-800/50 border border-white/10 text-zinc-400 text-xs rounded-lg flex items-center gap-1.5 font-medium">
                                                <Sparkles className="w-3.5 h-3.5 text-brand-500" />
                                                Historial Procesado
                                            </div>
                                        )}
                                    </div>
                                ) : ytShowPicker ? (
                                    <div className="p-4 rounded-xl bg-black/20 border border-red-500/20 space-y-3">
                                        <h4 className="text-white font-medium text-sm flex items-center gap-2">
                                            <Youtube className="w-5 h-5 text-red-500" /> Select Your Channel
                                        </h4>
                                        <div className="space-y-2 max-h-48 overflow-y-auto">
                                            {ytChannels.map((ch: any) => (
                                                <button key={ch.id} onClick={() => handleYtSelectChannel(ch.id)} disabled={ytConnecting}
                                                    className="w-full flex items-center gap-3 p-3 rounded-lg bg-zinc-800/50 border border-white/5 hover:border-red-500/30 transition-all text-left disabled:opacity-50">
                                                    {ch.thumbnail && <img src={ch.thumbnail} alt="" className="w-8 h-8 rounded-full" />}
                                                    <div className="flex-1 min-w-0">
                                                        <div className="text-zinc-200 text-sm font-medium truncate">{ch.title}</div>
                                                        <div className="text-zinc-500 text-xs">{ch.handle ? `@${ch.handle}` : ''} · {ch.subscriber_count || 0} subs</div>
                                                    </div>
                                                </button>
                                            ))}
                                        </div>
                                        <div className="flex gap-2 pt-2 border-t border-white/5">
                                            <input type="text" value={ytManualHandle} onChange={e => setYtManualHandle(e.target.value)}
                                                placeholder="@channelhandle" className="flex-1 bg-black/40 border border-white/10 rounded-lg px-3 py-2 text-sm text-zinc-200 placeholder-zinc-600 focus:outline-none focus:border-red-500/50" />
                                            <button onClick={handleYtManualHandle} disabled={ytConnecting || !ytManualHandle.trim()}
                                                className="px-4 py-2 bg-red-600 text-white text-sm font-medium rounded-lg hover:bg-red-500 disabled:opacity-50 transition-all">Sync</button>
                                        </div>
                                    </div>
                                ) : (
                                    <button onClick={handleYouTubeConnect} disabled={ytConnecting}
                                        className="w-full flex items-center gap-3 p-4 rounded-xl bg-black/20 border border-white/5 hover:bg-black/40 hover:border-red-500/30 transition-all text-left cursor-pointer disabled:opacity-50">
                                        {ytConnecting ? <Loader2 className="w-6 h-6 text-red-500 animate-spin" /> : <Youtube className="w-6 h-6 text-red-500" />}
                                        <div className="flex-1">
                                            <div className="text-zinc-200 font-medium text-sm">YouTube Channel</div>
                                            <div className="text-zinc-500 text-xs mt-0.5">Connect to unlock Personal Intelligence</div>
                                        </div>
                                        <span className="text-[10px] uppercase tracking-wider text-brand-400 font-bold bg-brand-500/10 px-2 py-1 rounded-md">Recommended</span>
                                    </button>
                                )}

                                {/* TikTok Button (future) */}
                                <button onClick={() => handleSocialConnect('tiktok')} className="w-full flex items-center gap-3 p-4 rounded-xl bg-black/20 border border-white/5 hover:bg-black/40 hover:border-[#00f2fe]/30 transition-all text-left cursor-pointer">
                                    <svg className="w-5 h-5 ml-0.5 text-zinc-200" fill="currentColor" viewBox="0 0 24 24"><path d="M19.59 6.69a4.83 4.83 0 0 1-3.77-4.25V2h-3.45v13.67a2.89 2.89 0 0 1-5.2 1.74 2.89 2.89 0 0 1 2.31-4.64 2.93 2.93 0 0 1 .88.13V9.4a6.84 6.84 0 0 0-1-.05A6.33 6.33 0 0 0 5 20.1a6.34 6.34 0 0 0 10.86-4.43v-7a8.16 8.16 0 0 0 4.77 1.52v-3.4a4.85 4.85 0 0 1-1-.1z" /></svg>
                                    <div>
                                        <div className="text-zinc-200 font-medium text-sm">TikTok Account</div>
                                        <div className="text-zinc-500 text-xs mt-0.5">Próximamente</div>
                                    </div>
                                </button>
                            </div>
                        </div>
                    </div>

                    <div className="flex items-center justify-between pt-8 border-t border-white/10 mt-8">
                        <button onClick={handlePrev} className="text-zinc-400 hover:text-white transition-colors text-sm font-medium flex items-center gap-2">
                            <ArrowLeft className="w-4 h-4" /> Atrás
                        </button>
                        <button onClick={handleNext} className="flex items-center gap-2 px-6 py-3 bg-white text-black font-semibold rounded-xl hover:bg-zinc-200 focus:ring-4 focus:ring-white/20 transition-all">
                            Siguiente <ArrowRight className="w-4 h-4" />
                        </button>
                    </div>
                </div>
            )}

            {/* STEP 4: AI ENGINES */}
            {step === 4 && (
                <div className="space-y-6 animate-in fade-in slide-in-from-right-4 duration-500">
                    <div>
                        <h1 className="text-3xl font-bold bg-gradient-to-r from-white to-zinc-400 bg-clip-text text-transparent">Conecta tu Inteligencia</h1>
                        <p className="text-zinc-400 mt-2">Para mantener tus datos privados, Azelia filtra los videos orquestando IAs a través de llaves API locales.</p>
                    </div>

                    <div className="bg-amber-950/30 border border-amber-500/20 rounded-xl p-4 flex gap-3 items-start">
                        <Shield className="w-5 h-5 text-amber-500 shrink-0 mt-0.5" />
                        <div className="text-sm text-amber-200/80 leading-relaxed">
                            <strong className="text-amber-400 block mb-1">Las APIs gratuitas colapsarán.</strong>
                            Extraer clips de un podcast de 1 hora requiere enviar más de 500,000 tokens de contexto a velocidad masiva. Los "Free Tiers" de Groq o Anthropic se bloquean a la mitad. Configura llaves API pagas para evitar fallos.
                        </div>
                    </div>

                    <div className="space-y-4 mt-6 relative z-20">
                        <div className="bg-black/40 border border-white/10 rounded-2xl p-6">
                            {/* Dropdown 1: Provider */}
                            <label className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-2 block">Proveedor de IA</label>
                            <select
                                value={selectedProvider}
                                onChange={(e) => { setSelectedProvider(e.target.value); setSelectedModelId(''); }}
                                className="w-full bg-zinc-900 border border-white/20 rounded-xl px-4 py-3 text-white appearance-none focus:border-brand-500 outline-none hover:border-white/30 transition-all font-medium text-sm"
                                style={{ backgroundImage: `url("data:image/svg+xml;charset=US-ASCII,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20width%3D%22292.4%22%20height%3D%22292.4%22%3E%3Cpath%20fill%3D%22%23A1A1AA%22%20d%3D%22M287%2069.4a17.6%2017.6%200%200%200-13-5.4H18.4c-5%200-9.3%201.8-12.9%205.4A17.6%2017.6%200%200%200%200%2082.2c0%205%201.8%209.3%205.4%2012.9l128%20127.9c3.6%203.6%207.8%205.4%2012.8%205.4s9.2-1.8%2012.8-5.4L287%2095c3.5-3.5%205.4-7.8%205.4-12.8%200-5-1.9-9.2-5.5-12.8z%22%2F%3E%3C%2Fsvg%3E")`, backgroundRepeat: 'no-repeat', backgroundPosition: 'right 1rem top 50%', backgroundSize: '0.65rem auto' }}
                            >
                                <option value="" disabled>Selecciona un proveedor...</option>
                                {providerOrder.map(key => (
                                    <option key={key} value={key} className="bg-zinc-900">{PROVIDERS[key].name}</option>
                                ))}
                            </select>
                            <p className="text-xs text-zinc-500 mt-1.5">{selectedProvider ? PROVIDERS[selectedProvider].desc : ''}</p>

                            {/* Dropdown 2: Model (appears after provider selection) */}
                            {selectedProvider && (
                                <div className="mt-5 animate-in fade-in slide-in-from-top-2 duration-300">
                                    <label className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-2 block">Modelo</label>
                                    <select
                                        value={selectedModelId}
                                        onChange={(e) => {
                                            const id = e.target.value;
                                            setSelectedModelId(id);
                                            const p = selectedProvider;
                                            if (p === 'openai') handleUpdate({ openai_model: id });
                                            else if (p === 'anthropic') handleUpdate({ anthropic_model: id });
                                            else if (p === 'vertex') handleUpdate({ vertex_model: id });
                                            else if (p === 'groq') handleUpdate({ groq_model: id });
                                        }}
                                        className="w-full bg-zinc-900 border border-white/20 rounded-xl px-4 py-3 text-white appearance-none focus:border-brand-500 outline-none hover:border-white/30 transition-all font-medium text-sm"
                                        style={{ backgroundImage: `url("data:image/svg+xml;charset=US-ASCII,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20width%3D%22292.4%22%20height%3D%22292.4%22%3E%3Cpath%20fill%3D%22%23A1A1AA%22%20d%3D%22M287%2069.4a17.6%2017.6%200%200%200-13-5.4H18.4c-5%200-9.3%201.8-12.9%205.4A17.6%2017.6%200%200%200%200%2082.2c0%205%201.8%209.3%205.4%2012.9l128%20127.9c3.6%203.6%207.8%205.4%2012.8%205.4s9.2-1.8%2012.8-5.4L287%2095c3.5-3.5%205.4-7.8%205.4-12.8%200-5-1.9-9.2-5.5-12.8z%22%2F%3E%3C%2Fsvg%3E")`, backgroundRepeat: 'no-repeat', backgroundPosition: 'right 1rem top 50%', backgroundSize: '0.65rem auto' }}
                                    >
                                        <option value="" disabled>Selecciona un modelo...</option>
                                        {PROVIDERS[selectedProvider].models.map(m => (
                                            <option key={m.id} value={m.id} className="bg-zinc-900">{m.label}</option>
                                        ))}
                                    </select>
                                </div>
                            )}

                            {/* API Key Input (appears after model selection) */}
                            {selectedModelId && selectedProvider && (
                                <div className="mt-5 pt-5 border-t border-white/10 animate-in fade-in slide-in-from-top-2">
                                    <div className="flex items-center justify-between mb-2">
                                        <label className="text-xs font-semibold text-brand-300 uppercase tracking-wider">
                                            {selectedProvider === 'vertex' ? 'GCP Project ID' : 'API Key'}
                                        </label>
                                        <a
                                            href={PROVIDERS[selectedProvider].keyUrl}
                                            target="_blank"
                                            rel="noreferrer"
                                            className="text-[10px] text-zinc-500 hover:text-white underline underline-offset-2 flex items-center gap-1"
                                        >
                                            Obtener llave <ArrowRight className="w-3 h-3" />
                                        </a>
                                    </div>
                                    <div className="relative">
                                        <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                                            <Key className="h-4 w-4 text-zinc-500" />
                                        </div>
                                        <input
                                            type="password"
                                            value={
                                                (selectedProvider === 'openai' ? formData.openai_api_key :
                                                    selectedProvider === 'anthropic' ? formData.anthropic_api_key :
                                                        selectedProvider === 'vertex' ? formData.gcp_project_id :
                                                            formData.groq_api_key) || ''
                                            }
                                            onChange={(e) => {
                                                const val = e.target.value;
                                                if (selectedProvider === 'openai') handleUpdate({ openai_api_key: val, ai_provider_order: ['openai', 'groq', 'anthropic', 'vertex'] });
                                                else if (selectedProvider === 'anthropic') handleUpdate({ anthropic_api_key: val, ai_provider_order: ['anthropic', 'groq', 'openai', 'vertex'] });
                                                else if (selectedProvider === 'vertex') handleUpdate({ gcp_project_id: val, ai_provider_order: ['vertex', 'groq', 'openai', 'anthropic'] });
                                                else handleUpdate({ groq_api_key: val, ai_provider_order: ['groq', 'openai', 'anthropic', 'vertex'] });
                                            }}
                                            placeholder={PROVIDERS[selectedProvider].ph}
                                            className="w-full bg-black/60 border border-white/10 hover:border-white/20 rounded-xl pl-10 pr-4 py-3 text-sm text-zinc-200 placeholder-zinc-700 focus:outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500 font-mono transition-all shadow-[inset_0_2px_4px_rgba(0,0,0,0.3)]"
                                        />
                                    </div>
                                    <p className="text-xs text-zinc-500 mt-3 leading-relaxed">
                                        Se guarda en tu <code className="text-zinc-400">.env</code> local — nunca sale de tu máquina.
                                    </p>
                                </div>
                            )}
                        </div>
                    </div>

                    <div className="flex flex-col gap-4 pt-6 border-t border-white/10 mt-6">
                        <label className="flex items-start gap-3 cursor-pointer group">
                            <div className="relative flex items-center mt-0.5">
                                <input
                                    type="checkbox"
                                    checked={acceptedTerms}
                                    onChange={(e) => setAcceptedTerms(e.target.checked)}
                                    className="peer sr-only"
                                />
                                <div className="w-5 h-5 rounded border border-white/20 bg-black/50 peer-checked:bg-brand-500 peer-checked:border-brand-500 transition-all flex items-center justify-center">
                                    <CheckCircle2 className="w-3.5 h-3.5 text-white opacity-0 peer-checked:opacity-100 transition-opacity" />
                                </div>
                            </div>
                            <span className="text-sm text-zinc-400 group-hover:text-zinc-300 transition-colors cursor-pointer leading-tight">
                                He leído y acepto los <a href="https://azeliaclips.com/terms" className="text-brand-400 hover:text-brand-300 underline underline-offset-2">Términos y Condiciones</a> y la <a href="https://azeliaclips.com/privacy" className="text-brand-400 hover:text-brand-300 underline underline-offset-2">Política de Privacidad</a> de Azelia Clips.
                            </span>
                        </label>

                        <div className="flex items-center justify-between">
                            <button onClick={handlePrev} className="text-zinc-400 hover:text-white transition-colors text-sm font-medium flex items-center gap-2">
                                <ArrowLeft className="w-4 h-4" /> Atrás
                            </button>
                            <div className="flex flex-col items-end gap-1">
                                <button
                                    onClick={handleFinish}
                                    disabled={!hasAnyKey || !acceptedTerms || saving}
                                    className="flex items-center gap-2 px-6 py-3 bg-gradient-to-r from-brand-600 to-brand-500 text-white font-semibold rounded-xl hover:from-brand-500 focus:ring-4 focus:ring-brand-500/30 transition-all disabled:opacity-50 disabled:cursor-not-allowed shadow-lg shadow-brand-500/20"
                                >
                                    {saving ? <Loader2 className="w-5 h-5 animate-spin" /> : <Sparkles className="w-5 h-5" />} Terminar Setup
                                </button>
                                {(!hasAnyKey || !acceptedTerms) && (
                                    <span className="text-xs text-red-400/80 mr-1">
                                        {!hasAnyKey ? "Ingresa una API Key válida" : "Acepta los términos para continuar"}
                                    </span>
                                )}
                            </div>
                        </div>
                    </div>
                </div>
            )}
            
            <RetroactiveSyncModal 
                isOpen={showRetroactiveModal}
                onClose={() => setShowRetroactiveModal(false)}
                onSuccess={() => {
                    setHasSyncedHistorical(true);
                    setShowRetroactiveModal(false);
                }}
            />
        </div>
    );
};
