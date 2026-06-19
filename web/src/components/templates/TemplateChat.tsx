import React, { useState } from "react";
import toast from "react-hot-toast";
import { Send, Sparkles } from "lucide-react";
import { TemplatesApi, type ClipTemplate } from "../../lib/api";

interface Msg {
  role: "user" | "assistant";
  content: string;
}

interface Props {
  draft: ClipTemplate;
  onApply: (t: ClipTemplate) => void;
}

/**
 * Natural-language editor. Sends the current draft + chat history to the AI,
 * applies the returned template to the draft, and shows the explanation.
 * (Reference-image attach lands in T6.)
 */
export const TemplateChat: React.FC<Props> = ({ draft, onApply }) => {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);

  const send = async () => {
    const text = input.trim();
    if (!text || busy) return;
    const nextMsgs: Msg[] = [...messages, { role: "user", content: text }];
    setMessages(nextMsgs);
    setInput("");
    setBusy(true);
    try {
      const res = await TemplatesApi.chat({ template: draft, messages: nextMsgs });
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

      <div className="flex items-center gap-2 border-t border-zinc-800 p-2">
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
          disabled={busy || !input.trim()}
          className="inline-flex items-center justify-center rounded-md bg-white p-2 text-black hover:bg-zinc-200 disabled:opacity-40"
        >
          <Send size={15} />
        </button>
      </div>
    </div>
  );
};
