import React, { useEffect, useState } from "react";
import {
  Loader2,
  RefreshCw,
  Download,
  Link2,
  Check,
  X,
  TrendingDown,
  Sparkles,
  AlertTriangle,
} from "lucide-react";
import { CpiApi, type ClipLink } from "../../lib/api";

interface Summary {
  shorts: number;
  with_retention: number;
  creator_signals: number;
  niche_signals: number;
  links_suggested: number;
  zero_reach: number;
}

interface ZeroReachVideo {
  video_id: string;
  title: string;
  published_at: string;
  duration_seconds: number;
}

function pct(n?: number | null): string {
  if (n === null || n === undefined) return "—";
  return `${Math.round(n)}%`;
}

function ratioPct(n?: number | null): string {
  if (n === null || n === undefined) return "—";
  return `${Math.round(n * 100)}%`;
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
  const [links, setLinks] = useState<ClipLink[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [suggesting, setSuggesting] = useState(false);
  const [importing, setImporting] = useState(false);
  const [nichePath, setNichePath] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [zeroReach, setZeroReach] = useState<ZeroReachVideo[]>([]);
  const [showZero, setShowZero] = useState(false);

  const loadLinks = async () => {
    try {
      const r = await CpiApi.listLinks("suggested");
      setLinks(r.links);
    } catch {
      /* sin links aún */
    }
  };

  const refresh = async () => {
    setRefreshing(true);
    setMsg(null);
    try {
      const s = await CpiApi.refresh();
      setSummary(s);
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
      await loadLinks();
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

  const suggest = async () => {
    setSuggesting(true);
    setMsg(null);
    try {
      const r = await CpiApi.suggestLinks();
      setMsg(`${r.count} matches sugeridos.`);
      await loadLinks();
      await refresh();
    } catch (e: any) {
      setMsg(e?.message || "No se pudo generar matches");
    } finally {
      setSuggesting(false);
    }
  };

  const act = async (id: number, action: "confirm" | "reject", videoId?: string | null) => {
    setBusyId(id);
    try {
      await CpiApi.updateLink(id, action, videoId || undefined);
      setLinks((prev) => prev.filter((l) => l.id !== id));
      await refresh();
    } catch (e: any) {
      setMsg(e?.message || "Acción falló");
    } finally {
      setBusyId(null);
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
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          <StatCard label="Shorts" value={summary.shorts} />
          <StatCard
            label="Con retención"
            value={summary.with_retention}
            hint="data real de YouTube"
          />
          <StatCard label="Señales propias" value={summary.creator_signals} hint="CREATOR SELF" />
          <StatCard label="Señales de nicho" value={summary.niche_signals} hint="PodFinder" />
          <StatCard label="Matches por revisar" value={summary.links_suggested} />
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

      {/* Niche import + suggest matches */}
      <div className="flex flex-col sm:flex-row gap-3">
        <div className="flex-1 rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
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
        <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4 flex flex-col justify-between">
          <div className="flex items-center gap-2 text-sm font-semibold text-white mb-2">
            <Link2 className="w-4 h-4 text-brand-400" /> Vincular clips ↔ videos
          </div>
          <button
            onClick={suggest}
            disabled={suggesting}
            className="rounded-lg bg-zinc-800 border border-zinc-700 px-3 py-2 text-sm text-zinc-200 hover:bg-zinc-700 disabled:opacity-50"
          >
            {suggesting ? <Loader2 className="w-4 h-4 animate-spin" /> : "Generar matches"}
          </button>
        </div>
      </div>

      {/* Match review */}
      <div>
        <h2 className="text-lg font-semibold text-white mb-1">Revisar matches</h2>
        <p className="text-sm text-zinc-500 mb-4">
          Confirma qué clip tuyo corresponde a cada video subido. Al confirmar, el agente hereda la
          retención real de ESE video.
        </p>
        {links.length === 0 ? (
          <div className="rounded-xl border border-dashed border-zinc-800 p-8 text-center text-sm text-zinc-500">
            No hay matches por revisar. Genera matches arriba.
          </div>
        ) : (
          <div className="space-y-2">
            {links.map((l) => (
              <div
                key={l.id}
                className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4 flex items-center gap-4"
              >
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium text-white truncate">{l.clip_title || "(sin título)"}</div>
                  <div className="text-xs text-zinc-500 truncate">
                    ↔ {l.video_title || l.video_id}{" "}
                    <span className="text-zinc-600">· conf {ratioPct(l.match_confidence)}</span>
                  </div>
                </div>
                <div className="text-right text-xs shrink-0">
                  <div className="text-zinc-300">
                    {l.video_views ?? "—"} views · retención{" "}
                    <span className="text-brand-300">{pct(l.video_retention)}</span>
                  </div>
                  {l.video_drop_off !== null && l.video_drop_off !== undefined && (
                    <div className="text-zinc-500 flex items-center gap-1 justify-end">
                      <TrendingDown className="w-3 h-3" /> se van al {ratioPct(l.video_drop_off)}
                    </div>
                  )}
                </div>
                <div className="flex gap-2 shrink-0">
                  <button
                    onClick={() => act(l.id, "confirm", l.video_id)}
                    disabled={busyId === l.id}
                    className="inline-flex items-center gap-1 rounded-lg bg-emerald-500/10 border border-emerald-500/30 px-2.5 py-1.5 text-xs text-emerald-300 hover:bg-emerald-500/20 disabled:opacity-50"
                  >
                    <Check className="w-3.5 h-3.5" /> Confirmar
                  </button>
                  <button
                    onClick={() => act(l.id, "reject")}
                    disabled={busyId === l.id}
                    className="inline-flex items-center gap-1 rounded-lg bg-zinc-800 border border-zinc-700 px-2.5 py-1.5 text-xs text-zinc-400 hover:bg-zinc-700 disabled:opacity-50"
                  >
                    <X className="w-3.5 h-3.5" /> Rechazar
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

export default CpiDashboard;
