import React, { useRef, useState } from "react";
import toast from "react-hot-toast";
import { Send, Sparkles, ImagePlus, X, Check, Undo2, AlertTriangle } from "lucide-react";
import { TemplatesApi, type ClipTemplate } from "../../lib/api";
import { assToHex } from "./colors";

interface Msg {
  role: "user" | "assistant";
  content: string;
}

type Change = { path: string; old: unknown; new: unknown };
type Pending = { template: ClipTemplate; changes: Change[]; unsupported: string[] };

interface Props {
  draft: ClipTemplate;
  onApply: (t: ClipTemplate) => void;
  visionAvailable?: boolean;
}

// Human labels for the change paths the assistant can touch.
const LABELS: Record<string, string> = {
  "subtitles.font_name": "Fuente",
  "subtitles.font_size": "Tamaño",
  "subtitles.primary_color": "Color texto",
  "subtitles.secondary_color": "Color resalte",
  "subtitles.outline_color": "Color contorno",
  "subtitles.back_color": "Color fondo",
  "subtitles.bold": "Negrita",
  "subtitles.outline": "Contorno",
  "subtitles.shadow": "Sombra",
  "subtitles.alignment": "Alineación",
  "subtitles.margin_v": "Margen vertical",
  "subtitles.animation": "Animación",
  "subtitles.words_per_line": "Palabras por línea",
  "layout.type": "Composición",
  "layout.wide_height_ratio": "Proporción wide",
};

const prettyPath = (p: string): string => {
  if (LABELS[p]) return LABELS[p];
  const [head, ...rest] = p.split(".");
  const group =
    { intro_title: "Hook", branding: "Logo", progress_bar: "Barra", bumpers: "Bumpers", layout: "Layout", subtitles: "Subtítulos" }[
      head
    ] ?? head;
  return rest.length ? `${group}: ${rest.join(" ")}` : group;
};

const isAssColor = (v: unknown) => typeof v === "string" && /^&H[0-9A-Fa-f]{8}$/.test(v);

// Human description of a layout (so a regions change reads as people, not JSON).
function describeLayout(l: ClipTemplate["layout"]): string {
  if (!l) return "—";
  if (l.type === "fullscreen") return "Pantalla completa";
  if (l.type === "split") return "1 invitado (close-up + plano abierto)";
  const parts = (l.regions ?? []).map((r) =>
    r.source.mode === "wide"
      ? "Plano abierto"
      : r.source.mode === "speaker"
        ? r.source.speaker_ref || "Persona"
        : "Quien habla",
  );
  return parts.length ? parts.join(" + ") : "Personalizado";
}

const ValueChip: React.FC<{ v: unknown }> = ({ v }) => {
  if (v === null || v === undefined || v === "") return <span className="text-slate-500">—</span>;
  if (typeof v === "boolean") return <span>{v ? "Sí" : "No"}</span>;
  if (isAssColor(v))
    return (
      <span className="inline-flex items-center gap-1">
        <span className="h-3 w-3 rounded-sm border border-slate-600" style={{ background: assToHex(v as string) }} />
        <span className="font-mono text-[10px]">{assToHex(v as string)}</span>
      </span>
    );
  if (typeof v === "number") return <span>{Math.round(v * 100) / 100}</span>;
  if (typeof v === "object") return <span className="text-slate-400">(varios)</span>;
  return <span className="truncate">{String(v)}</span>;
};

/**
 * Natural-language editor. The assistant proposes a change set; the user sees a
 * field-level diff + what it couldn't do, then explicitly Applies or Discards —
 * nothing mutates the draft until "Aplicar".
 */
