import React, { useEffect, useState } from 'react';
import { SettingsApi, type UpdateSettingsRequest } from '../../lib/api';
import { supabase } from '../../lib/supabase';
import { DirectoryPicker } from '../settings/DirectoryPicker';
import { ChevronDown, ChevronRight, Key, Loader2, Sparkles, FolderOpen, ArrowRight, CheckCircle2, User, Target, BarChart, Youtube, Link as LinkIcon, Shield } from 'lucide-react';
import toast from 'react-hot-toast';

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
    const [step, setStep] = useState<1 | 2 | 3 | 4>(1);
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [showDirPicker, setShowDirPicker] = useState(false);

    // Core settings
    const [formData, setFormData] = useState<Partial<UpdateSettingsRequest>>({});
    const [expandedProvider, setExpandedProvider] = useState<string | null>('groq');

    // Strategic Profiling (Step 2)
    const [profile, setProfile] = useState({
        content_niche: '',
        user_role: '',
        primary_goal: ''
    });

    // Telemetry (Step 3) - Opt-in: default OFF, user must explicitly enable
    const [telemetry, setTelemetry] = useState(false);

    // YouTube connection state
    const [ytConnected, setYtConnected] = useState(false);
    const [ytChannelName, setYtChannelName] = useState('');
    const [ytConnecting, setYtConnecting] = useState(false);
    const [ytChannels, setYtChannels] = useState<any[]>([]);
    const [ytAccessToken, setYtAccessToken] = useState<string | null>(null);
    const [ytShowPicker, setYtShowPicker] = useState(false);
    const [ytManualHandle, setYtManualHandle] = useState('');

    const PROVIDERS: Record<string, { name: string, desc: string, field: keyof UpdateSettingsRequest, modelField: keyof UpdateSettingsRequest, ph: string, models: { id: string, label: string }[] }> = {
        'groq': {
            name: 'Groq (Llama)', desc: 'Extremely fast inference', field: 'groq_api_key', modelField: 'groq_model', ph: 'gsk_...',
            models: [
                { id: "llama-3.3-70b-versatile", label: "Llama 3.3 70B Versatile" },
                { id: "meta-llama/llama-4-maverick-17b-128e-instruct", label: "Llama 4 Maverick 17B" },
                { id: "llama-3.1-70b-versatile", label: "Llama 3.1 70B Versatile" },
                { id: "deepseek-r1-distill-llama-70b", label: "DeepSeek R1 Distill 70B 💎" }
            ]
        },
        'openai': {
            name: 'OpenAI (GPT)', desc: 'High quality reasoning', field: 'openai_api_key', modelField: 'openai_model', ph: 'sk-...',
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

    const providerOrder = ['groq', 'openai', 'anthropic', 'vertex'];

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

    useEffect(() => {
        const init = async () => {
            try {
                const existing = await SettingsApi.getSettings();
                setFormData(existing);
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
                await supabase.from('user_profiles').update({
                    content_niche: profile.content_niche,
                    user_role: profile.user_role,
                    primary_goal: profile.primary_goal
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

            toast.success("¡Bienvenido a Celia Clips!");
            setTimeout(() => {
                window.location.replace('/dashboard');
            }, 1000);

        } catch (e) {
            console.error("Failed to save onboarding data", e);
            toast.error("Hubo un error guardando tu perfil.");
            setSaving(false);
        }
    };

    const handleYouTubeConnect = async () => {
        try {
            const redirectUri = window.location.origin + '/onboarding';
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
            const redirectUri = window.location.origin + '/onboarding';
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
                toast.success(`Synced ${result.total_shorts} videos from ${result.channel_name}!`, { id: toastId, icon: '🎬' });
                setYtConnected(true);
                setYtChannelName(result.channel_name);
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

    const hasAnyKey = !!(formData.groq_api_key || formData.openai_api_key || formData.anthropic_api_key || formData.gcp_project_id);

    if (loading) return (
        <div className="flex justify-center items-center py-20"><Loader2 className="w-8 h-8 text-brand-500 animate-spin" /></div>
    );

    return (
        <div className="bg-zinc-900/60 border border-white/10 rounded-3xl p-8 backdrop-blur-xl shadow-2xl relative overflow-hidden transition-all duration-500">
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
                        <p className="text-zinc-400 mt-2 text-lg">Celia analiza tus videos localmente. Dile cómo se llama tu proyecto y dónde encontrar el material.</p>
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
                        <p className="text-zinc-400 mt-2 text-lg">Esta información afina los algoritmos de recomendación de Celia para tu nicho específico.</p>
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
                    </div>

                    <div className="flex items-center justify-between pt-8 border-t border-white/10 mt-8">
                        <button onClick={handlePrev} className="text-zinc-500 hover:text-white transition-colors text-sm font-medium">Atrás</button>
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
                                        Únete al motor global de Celia. Al activar esto, donas métricas de retención 100% anónimas sobre qué hooks funcionan en tu nicho para nutrir la Inteligencia Colectiva (IC). NUNCA subimos video o audio. A cambio, tu cuenta acumulará un perfil de retención avanzado para cuando decidas hacer upgrade al IC Engine Pro.
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
                                    <div className="flex items-center gap-3 p-4 rounded-xl bg-green-500/10 border border-green-500/30 text-left">
                                        <CheckCircle2 className="w-6 h-6 text-green-500" />
                                        <div>
                                            <div className="text-white font-medium text-sm">YouTube Connected</div>
                                            <div className="text-green-400 text-xs mt-0.5">{ytChannelName}</div>
                                        </div>
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
                        <button onClick={handlePrev} className="text-zinc-500 hover:text-white transition-colors text-sm font-medium">Atrás</button>
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
                        <p className="text-zinc-400 mt-2">Para mantener tus datos privados, Celia filtra los videos orquestando IAs a través de llaves API locales.</p>
                    </div>

                    <div className="bg-amber-950/30 border border-amber-500/20 rounded-xl p-4 flex gap-3 items-start">
                        <Shield className="w-5 h-5 text-amber-500 shrink-0 mt-0.5" />
                        <div className="text-sm text-amber-200/80 leading-relaxed">
                            <strong className="text-amber-400 block mb-1">Las APIs gratuitas colapsarán.</strong>
                            Extraer clips de un podcast de 1 hora requiere enviar más de 500,000 tokens de contexto a velocidad masiva. Los "Free Tiers" de Groq o Anthropic se bloquean a la mitad. Configura llaves API pagas para evitar fallos.
                        </div>
                    </div>

                    <div className="space-y-3 mt-6 relative z-20">
                        {providerOrder.map((providerId) => {
                            const config = PROVIDERS[providerId];
                            if (!config) return null;
                            const isExpanded = expandedProvider === providerId;
                            // @ts-ignore
                            const hasValue = !!formData[config.field];

                            return (
                                <div key={providerId} className={`border transition-all duration-300 rounded-xl overflow-hidden ${isExpanded ? 'bg-zinc-800/50 border-white/20' : 'bg-black/20 border-white/5 hover:border-white/10 cursor-pointer'}`}>
                                    <div className="h-16 px-4 flex items-center justify-between" onClick={() => !isExpanded && setExpandedProvider(providerId)}>
                                        <div className="flex items-center gap-3">
                                            {isExpanded ? <ChevronDown className="w-5 h-5 text-brand-400" /> : <ChevronRight className="w-5 h-5 text-zinc-500" />}
                                            <div>
                                                <div className="font-medium text-white flex items-center gap-2">{config.name} {hasValue && !isExpanded && <CheckCircle2 className="w-4 h-4 text-green-500" />}</div>
                                                <div className="text-xs text-zinc-500">{config.desc}</div>
                                            </div>
                                        </div>
                                    </div>

                                    {isExpanded && (
                                        <div className="p-4 pt-0 space-y-4 border-t border-white/5 mt-2">
                                            <div>
                                                <label className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">Secret API Key</label>
                                                <div className="relative mt-2">
                                                    <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none"><Key className="h-4 w-4 text-zinc-600" /></div>
                                                    <input type="password" value={(formData[config.field as keyof UpdateSettingsRequest] as string) || ''} onChange={(e) => handleUpdate({ [config.field]: e.target.value })} placeholder={config.ph} className="w-full bg-black/40 border border-white/10 rounded-lg pl-10 pr-4 py-2 text-sm text-zinc-200 placeholder-zinc-700 focus:outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500 font-mono transition-all" />
                                                </div>
                                            </div>
                                            <div>
                                                <label className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-2 block">Selecciona el Modelo</label>
                                                <select value={(formData[config.modelField as keyof UpdateSettingsRequest] as string) || config.models[0].id} onChange={(e) => handleUpdate({ [config.modelField]: e.target.value })} className="w-full bg-black/40 border border-white/10 rounded-lg px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-brand-500 transition-all font-mono appearance-none" style={{ backgroundImage: `url("data:image/svg+xml;charset=US-ASCII,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20width%3D%22292.4%22%20height%3D%22292.4%22%3E%3Cpath%20fill%3D%22%23A1A1AA%22%20d%3D%22M287%2069.4a17.6%2017.6%200%200%200-13-5.4H18.4c-5%200-9.3%201.8-12.9%205.4A17.6%2017.6%200%200%200%200%2082.2c0%205%201.8%209.3%205.4%2012.9l128%20127.9c3.6%203.6%207.8%205.4%2012.8%205.4s9.2-1.8%2012.8-5.4L287%2095c3.5-3.5%205.4-7.8%205.4-12.8%200-5-1.9-9.2-5.5-12.8z%22%2F%3E%3C%2Fsvg%3E")`, backgroundRepeat: 'no-repeat', backgroundPosition: 'right 0.7rem top 50%', backgroundSize: '0.65rem auto' }}>
                                                    {config.models.map(model => <option key={model.id} value={model.id} className="bg-zinc-900">{model.label}</option>)}
                                                </select>
                                            </div>
                                        </div>
                                    )}
                                </div>
                            );
                        })}
                    </div>

                    <div className="flex items-center justify-between pt-8 border-t border-white/10 mt-8">
                        <button onClick={handlePrev} className="text-zinc-500 hover:text-white transition-colors text-sm font-medium">Atrás</button>
                        <button onClick={handleFinish} disabled={!hasAnyKey || saving} className="flex items-center gap-2 px-6 py-3 bg-gradient-to-r from-brand-600 to-brand-500 text-white font-semibold rounded-xl hover:from-brand-500 focus:ring-4 focus:ring-brand-500/30 transition-all disabled:opacity-50 shadow-lg shadow-brand-500/20">
                            {saving ? <Loader2 className="w-5 h-5 animate-spin" /> : <Sparkles className="w-5 h-5" />} Terminar Setup
                        </button>
                    </div>
                </div>
            )}
        </div>
    );
};
