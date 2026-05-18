import { useState, useEffect } from "react";
import { SettingsApi } from "../lib/api";

/**
 * v0.1.0 supported providers: Anthropic API + Claude Code (local subscription).
 * Other providers (Groq, OpenAI, Google) are intentionally hidden in UI even
 * if the backend ModelRegistry returns them.
 */
export type AIProvider =
  | "anthropic"
  | "claude_code"
  | "openai"
  | "google"
  | "groq";

export const ENABLED_PROVIDERS: AIProvider[] = ["claude_code", "anthropic"];

export interface AIModel {
  id: string;
  name: string;
  provider: AIProvider;
  context_length: number;
  description: string;
  is_reasoning?: boolean;
}

export interface ModelGroup {
  provider: AIProvider;
  models: AIModel[];
  label: string;
}

export function useAIModels() {
  const [models, setModels] = useState<AIModel[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [fetchKey, setFetchKey] = useState(0);

  useEffect(() => {
    let mounted = true;

    async function fetchModels() {
      setLoading(true);
      try {
        const res = await SettingsApi.getModels();
        if (!mounted) return;
        // Hide disabled providers at the boundary so downstream UI doesn't see them.
        const filtered = (res.data || []).filter((m: AIModel) =>
          ENABLED_PROVIDERS.includes(m.provider),
        );
        setModels(filtered);
        setError(null);
      } catch (err: unknown) {
        if (mounted)
          setError((err as Error).message || "Failed to fetch models");
      } finally {
        if (mounted) setLoading(false);
      }
    }

    fetchModels();
    return () => {
      mounted = false;
    };
  }, [fetchKey]);

  const refetch = () => setFetchKey((k) => k + 1);

  const groupedModels: ModelGroup[] = [
    {
      provider: "anthropic" as AIProvider,
      label: "Anthropic",
      models: models.filter((m) => m.provider === "anthropic"),
    },
  ].filter((g) => g.models.length > 0);

  return { models, groupedModels, loading, error, refetch };
}