export const TemplateChat: React.FC<Props> = ({ draft, onApply, visionAvailable }) => {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [image, setImage] = useState<{ name: string; b64: string } | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const onPickImage = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) {
      toast.error("La imagen supera 5 MB");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => setImage({ name: file.name, b64: String(reader.result) });
    reader.readAsDataURL(file);
  };

  const SUGGESTIONS = [
    "Captions grandes, una palabra por línea",
    "Resaltado verde",
    "Título inicial tipo hook",
    "Barra de progreso abajo",
  ];

  const send = async (override?: string) => {
    const text = (override ?? input).trim();
    if ((!text && !image) || busy) return;
    const userContent = image ? `${text} [📎 ${image.name}]`.trim() : text;
    const nextMsgs: Msg[] = [...messages, { role: "user", content: userContent }];
    setMessages(nextMsgs);
    setInput("");
    setBusy(true);
    setPending(null);
    const sentImage = image;
    setImage(null);
    try {
      const res = await TemplatesApi.chat({
        template: draft,
        messages: nextMsgs,
        image_b64: sentImage?.b64 ?? null,
      });
      setMessages([...nextMsgs, { role: "assistant", content: res.explanation }]);
      // Don't mutate the draft yet — let the user review and apply.
      setPending({ template: res.template, changes: res.changes ?? [], unsupported: res.unsupported ?? [] });
    } catch (e) {
      toast.error((e as Error).message);
      setMessages([...nextMsgs, { role: "assistant", content: `⚠️ ${(e as Error).message}` }]);
    } finally {
      setBusy(false);
    }
  };

  const applyPending = () => {
    if (!pending) return;
    onApply(pending.template);
    setMessages((m) => [...m, { role: "assistant", content: "✓ Cambios aplicados al preview." }]);
    setPending(null);
  };

  return (
    <div className="flex h-full flex-col bg-slate-950/40">
      <div className="flex items-center justify-between border-b border-slate-800 px-3 py-2.5 text-xs">
        <span className="inline-flex items-center gap-2 font-semibold text-slate-200">
          <Sparkles size={14} className="text-emerald-400" /> Asistente
        </span>
        <span className="inline-flex items-center gap-1.5 text-emerald-400/90">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" /> en línea
        </span>
      </div>

      <div className="flex flex-1 flex-col gap-2 overflow-y-auto p-3 text-sm">
        {messages.length === 0 && (
          <>
            <div className="self-start max-w-[90%] rounded-lg bg-slate-800 px-3 py-2 text-slate-200">
              ¡Hola! Describe el estilo que buscas. Te muestro qué cambiaría y tú decides si aplicarlo. También
              puedes adjuntar una imagen de referencia.
            </div>
            <div className="mt-1 flex flex-wrap gap-2">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  onClick={() => send(s)}
                  disabled={busy}
                  className="rounded-full border border-slate-700 px-3 py-1 text-xs text-slate-300 hover:border-emerald-500/60 hover:text-white disabled:opacity-40"
                >
                  {s}
                </button>
              ))}
            </div>
          </>
        )}
        {messages.map((m, i) => (
          <div
            key={i}
            className={`max-w-[85%] rounded-lg px-3 py-1.5 ${
              m.role === "user"
                ? "self-end bg-emerald-600/30 text-emerald-50"
                : "self-start bg-slate-800 text-slate-200"
            }`}
          >
            {m.content}
          </div>
        ))}

        {/* Proposed change set — review then apply. */}
        {pending && (
          <div className="self-stretch rounded-lg border border-emerald-500/30 bg-slate-900/80 p-3">
            {(() => {
              // Collapse all layout.* changes into one friendly "Composición" row;
              // raw region objects must never reach the user as [object Object].
              const layoutChanged = pending.changes.some((c) => c.path.startsWith("layout"));
              const rest = pending.changes.filter((c) => !c.path.startsWith("layout"));
              const rows = rest.length + (layoutChanged ? 1 : 0);
              if (rows === 0)
                return <p className="text-xs text-slate-400">El asistente no propuso cambios.</p>;
              return (
                <>
                  <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
                    Cambios propuestos
                  </p>
                  <ul className="flex flex-col gap-1.5">
                    {layoutChanged && (
                      <li className="flex items-center justify-between gap-2 text-xs">
                        <span className="text-slate-300">Composición</span>
                        <span className="text-emerald-300">
                          {describeLayout(pending.template.layout)}
                        </span>
                      </li>
                    )}
                    {rest.map((c) => (
                      <li key={c.path} className="flex items-center justify-between gap-2 text-xs">
                        <span className="text-slate-300">{prettyPath(c.path)}</span>
                        <span className="flex items-center gap-1.5 text-slate-400">
                          <ValueChip v={c.old} /> <span className="text-slate-600">→</span>{" "}
                          <span className="text-emerald-300">
                            <ValueChip v={c.new} />
                          </span>
                        </span>
                      </li>
                    ))}
                  </ul>
                </>
              );
            })()}

            {pending.unsupported.length > 0 && (
              <div className="mt-2 flex items-start gap-1.5 rounded-md border border-amber-500/30 bg-amber-500/5 px-2 py-1.5 text-xs text-amber-300/90">
                <AlertTriangle size={13} className="mt-0.5 shrink-0" />
                <span>
                  Aún no puedo: {pending.unsupported.join(", ")}.
                </span>
              </div>
            )}

            {pending.changes.length > 0 && (
              <div className="mt-3 flex items-center gap-2">
                <button
                  onClick={applyPending}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-500 px-3 py-1.5 text-xs font-semibold text-white hover:bg-emerald-400"
                >
                  <Check size={13} /> Aplicar cambios
                </button>
                <button
                  onClick={() => setPending(null)}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800"
                >
                  <Undo2 size={13} /> Descartar
                </button>
              </div>
            )}
          </div>
        )}

        {busy && <div className="self-start text-xs text-slate-500">pensando…</div>}
      </div>

      {image && (
        <div className="mx-2 mb-1 flex items-center gap-2 rounded-md bg-slate-800/70 px-2 py-1 text-xs text-slate-300">
          <span className="truncate">📎 {image.name}</span>
          <button onClick={() => setImage(null)} className="text-slate-500 hover:text-white">
            <X size={12} />
          </button>
        </div>
      )}

      <div className="flex items-center gap-2 border-t border-slate-800 p-2">
        <input
          ref={fileRef}
          type="file"
          accept="image/png,image/jpeg,image/webp"
          className="hidden"
          onChange={onPickImage}
        />
        <button
          onClick={() => fileRef.current?.click()}
          disabled={busy || !visionAvailable}
          title={visionAvailable ? "Adjuntar imagen de referencia" : "Adjuntar imagen requiere Claude Code"}
          className="inline-flex items-center justify-center rounded-lg border border-slate-700 p-2 text-slate-300 hover:bg-slate-800 disabled:opacity-40"
        >
          <ImagePlus size={15} />
        </button>
        <input
          className="flex-1 rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white placeholder:text-slate-500"
          placeholder="Describe el cambio…"
          value={input}
          disabled={busy}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
        />
        <button
          onClick={() => send()}
          disabled={busy || (!input.trim() && !image)}
          className="inline-flex items-center justify-center rounded-lg bg-emerald-500 p-2 text-white hover:bg-emerald-400 disabled:opacity-40"
        >
          <Send size={15} />
        </button>
      </div>
    </div>
  );
};
