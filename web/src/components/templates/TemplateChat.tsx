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

  const send = async () => {
    const text = input.trim();
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
    <div className="flex flex-col rounded-xl border border-zinc-800 bg-zinc-950/60">
      <div className="flex items-center gap-2 border-b border-zinc-800 px-3 py-2 text-xs text-zinc-400">
        <Sparkles size={13} className="text-cyan-400" /> Asistente de templates
      </div>

      <div className="flex max-h-56 min-h-[5rem] flex-col gap-2 overflow-y-auto p-3 text-sm">
        {messages.length === 0 && (
          <p className="text-zinc-600">
            Pídeme cambios: “fuente más grande y resaltado verde”, “ponlo full-screen”…
          </p>
        )}
        {messages.map((m, i) => (
          <div
            key={i}
            className={`max-w-[85%] rounded-lg px-3 py-1.5 ${
              m.role === "user"
                ? "self-end bg-cyan-600/30 text-cyan-50"
                : "self-start bg-zinc-800 text-zinc-200"
            }`}
          >
            {m.content}
          </div>
        ))}
        {busy && <div className="self-start text-xs text-zinc-500">pensando…</div>}
      </div>

      {image && (
        <div className="mx-2 mb-1 flex items-center gap-2 rounded-md bg-zinc-800/70 px-2 py-1 text-xs text-zinc-300">
          <span className="truncate">📎 {image.name}</span>
          <button onClick={() => setImage(null)} className="text-zinc-500 hover:text-white">
            <X size={12} />
          </button>
        </div>
      )}

      <div className="flex items-center gap-2 border-t border-zinc-800 p-2">
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
          className="inline-flex items-center justify-center rounded-md border border-zinc-700 p-2 text-zinc-300 hover:bg-zinc-800 disabled:opacity-40"
        >
          <ImagePlus size={15} />
        </button>
        <input
          className="flex-1 rounded-md border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-sm text-white"
          placeholder="Describe el cambio…"
          value={input}
          disabled={busy}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
        />
        <button
          onClick={send}
          disabled={busy || (!input.trim() && !image)}
          className="inline-flex items-center justify-center rounded-md bg-white p-2 text-black hover:bg-zinc-200 disabled:opacity-40"
        >
          <Send size={15} />
        </button>
      </div>
    </div>
  );
};
