import React, { useState } from 'react';
import { Sparkles, BarChart2, Zap, Shield, Loader2 } from 'lucide-react';
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
}

export const ProUpgradeCard: React.FC<ProUpgradeCardProps> = ({ onActivated }) => {
    const [loading, setLoading] = useState(false);

    const handleActivate = async () => {
        setLoading(true);
        try {
            const res = await fetchWithAuth('/upgrade/pro', { method: 'POST' });
            if (res.status === 410) {
                toast.error('La beta gratuita ha finalizado. ¡Gracias por el interés!');
                return;
            }
            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'Error activando Pro');
            }
            const data = await res.json();
            toast.success(data.message || '¡Pro activado!');
            onActivated?.();
        } catch (e: any) {
            toast.error(e.message || 'No se pudo activar Pro');
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="rounded-2xl border border-brand-500/30 bg-gradient-to-br from-brand-500/10 to-zinc-900/80 p-6 space-y-5">
            {/* Header */}
            <div className="flex items-center gap-3">
                <div className="p-2 rounded-xl bg-brand-500/20">
                    <Sparkles className="w-5 h-5 text-brand-400" />
                </div>
                <div>
                    <h3 className="font-semibold text-white text-sm">Azelia Pro — Beta gratuita</h3>
                    <p className="text-xs text-zinc-400">3 meses sin costo</p>
                </div>
            </div>

            {/* Features */}
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

            {/* Tradeoff explanation */}
            <div className="flex items-start gap-2.5 rounded-xl bg-zinc-800/60 border border-white/5 p-3.5">
                <Shield className="w-4 h-4 text-zinc-400 mt-0.5 shrink-0" />
                <p className="text-xs text-zinc-400 leading-relaxed">
                    <span className="text-zinc-300 font-medium">El trueque:</span> A cambio del acceso Pro,
                    tus métricas anónimas (scores, duración, tipo de hooks) contribuyen al pool colectivo
                    que alimenta el IC de todos. Nunca se envía audio, texto ni datos personales.
                </p>
            </div>

            {/* CTA */}
            <button
                onClick={handleActivate}
                disabled={loading}
                className="w-full flex items-center justify-center gap-2 rounded-xl bg-brand-500 hover:bg-brand-400 disabled:opacity-60 disabled:cursor-not-allowed text-white font-medium text-sm py-3 transition-colors"
            >
                {loading ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                    <Sparkles className="w-4 h-4" />
                )}
                {loading ? 'Activando...' : 'Activar Pro y contribuir al IC'}
            </button>

            <p className="text-center text-xs text-zinc-500">
                Sin tarjeta de crédito · Cancela cuando quieras
            </p>
        </div>
    );
};
