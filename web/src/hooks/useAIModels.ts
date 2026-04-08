import { useState, useEffect } from 'react';
import { SettingsApi } from '../lib/api';

// Providers matching our Python ModelRegistry
export type AIProvider = 'openai' | 'anthropic' | 'google' | 'groq';

export interface AIModel {
    id: string; // Native Model ID directly supported by the SDK
    name: string; // E.g. "GPT-4o", "Claude 3.7 Sonnet"
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
                setModels(res.data || []);
                setError(null);
            } catch (err: any) {
                if (mounted) setError(err.message || "Failed to fetch native models");
            } finally {
                if (mounted) setLoading(false);
            }
        }

        fetchModels();
        return () => { mounted = false; };
    }, [fetchKey]);

    const refetch = () => setFetchKey(k => k + 1);

    const groupedModels: ModelGroup[] = [
        { provider: "anthropic" as AIProvider, label: "Anthropic", models: models.filter(m => m.provider === "anthropic") },
        { provider: "openai" as AIProvider, label: "OpenAI", models: models.filter(m => m.provider === "openai") },
        { provider: "groq" as AIProvider, label: "Groq (Llama)", models: models.filter(m => m.provider === "groq") },
        { provider: "google" as AIProvider, label: "Google (Gemini)", models: models.filter(m => m.provider === "google") },
    ].filter(g => g.models.length > 0);

    return { models, groupedModels, loading, error, refetch };
}
