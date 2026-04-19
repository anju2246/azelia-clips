import React, { useState } from 'react';
import { Sparkles, BarChart2, Zap, Shield, Loader2, CheckCircle2, Youtube, ArrowRight } from 'lucide-react';
import { supabase } from '../../lib/supabase';
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

interface ProUpgradeCardProps {
    onActivated?: () => void;
    youtubeConnected?: boolean;
    redirectUri?: string;
    onYouTubeConnected?: () => void;
    // onConnectYouTube is no longer used — OAuth is handled internally
    onConnectYouTube?: () => void;
}

export const ProUpgradeCard: React.FC<ProUpgradeCardProps> = ({ onActivated, youtubeConnected = false, redirectUri, onYouTubeConnected }) => {
    const [loading, setLoading] = useState(false);
    const [activated, setActivated] = useState(false);
    const [ytLoading, setYtLoading] = useState(false);
    const [acceptedTelemetry, setAcceptedTelemetry] = useState(false);

    // Check if already Pro on mount (e.g. after returning from YouTube OAuth)
    React.useEffect(() => {
        fetchWithAuth('/upgrade/status').then(res => {
            if (res.ok) res.json().then(d => { if (d.tier === 'pro') setActivated(true); });
        }).catch(() => {});
    }, []);

    const handleActivate = async () => {
        if (!acceptedTelemetry) {
            toast.error('Debes aceptar el intercambio de telemetría para activar Pro.');
            return;
        }
        setLoading(true);
        try {
            // Telemetry opt-in is an explicit, user-checked consent — never hidden.
            const tRes = await fetchWithAuth('/telemetry/consent', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enabled: true }),
            });
            if (!tRes.ok) {
                const err = await tRes.json().catch(() => ({}));
                throw new Error(err.detail || 'No se pudo registrar el consentimiento de telemetría.');
            }

            const res = await fetchWithAuth('/upgrade/pro', { method: 'POST' });
            if (res.status === 410) {
                toast.error('La beta gratuita ha finalizado. ¡Gracias por el interés!');
                return;
            }
            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'Error activando Pro');
            }

            if (youtubeConnected) {
                toast.success('¡Pro activado!');
                onActivated?.();
                return;
            }

            setActivated(true);
        } catch (e: any) {
            toast.error(e.message || 'No se pudo activar Pro');
        } finally {
            setLoading(false);
        }
    };

    const handleConnectYouTube = async () => {
        setYtLoading(true);
        try {
            const baseOrigin = window.location.origin
                .replace('127.0.0.1', 'localhost')
                .replace('0.0.0.0', 'localhost');
            const resolvedRedirectUri = redirectUri ?? (baseOrigin + '/dashboard/intelligence');
            const res = await fetchWithAuth(`/auth/youtube/authorize?redirect_uri=${encodeURIComponent(resolvedRedirectUri)}`);
            if (!res.ok) throw new Error('No se pudo iniciar la autorización de YouTube');
            const { url } = await res.json();
            window.location.href = url;
        } catch (e: any) {
            toast.error(e.message || 'Error conectando YouTube');
            setYtLoading(false);
        }
    };

    // Post-activation: show YouTube nudge
    if (activated) {
        return (
            <div className="rounded-2xl border border-green-500/30 bg-gradient-to-br from-green-500/10 to-zinc-900/80 p-6 space-y-5">
                <div className="flex items-center gap-3">
                    <div className="p-2 rounded-xl bg-green-500/20">
                        <CheckCircle2 className="w-5 h-5 text-green-400" />
                    </div>
                    <div>
                        <h3 className="font-semibold text-white text-sm">¡Pro activado! 3 meses gratis</h3>
                        <p className="text-xs text-green-400">Acceso completo al IC Cascade</p>
                    </div>
                </div>

                <div className="rounded-xl bg-zinc-800/80 border border-red-500/20 p-4 space-y-3">
                    <div className="flex items-center gap-2">
                        <Youtube className="w-4 h-4 text-red-400 shrink-0" />
                        <p className="text-sm font-medium text-white">Potencia tu IC con YouTube Analytics</p>
                    </div>
                    <p className="text-xs text-zinc-400 leading-relaxed">
                        El IC Cascade cruza tus clips con el <span className="text-zinc-200 font-medium">rendimiento real de tu canal</span> — retención, CTR y patrones de tu audiencia. Sin ese historial, el análisis trabaja a ciegas.
                    </p>
                    <button
                        onClick={handleConnectYouTube}
                        disabled={ytLoading}
                        className="w-full flex items-center justify-center gap-2 rounded-xl bg-red-600 hover:bg-red-500 disabled:opacity-60 text-white font-medium text-sm py-2.5 transition-colors"
                    >
                        {ytLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Youtube className="w-4 h-4" />}
                        {ytLoading ? 'Redirigiendo...' : 'Conectar canal de YouTube'}
                    </button>
                </div>

                {!onYouTubeConnected && (
                    <button
                        onClick={() => onActivated?.()}
                        className="w-full flex items-center justify-center gap-1.5 text-xs text-zinc-500 hover:text-zinc-400 transition-colors py-1"
                    >
                        Ir al dashboard sin conectar <ArrowRight className="w-3 h-3" />
                    </button>
                )}
            </div>
        );
    }

    return (
        <div className="rounded-2xl border border-brand-500/30 bg-gradient-to-br from-brand-500/10 to-zinc-900/80 p-6 space-y-5">
            <div className="flex items-center gap-3">
                <div className="p-2 rounded-xl bg-brand-500/20">
                    <Sparkles className="w-5 h-5 text-brand-400" />
                </div>
                <div>
                    <h3 className="font-semibold text-white text-sm">Azelia Pro — Beta gratuita</h3>
                    <p className="text-xs text-zinc-400">3 meses sin costo</p>
                </div>
            </div>

            <ul className="space-y-2.5">
                {[
                    { icon: BarChart2, text: 'IC Cascade — señales de mercado en tiempo real' },
                    { icon: Zap,       text: 'Patrones de hooks y duración de los top podcasts' },
                    { icon: BarChart2, text: 'Comparativa de tu contenido vs. el mercado' },
                ].map(({ icon: Icon, text }) => (
                    <li key={text} className="flex items-start gap-2.5">
                        <Icon className="w-4 h-4 text-brand-400 mt-0.5 shrink-0" />
                        <span className="text-sm text-zinc-300">{text}</span>
                    </li>
                ))}
            </ul>

            <div className="flex items-start gap-2.5 rounded-xl bg-zinc-800/60 border border-white/5 p-3.5">
                <Shield className="w-4 h-4 text-zinc-400 mt-0.5 shrink-0" />
                <p className="text-xs text-zinc-400 leading-relaxed">
                    <span className="text-zinc-300 font-medium">El trueque:</span> A cambio del acceso Pro,
                    tus métricas anónimas (scores, duración, tipo de hooks) contribuyen al pool colectivo
                    que alimenta el IC de todos. Nunca se envía audio, texto ni datos personales.
                </p>
            </div>

            {/* Pro-specific consent — the telemetry opt-in is the "trade" for the free 3 months.
                 General TyC and Privacy were already accepted at signup; they're not re-asked here. */}
            <label className="flex items-start gap-2.5 cursor-pointer group">
                <input
                    type="checkbox"
                    checked={acceptedTelemetry}
                    onChange={e => setAcceptedTelemetry(e.target.checked)}
                    className="mt-0.5 w-4 h-4 rounded accent-brand-500 cursor-pointer shrink-0"
                />
                <span className="text-xs text-zinc-300 leading-relaxed">
                    Acepto que mis <span className="font-medium text-white">métricas anónimas</span> (scores,
                    duración, tipo de hooks, rendimiento agregado en YouTube) contribuyan al IC colectivo mientras
                    esté en Pro. Detalles en la{' '}
                    <a href="https://azelia.ai/privacy" target="_blank" rel="noopener" className="underline decoration-dotted hover:text-white">
                        Política de Privacidad
                    </a>.
                    Puedo desactivar la telemetría en Ajustes cuando quiera.
                </span>
            </label>

            <button
                onClick={handleActivate}
                disabled={loading || !acceptedTelemetry}
                className="w-full flex items-center justify-center gap-2 rounded-xl bg-brand-500 hover:bg-brand-400 disabled:opacity-40 disabled:cursor-not-allowed text-white font-medium text-sm py-3 transition-colors"
            >
                {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
                {loading ? 'Activando...' : 'Activar Pro (3 meses)'}
            </button>

            <p className="text-center text-xs text-zinc-500">
                Sin tarjeta de crédito · Cancela cuando quieras
            </p>
        </div>
    );
};
