import React, { useEffect, useState } from "react";
import {
  Loader2,
  RefreshCw,
  Download,
  Sparkles,
  AlertTriangle,
} from "lucide-react";
import { CpiApi } from "../../lib/api";

interface Summary {
  shorts: number;
  with_retention: number;
  creator_signals: number;
  niche_signals: number;
  zero_reach: number;
}

interface ZeroReachVideo {
  video_id: string;
  title: string;
  published_at: string;
  duration_seconds: number;
}

const StatCard: React.FC<{ label: string; value: React.ReactNode; hint?: string }> = ({
  label,
  value,
  hint,
}) => (
  <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-4">
    <div className="text-2xl font-bold text-white">{value}</div>
    <div className="text-xs text-zinc-400 mt-1">{label}</div>
    {hint && <div className="text-[11px] text-zinc-600 mt-0.5">{hint}</div>}
  </div>
);

export const CpiDashboard: React.FC = () => {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [importing, setImporting] = useState(false);
  const [nichePath, setNichePath] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [zeroReach, setZeroReach] = useState<ZeroReachVideo[]>([]);
  const [showZero, setShowZero] = useState(false);

  const refresh = async () => {
    setRefreshing(true);
    setMsg(null);
    try {
      setSummary(await CpiApi.refresh());
    } catch (e: any) {
      setMsg(e?.message || "No se pudo refrescar");
    } finally {
      setRefreshing(false);
    }
  };

  const loadZeroReach = async () => {
    try {
      const r = await CpiApi.zeroReach();
      setZeroReach(r.videos);
    } catch {
      /* sin data */
    }
  };

  useEffect(() => {
    (async () => {
      await refresh();
      await loadZeroReach();
      setLoading(false);
    })();
  }, []);

  const importNiche = async () => {
    setImporting(true);
    setMsg(null);
    try {
      const r = await CpiApi.importNiche(nichePath || undefined);
      setMsg(
        `Importadas ${r.signals_imported} señales niche y ${r.baselines_imported} baselines.`,
      );
      await refresh();
    } catch (e: any) {
      setMsg(e?.message || "No se pudo importar");
    } finally {
      setImporting(false);
    }
  };

  if (loading) {
    return (
      <div className="flex justify-center py-16">
        <Loader2 className="w-6 h-6 text-brand-500 animate-spin" />
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <Sparkles className="w-6 h-6 text-brand-400" /> Clip Performance Intelligence
          </h1>
          <p className="text-sm text-zinc-400 mt-1">
            Lo que de verdad funciona en tu canal (retención real) + lo que rinde en tu nicho.
            Tus agentes ya usan estas señales al sacar clips.
          </p>
        </div>
        <button
          onClick={refresh}
          disabled={refreshing}
          className="inline-flex items-center gap-2 rounded-lg bg-brand-500/10 border border-brand-500/30 px-3 py-2 text-sm text-brand-300 hover:bg-brand-500/20 disabled:opacity-50"
        >
          <RefreshCw className={`w-4 h-4 ${refreshing ? "animate-spin" : ""}`} />
          Refrescar
        </button>
      </div>

      {msg && (
        <div className="rounded-lg border border-zinc-700 bg-zinc-900/60 px-4 py-2 text-sm text-zinc-300">
          {msg}
        </div>
      )}

      {/* Summary */}
      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <StatCard label="Shorts" value={summary.shorts} />
          <StatCard
            label="Con retención"
            value={summary.with_retention}
            hint="data real de YouTube"
          />
          <StatCard label="Señales propias" value={summary.creator_signals} hint="CREATOR SELF" />
          <StatCard label="Señales de nicho" value={summary.niche_signals} hint="PodFinder" />
        </div>
      )}

      {/* Alerta de 0-reach (problema de distribución, no de contenido) */}
      {summary && summary.zero_reach > 0 && (
        <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-4">
          <button
            onClick={() => setShowZero((v) => !v)}
            className="w-full flex items-center gap-2 text-left"
          >
            <AlertTriangle className="w-5 h-5 text-amber-400 shrink-0" />
            <span className="text-sm font-semibold text-amber-200">
              {summary.zero_reach} shorts públicos con 0 reproducciones
            </span>
            <span className="text-xs text-amber-200/60 ml-1">
              — probable problema de distribución, no de contenido. {showZero ? "Ocultar" : "Ver cuáles"}
            </span>
          </button>
          {showZero && (
            <div className="mt-3 space-y-1.5 border-t border-amber-500/20 pt-3">
              {zeroReach.map((v) => (
                <div key={v.video_id} className="flex items-center justify-between text-xs">
                  <span className="text-zinc-300 truncate flex-1">{v.title || v.video_id}</span>
                  <span className="text-zinc-500 shrink-0 ml-3">
                    {v.published_at?.slice(0, 10)} · {Math.round(v.duration_seconds)}s
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Niche import */}
      <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
        <div className="flex items-center gap-2 text-sm font-semibold text-white mb-2">
          <Download className="w-4 h-4 text-brand-400" /> Importar señales de nicho
        </div>
        <p className="text-xs text-zinc-500 mb-3">
          Ruta al JSON de resultados (ic_signals_ready.json). Vacío = usa la ruta configurada.
        </p>
        <div className="flex gap-2">
          <input
            value={nichePath}
            onChange={(e) => setNichePath(e.target.value)}
            placeholder="/ruta/ic_signals_ready.json"
            className="flex-1 rounded-lg bg-zinc-950 border border-zinc-700 px-3 py-2 text-sm text-zinc-200"
          />
          <button
            onClick={importNiche}
            disabled={importing}
            className="rounded-lg bg-zinc-800 border border-zinc-700 px-3 py-2 text-sm text-zinc-200 hover:bg-zinc-700 disabled:opacity-50"
          >
            {importing ? <Loader2 className="w-4 h-4 animate-spin" /> : "Importar"}
          </button>
        </div>
      </div>
    </div>
  );
};

export default CpiDashboard;
