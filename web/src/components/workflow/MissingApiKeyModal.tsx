import React, { useState } from "react";
import { Key, ArrowRight, X, AlertTriangle } from "lucide-react";
import { SettingsApi } from "../../lib/api";
import toast from "react-hot-toast";

interface MissingApiKeyModalProps {
  isOpen: boolean;
  onClose: () => void;
  onKeySaved: () => void;
}

const PROVIDERS = [
  {
    id: "anthropic",
    name: "Anthropic (Claude)",
    field: "anthropic_api_key" as const,
    ph: "sk-ant-...",
    url: "https://console.anthropic.com/settings/keys",
    modelField: "anthropic_model" as const,
    defaultModel: "claude-3.7-sonnet",
  },
  {
    id: "openai",
    name: "OpenAI (GPT)",
    field: "openai_api_key" as const,
    ph: "sk-...",
    url: "https://platform.openai.com/api-keys",
    modelField: "openai_model" as const,
    defaultModel: "gpt-4o",
  },
  {
    id: "groq",
    name: "Groq (Llama)",
    field: "groq_api_key" as const,
    ph: "gsk_...",
    url: "https://console.groq.com/keys",
    modelField: "groq_model" as const,
    defaultModel: "llama-3.3-70b-versatile",
  },
];

export const MissingApiKeyModal: React.FC<MissingApiKeyModalProps> = ({
  isOpen,
  onClose,
  onKeySaved,
}) => {
  const [selectedProvider, setSelectedProvider] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [saving, setSaving] = useState(false);

  if (!isOpen) return null;

  const provider = PROVIDERS.find((p) => p.id === selectedProvider);

  const handleSave = async () => {
    if (!provider || !apiKey.trim()) return;
    setSaving(true);
    try {
      const update: Record<string, string | string[]> = {
        [provider.field]: apiKey.trim(),
        [provider.modelField]: provider.defaultModel,
        ai_provider_order: [
          provider.id,
          ...["anthropic", "openai", "groq", "vertex"].filter(
            (p) => p !== provider.id,
          ),
        ],
      };
      await SettingsApi.updateSettings(update as any);
      toast.success("API key saved. You can now process videos.");
      setApiKey("");
      setSelectedProvider("");
      onKeySaved();
    } catch (e: any) {
      toast.error(e.message || "Error saving the API key");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="bg-zinc-900 border border-white/10 rounded-2xl w-full max-w-lg mx-4 shadow-2xl animate-in zoom-in-95 duration-300">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/10">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full bg-amber-500/10 flex items-center justify-center">
              <AlertTriangle className="w-5 h-5 text-amber-500" />
            </div>
            <div>
              <h3 className="text-white font-semibold">API Key Required</h3>
              <p className="text-xs text-zinc-500">
                You need at least one AI key to process videos
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-zinc-500 hover:text-white transition-colors p-1 rounded-lg hover:bg-white/5"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-5 space-y-4">
          <p className="text-sm text-zinc-400 leading-relaxed">
            Azelia uses AI models to analyze, curate, and extract the best
            moments from your videos. Pick a provider and paste your API key to
            get started.
          </p>

          {/* Provider Selection */}
          <div className="grid grid-cols-3 gap-2">
            {PROVIDERS.map((p) => (
              <button
                key={p.id}
                onClick={() => {
                  setSelectedProvider(p.id);
                  setApiKey("");
                }}
                className={`px-3 py-2.5 rounded-xl border text-sm font-medium transition-all text-center ${
                  selectedProvider === p.id
                    ? "bg-brand-500/20 border-brand-500 text-white"
                    : "bg-black/20 border-white/10 text-zinc-400 hover:border-white/20"
                }`}
              >
                {p.name.split("(")[0].trim()}
              </button>
            ))}
          </div>

          {/* Key Input */}
          {provider && (
            <div className="space-y-2 animate-in fade-in slide-in-from-top-2 duration-200">
              <div className="flex items-center justify-between">
                <label className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">
                  API Key
                </label>
                <a
                  href={provider.url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-[10px] text-brand-400 hover:text-brand-300 underline underline-offset-2 flex items-center gap-1"
                >
                  Get a key <ArrowRight className="w-3 h-3" />
                </a>
              </div>
              <div className="relative">
                <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                  <Key className="h-4 w-4 text-zinc-500" />
                </div>
                <input
                  type="password"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder={provider.ph}
                  className="w-full bg-black/60 border border-white/10 hover:border-white/20 rounded-xl pl-10 pr-4 py-3 text-sm text-zinc-200 placeholder-zinc-700 focus:outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500 font-mono transition-all"
                  autoFocus
                />
              </div>
              <p className="text-xs text-zinc-600">
                Stored in your local <code className="text-zinc-500">.env</code>{" "}
                — never leaves your machine.
              </p>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-6 py-4 border-t border-white/10">
          <button
            onClick={onClose}
            className="text-sm text-zinc-500 hover:text-white transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={!apiKey.trim() || apiKey.length < 20 || saving}
            className="flex items-center gap-2 px-5 py-2.5 bg-gradient-to-r from-brand-600 to-brand-500 text-white font-semibold rounded-xl hover:from-brand-500 transition-all disabled:opacity-50 disabled:cursor-not-allowed text-sm shadow-lg shadow-brand-500/20"
          >
            {saving ? "Saving…" : "Save and continue"}
          </button>
        </div>
      </div>
    </div>
  );
};
