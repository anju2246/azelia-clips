import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  Loader2,
  X,
  Send,
  Check,
  Trash2,
  ChevronRight,
  ChevronLeft,
  ChevronDown,
} from "lucide-react";
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

type Decision = "approved" | "discarded" | "pending";

function OriginBadge({ c }: { c: BriefCandidate }) {
  if (!c.critic_approved) {
    return (
      <span className="text-[10px] uppercase tracking-wide text-amber-400/80">
        descartado por el crítico
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

/** Editable hook text (first-N-seconds title). Shown only when the job's
 *  template renders a hook. Saves on blur; the server returns the updated
 *  brief which the parent applies. */
function HookField({
  jobId,
  candidate,
  durationS,
  onSaved,
}: {
  jobId: string;
  candidate: BriefCandidate;
  durationS: number;
  onSaved: (b: BriefResponse) => void;
}) {
  const [value, setValue] = useState(candidate.hook_text ?? "");
  const [saving, setSaving] = useState(false);

  // Reset the field when navigating to another candidate.
  useEffect(() => {
    setValue(candidate.hook_text ?? "");
  }, [candidate.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const save = async () => {
    if (value === (candidate.hook_text ?? "")) return; // no change → skip
    setSaving(true);
    try {
      onSaved(await ClipsApi.setBriefHook(jobId, candidate.id, value));
    } catch {
      toast.error("No pude guardar el hook");
      setValue(candidate.hook_text ?? "");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="mt-3" data-testid="brief-hook-field">
      <label className="flex items-center gap-1 text-[11px] uppercase tracking-wide text-zinc-500">
        Hook{durationS > 0 ? ` (primeros ${Math.round(durationS)}s)` : ""}
        {saving && <Loader2 className="w-3 h-3 animate-spin" />}
      </label>
      <input
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onBlur={save}
        onKeyDown={(e) => {
          if (e.key === "Enter") (e.target as HTMLInputElement).blur();
        }}
        maxLength={120}
        placeholder={candidate.title}
        className="mt-1 w-full rounded-lg border border-zinc-800 bg-black/40 px-3 py-2 text-sm text-white focus:border-brand-500 focus:outline-none"
      />
    </div>
  );
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

  const [idx, setIdx] = useState(0); // current candidate (or === length → summary)
  const [discarded, setDiscarded] = useState<Set<number>>(new Set());
  const [showTranscript, setShowTranscript] = useState(false);
  const chatEndRef = useRef<HTMLDivElement | null>(null);

  const candidates = brief?.candidates ?? [];
  const total = candidates.length;
  const onSummary = idx >= total && total > 0;
  const current: BriefCandidate | undefined = candidates[idx];

  // ── Load the brief ────────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false;
    ClipsApi.getBrief(jobId)
      .then((b) => {
        if (cancelled) return;
        setBrief(b);
        // Seed discarded set: critic-rejected / below-threshold start unselected.
        const seed = new Set(
          b.candidates.filter((c) => !c.selected).map((c) => c.id),
        );
        setDiscarded(seed);
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

  // Collapse transcript + scroll chat whenever we move to another clip.
  useEffect(() => {
    setShowTranscript(false);
  }, [idx]);

  const clipMessages = useMemo(
    () =>
      current
        ? (brief?.messages ?? []).filter((m) => m.clip_id === current.id)
        : [],
    [brief?.messages, current?.id],
  );

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [clipMessages.length]);

  // ── Decisions ─────────────────────────────────────────────────────
  const decisionFor = (c: BriefCandidate): Decision => {
    if (discarded.has(c.id)) return "discarded";
    if (c.selected) return "approved";
    return "pending";
  };

  const setSelected = (id: number, selected: boolean) => {
    setBrief((prev) =>
      prev
        ? {
            ...prev,
            candidates: prev.candidates.map((c) =>
              c.id === id ? { ...c, selected } : c,
            ),
          }
        : prev,
    );
  };

  const advance = () => setIdx((i) => Math.min(i + 1, total));

  const approveCurrent = () => {
    if (!current) return;
    setDiscarded((prev) => {
      const next = new Set(prev);
      next.delete(current.id);
      return next;
    });
    setSelected(current.id, true);
    advance();
  };

  const discardCurrent = () => {
    if (!current) return;
    setDiscarded((prev) => new Set(prev).add(current.id));
    setSelected(current.id, false);
    advance();
  };

  // ── Chat (scoped to the current clip) ─────────────────────────────
  const send = async () => {
    const message = input.trim();
    if (!message || sending || !current) return;
    setSending(true);
    try {
      const res = await ClipsApi.sendBriefMessage(jobId, message, current.id);
      setBrief(res);
      setInput("");
      setShowTranscript(true); // reveal the (possibly re-cut) transcript so the change is visible
    } catch (e: any) {
      toast.error(e?.message || "No se pudo enviar el feedback");
    } finally {
      setSending(false);
    }
  };

  // ── Approve & render the selected set ─────────────────────────────
  const approvedIds = candidates.filter((c) => c.selected).map((c) => c.id);

  const render = async () => {
    if (approving) return;
    if (approvedIds.length === 0) {
      toast.error("Aprueba al menos un clip antes de renderizar");
      return;
    }
    setApproving(true);
    try {
      await ClipsApi.approveBrief(jobId, approvedIds);
      toast.success(`Procesando ${approvedIds.length} clips aprobados`);
      onApproved();
    } catch (e: any) {
      toast.error(e?.message || "No se pudo aprobar");
      setApproving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/75 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-zinc-900 border border-zinc-800 rounded-2xl max-w-3xl w-full max-h-[92vh] flex flex-col">
        {/* ── Header + progress ─────────────────────────────────────── */}
        <div className="flex justify-between items-start p-5 border-b border-zinc-800">
          <div className="min-w-0">
            <h2 className="text-lg font-semibold text-white">
              Revisar clips antes de procesar
            </h2>
            <p className="text-xs text-zinc-400 mt-0.5">
              {brief
                ? onSummary
                  ? `${brief.episode_id} · ${approvedIds.length} de ${total} aprobados`
                  : `${brief.episode_id} · Clip ${idx + 1} de ${total}`
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

        {/* Progress dots */}
        {brief && total > 0 && (
          <div className="flex flex-wrap items-center gap-1.5 px-5 pt-4">
            {candidates.map((c, i) => {
              const d = decisionFor(c);
              const active = i === idx && !onSummary;
              const color =
                d === "approved"
                  ? "bg-brand-500"
                  : d === "discarded"
                    ? "bg-zinc-700"
                    : "bg-zinc-600";
              return (
                <button
                  key={c.id}
                  onClick={() => setIdx(i)}
                  aria-label={`Ir al clip ${i + 1}`}
                  title={`#${c.id} ${c.title}`}
                  className={`h-2.5 rounded-full transition-all ${color} ${
                    active ? "w-6 ring-2 ring-brand-400/50" : "w-2.5"
                  } ${d === "discarded" ? "opacity-50" : ""}`}
                />
              );
            })}
          </div>
        )}

        {loading ? (
          <div className="flex flex-col items-center justify-center py-20 gap-3">
            <Loader2 className="w-6 h-6 text-brand-400 animate-spin" />
            <p className="text-sm text-zinc-400">Armando el brief…</p>
          </div>
        ) : error ? (
          <div className="m-6 p-4 bg-red-950/30 border border-red-900/50 rounded-xl text-sm text-red-300">
            {error}
          </div>
        ) : onSummary ? (
          /* ── Summary / render screen ──────────────────────────────── */
          <div className="flex-1 overflow-y-auto p-6 flex flex-col gap-4">
            <div className="text-sm text-zinc-300 bg-zinc-950/50 border border-zinc-800 rounded-xl p-4">
              Revisaste los {total} candidatos.{" "}
              <span className="text-white font-medium">
                {approvedIds.length} aprobados
              </span>{" "}
              se van a renderizar. Puedes volver a cualquier clip tocando su punto
              arriba.
            </div>
            <div className="space-y-2">
              {candidates.map((c, i) => {
                const approved = c.selected;
                return (
                  <button
                    key={c.id}
                    onClick={() => setIdx(i)}
                    className={`w-full flex items-center gap-3 text-left rounded-xl border p-3 transition-colors ${
                      approved
                        ? "border-brand-600/40 bg-brand-600/10"
                        : "border-zinc-800 bg-zinc-950/40"
                    }`}
                  >
                    <span
                      className={`flex items-center justify-center w-5 h-5 rounded-md flex-shrink-0 ${
                        approved
                          ? "bg-brand-500 text-white"
                          : "bg-zinc-800 text-zinc-600"
                      }`}
                    >
                      {approved ? (
                        <Check className="w-3.5 h-3.5" />
                      ) : (
                        <Trash2 className="w-3 h-3" />
                      )}
                    </span>
                    <span
                      className={`text-sm truncate flex-1 ${approved ? "text-white" : "text-zinc-500 line-through"}`}
                    >
                      #{c.id} {c.title}
                    </span>
                    <span className="text-xs text-zinc-500 tabular-nums">
                      {Math.round(c.end_time - c.start_time)}s
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        ) : current ? (
          /* ── Single-clip review ───────────────────────────────────── */
          <div className="flex-1 flex flex-col min-h-0 p-5 gap-3">
            {/* Candidate card */}
            <div
              data-testid="brief-candidate"
              className="rounded-xl border border-zinc-800 bg-zinc-950/40 p-4"
            >
              <div className="flex items-start gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-base font-semibold text-white">
                      #{current.id} {current.title}
                    </span>
                    <OriginBadge c={current} />
                  </div>
                  <p className="text-xs text-zinc-500 mt-0.5">
                    {Math.round(current.start_time)}s–
                    {Math.round(current.end_time)}s ·{" "}
                    {Math.round(current.end_time - current.start_time)}s
                  </p>
                </div>
                <span className="text-lg font-semibold text-zinc-300 tabular-nums">
                  {current.score > 0 ? Math.round(current.score) : "—"}
                </span>
              </div>

              {brief?.hook_enabled && (
                <HookField
                  jobId={jobId}
                  candidate={current}
                  durationS={brief.hook_duration_s}
                  onSaved={setBrief}
                />
              )}

              {current.summary && (
                <p className="text-sm text-zinc-200 mt-3">{current.summary}</p>
              )}
              {current.reasoning && (
                <p className="text-sm text-zinc-400 mt-2">
                  <span className="text-zinc-500">Por qué: </span>
                  {current.reasoning}
                </p>
              )}
              {current.transcript && (
                <div className="mt-3">
                  <button
                    onClick={() => setShowTranscript((v) => !v)}
                    className="flex items-center gap-1 text-[11px] uppercase tracking-wide text-zinc-500 hover:text-zinc-300"
                  >
                    {showTranscript ? (
                      <ChevronDown className="w-3.5 h-3.5" />
                    ) : (
                      <ChevronRight className="w-3.5 h-3.5" />
                    )}
                    Transcript
                  </button>
                  {showTranscript && (
                    <p className="text-xs text-zinc-400 leading-relaxed max-h-32 overflow-y-auto bg-black/30 rounded-lg p-2 mt-1">
                      {current.transcript}
                    </p>
                  )}
                </div>
              )}
            </div>

            {/* Per-clip chat */}
            <div className="flex-1 min-h-0 flex flex-col rounded-xl border border-zinc-800 bg-zinc-950/30">
              <div className="flex-1 overflow-y-auto p-4 space-y-3">
                <div className="text-sm text-zinc-300">
                  Dime qué ajustar de este clip: recortarlo, mover el arranque o
                  el cierre, buscar un mejor momento, o descártalo si no va.
                </div>
                {clipMessages.map((m, i) => (
                  <div
                    key={i}
                    className={
                      m.role === "user"
                        ? "text-sm text-white bg-brand-600/20 border border-brand-600/30 rounded-xl p-3 ml-8"
                        : "text-sm text-zinc-200 bg-zinc-900/70 border border-zinc-800 rounded-xl p-3 mr-8"
                    }
                  >
                    {m.content}
                  </div>
                ))}
                {sending && (
                  <div className="text-sm text-zinc-400 flex items-center gap-2 mr-8">
                    <Loader2 className="w-3.5 h-3.5 animate-spin" /> Aplicando…
                  </div>
                )}
                <div ref={chatEndRef} />
              </div>
              <div className="p-3 border-t border-zinc-800 flex items-end gap-2">
                <textarea
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      send();
                    }
                  }}
                  rows={1}
                  placeholder="Feedback de este clip…  (Enter envía)"
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
          </div>
        ) : null}

        {/* ── Footer actions ────────────────────────────────────────── */}
        {!loading && !error && brief && (
          <div className="p-4 border-t border-zinc-800 flex items-center gap-2">
            <button
              onClick={() => setIdx((i) => Math.max(i - 1, 0))}
              disabled={idx === 0}
              className="p-2.5 text-zinc-400 hover:text-white disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
              aria-label="Anterior"
            >
              <ChevronLeft className="w-5 h-5" />
            </button>

            {onSummary ? (
              <button
                onClick={render}
                disabled={approving || approvedIds.length === 0}
                className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 bg-brand-600 hover:bg-brand-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-semibold rounded-xl transition-colors"
                data-testid="brief-approve"
              >
                {approving ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Check className="w-4 h-4" />
                )}
                Renderizar {approvedIds.length} aprobados
              </button>
            ) : (
              <>
                <button
                  onClick={discardCurrent}
                  className="flex items-center justify-center gap-1.5 px-4 py-2.5 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-sm font-medium rounded-xl transition-colors"
                  data-testid="brief-discard"
                >
                  <Trash2 className="w-4 h-4" /> Descartar
                </button>
                <button
                  onClick={advance}
                  className="px-4 py-2.5 text-sm text-zinc-400 hover:text-white transition-colors"
                >
                  Saltar →
                </button>
                <button
                  onClick={approveCurrent}
                  className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 bg-brand-600 hover:bg-brand-500 text-white text-sm font-semibold rounded-xl transition-colors"
                  data-testid="brief-approve"
                >
                  <Check className="w-4 h-4" /> Aprobar →
                </button>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
};
