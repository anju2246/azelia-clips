import React, { useEffect, useRef, useState } from "react";
import { Loader2, X, Send, Check } from "lucide-react";
import toast from "react-hot-toast";
import {
  ClipsApi,
  type BriefResponse,
  type BriefCandidate,
} from "../../lib/api";

interface BriefChatModalProps {
  jobId: string;
  onClose: () => void;
  onApproved: () => void;
}

function OriginBadge({ c }: { c: BriefCandidate }) {
  if (!c.critic_approved) {
    return (
      <span className="text-[10px] uppercase tracking-wide text-amber-400/80">
        descartado
      </span>
    );
  }
  if (c.origin === "found") {
    return (
      <span className="text-[10px] uppercase tracking-wide text-sky-400/80">
        nuevo
      </span>
    );
  }
  return null;
}

export const BriefChatModal: React.FC<BriefChatModalProps> = ({
  jobId,
  onClose,
  onApproved,
}) => {
  const [brief, setBrief] = useState<BriefResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [approving, setApproving] = useState(false);
  const chatEndRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    ClipsApi.getBrief(jobId)
      .then((b) => {
        if (!cancelled) setBrief(b);
      })
      .catch((e: any) => {
        if (!cancelled) setError(e?.message || "No se pudo cargar el brief");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [jobId]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [brief?.messages.length]);

  const send = async () => {
    const message = input.trim();
    if (!message || sending) return;
    setSending(true);
    try {
      const res = await ClipsApi.sendBriefMessage(jobId, message);
      setBrief(res);
      setInput("");
    } catch (e: any) {
      toast.error(e?.message || "No se pudo enviar el feedback");
    } finally {
      setSending(false);
    }
  };

  const approve = async () => {
    if (!brief || approving) return;
    const selectedIds = brief.candidates.filter((c) => c.selected).map((c) => c.id);
    if (selectedIds.length === 0) {
      toast.error("Selecciona al menos un clip para procesar");
      return;
    }
    setApproving(true);
    try {
      await ClipsApi.approveBrief(jobId, selectedIds);
      toast.success(`Procesando ${selectedIds.length} clips aprobados`);
      onApproved();
    } catch (e: any) {
      toast.error(e?.message || "No se pudo aprobar");
      setApproving(false);
    }
  };

  const selectedCount = brief?.counts.selected ?? 0;
  const messages = brief?.messages ?? [];

  return (
    <div className="fixed inset-0 bg-black/75 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-zinc-900 border border-zinc-800 rounded-2xl max-w-5xl w-full max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="flex justify-between items-start p-5 border-b border-zinc-800">
          <div>
            <h2 className="text-lg font-semibold text-white">
              Revisar brief antes de procesar
            </h2>
            <p className="text-xs text-zinc-400 mt-0.5">
              {brief
                ? `${brief.episode_id} · ${brief.counts.total} candidatos · ${selectedCount} listos`
                : "Cargando candidatos…"}
            </p>
          </div>
          <button
            onClick={onClose}
            className="text-zinc-400 hover:text-white transition-colors"
            aria-label="Cerrar"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {loading ? (
          <div className="flex flex-col items-center justify-center py-20 gap-3">
            <Loader2 className="w-6 h-6 text-brand-400 animate-spin" />
            <p className="text-sm text-zinc-400">Armando el brief…</p>
          </div>
        ) : error ? (
          <div className="m-6 p-4 bg-red-950/30 border border-red-900/50 rounded-xl text-sm text-red-300">
            {error}
          </div>
        ) : (
          <div className="flex flex-1 min-h-0 divide-x divide-zinc-800">
            {/* ── Chat (left) ─────────────────────────────────────────── */}
            <div className="flex flex-col w-1/2 min-h-0">
              <div className="flex-1 overflow-y-auto p-5 space-y-3">
                <div className="text-sm text-zinc-300 bg-zinc-950/50 border border-zinc-800 rounded-xl p-3">
                  Te dejé {brief?.counts.total} candidatos, {selectedCount} ya
                  seleccionados. Dime qué ajustar: quitar, rescatar, reordenar,
                  o buscar algo de un momento puntual.
                </div>
                {messages.map((m, i) => (
                  <div
                    key={i}
                    className={
                      m.role === "user"
                        ? "text-sm text-white bg-brand-600/20 border border-brand-600/30 rounded-xl p-3 ml-6"
                        : "text-sm text-zinc-200 bg-zinc-950/50 border border-zinc-800 rounded-xl p-3 mr-6"
                    }
                  >
                    {m.content}
                  </div>
                ))}
                <div ref={chatEndRef} />
              </div>
              <div className="p-4 border-t border-zinc-800 flex items-end gap-2">
                <textarea
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      send();
                    }
                  }}
                  rows={2}
                  placeholder="Escribe tu feedback…  (Enter envía)"
                  className="flex-1 resize-none bg-zinc-950 border border-zinc-800 rounded-xl px-3 py-2 text-sm text-white placeholder:text-zinc-600 focus:outline-none focus:border-brand-500"
                  data-testid="brief-input"
                />
                <button
                  onClick={send}
                  disabled={sending || !input.trim()}
                  className="p-2.5 bg-brand-600 hover:bg-brand-500 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded-xl transition-colors"
                  aria-label="Enviar"
                >
                  {sending ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Send className="w-4 h-4" />
                  )}
                </button>
              </div>
            </div>

            {/* ── Candidates (right) ──────────────────────────────────── */}
            <div className="flex flex-col w-1/2 min-h-0">
              <div className="flex-1 overflow-y-auto p-5 space-y-2">
                {(brief?.candidates ?? []).map((c) => (
                  <div
                    key={c.id}
                    data-testid="brief-candidate"
                    className={`flex items-center gap-3 rounded-xl border p-3 ${
                      c.selected
                        ? "border-brand-600/40 bg-brand-600/10"
                        : "border-zinc-800 bg-zinc-950/40 opacity-70"
                    }`}
                  >
                    <div
                      className={`flex items-center justify-center w-5 h-5 rounded-md flex-shrink-0 ${
                        c.selected ? "bg-brand-500 text-white" : "bg-zinc-800 text-zinc-600"
                      }`}
                    >
                      {c.selected && <Check className="w-3.5 h-3.5" />}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="text-sm text-white truncate">
                          #{c.id} {c.title}
                        </span>
                        <OriginBadge c={c} />
                      </div>
                      <p className="text-xs text-zinc-500">
                        {Math.round(c.start_time)}s–{Math.round(c.end_time)}s
                      </p>
                    </div>
                    <span className="text-sm font-semibold text-zinc-300 tabular-nums">
                      {c.score > 0 ? Math.round(c.score) : "—"}
                    </span>
                  </div>
                ))}
              </div>
              <div className="p-4 border-t border-zinc-800 flex items-center gap-2">
                <button
                  onClick={approve}
                  disabled={approving || selectedCount === 0}
                  className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 bg-brand-600 hover:bg-brand-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-semibold rounded-xl transition-colors"
                  data-testid="brief-approve"
                >
                  {approving ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Check className="w-4 h-4" />
                  )}
                  Aprobar y procesar ({selectedCount})
                </button>
                <button
                  onClick={onClose}
                  className="px-4 py-2.5 text-sm text-zinc-400 hover:text-white transition-colors"
                >
                  Cerrar
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
