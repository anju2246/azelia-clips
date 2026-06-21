import React, { useRef, useState } from "react";
import toast from "react-hot-toast";
import { Send, Sparkles, ImagePlus, X } from "lucide-react";
import { TemplatesApi, type ClipTemplate } from "../../lib/api";

interface Msg {
  role: "user" | "assistant";
  content: string;
}

interface Props {
  draft: ClipTemplate;
  onApply: (t: ClipTemplate) => void;
  visionAvailable?: boolean;
}

/**
 * Natural-language editor. Sends the current draft + chat history to the AI,
 * applies the returned template to the draft, and shows the explanation.
 * (Reference-image attach lands in T6.)
 */
export const TemplateChat: React.FC<Props> = ({ draft, onApply, visionAvailable }) => {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [image, setImage] = useState<{ name: string; b64: string } | null>(null);
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
    "Hazlo full-screen",
    "Resaltado verde",
    "Más palabras por línea",
    "Subtítulos más grandes",
  ];

  const send = async (override?: string) => {
    const text = (override ?? input).trim();
    if ((!text && !image) || busy) return;
    const userContent = image ? `${text} [📎 ${image.name}]`.trim() : text;
    const nextMsgs: Msg[] = [...messages, { role: "user", content: userContent }];
    setMessages(nextMsgs);
    setInput("");
    setBusy(true);
    const sentImage = image;
    setImage(null);
    try {
      const res = await TemplatesApi.chat({
        template: draft,
        messages: nextMsgs,
        image_b64: sentImage?.b64 ?? null,
      });
      onApply(res.template);
      setMessages([...nextMsgs, { role: "assistant", content: res.explanation }]);
    } catch (e) {
      toast.error((e as Error).message);
      setMessages([
        ...nextMsgs,
        { role: "assistant", content: `⚠️ ${(e as Error).message}` },
      ]);
    } finally {
      setBusy(false);
    }
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
              ¡Hola! Describe el estilo que buscas y lo aplico al instante. También puedes
              adjuntar una imagen de referencia.
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
          title={
            visionAvailable
              ? "Adjuntar imagen de referencia"
              : "Adjuntar imagen requiere Claude Code"
          }
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
