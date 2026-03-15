import { useState, useEffect } from 'react';
import { SettingsApi } from '../lib/api';

// Providers matching our Python ModelRegistry
export type AIProvider = 'openai' | 'anthropic' | 'vertex' | 'groq';

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

    useEffect(() => {
        let mounted = true;

        async function fetchModels() {
            try {
                // Fetch dynamic models from our own backend which queries native SDKs securely
                const res = await SettingsApi.getModels();
                
                if (!mounted) return;
                
                // Fallback models in case the user has no API keys configured yet and the backend returns empty
                let finalModels: AIModel[] = res.data || [];
                
                if (finalModels.length === 0) {
                    finalModels = [
                        { id: "gpt-4o", name: "GPT-4o", provider: "openai", context_length: 128000, description: "OpenAI Flagship" },
                        { id: "claude-3-5-sonnet-latest", name: "Claude 3.5 Sonnet", provider: "anthropic", context_length: 200000, description: "Anthropic Flagship" },
                        { id: "llama-3.3-70b-versatile", name: "Llama 3.3 70B", provider: "groq", context_length: 131072, description: "Meta Open Source" },
                        { id: "gemini-2.5-pro", name: "Gemini 2.5 Pro", provider: "vertex", context_length: 1000000, description: "Google Vertex" }
                    ];
                }

                setModels(finalModels);
                setError(null);
            } catch (err: any) {
                if (mounted) setError(err.message || "Failed to fetch native models");
            } finally {
                if (mounted) setLoading(false);
            }
        }

        fetchModels();
        return () => { mounted = false; };
    }, []);

    const groupedModels: ModelGroup[] = [
        { provider: "anthropic" as AIProvider, label: "Anthropic", models: models.filter(m => m.provider === "anthropic") },
        { provider: "openai" as AIProvider, label: "OpenAI", models: models.filter(m => m.provider === "openai") },
        { provider: "groq" as AIProvider, label: "Groq (Llama / DeepSeek)", models: models.filter(m => m.provider === "groq") },
        { provider: "vertex" as AIProvider, label: "Google Vertex", models: models.filter(m => m.provider === "vertex") },
    ].filter(g => g.models.length > 0);

    return { models, groupedModels, loading, error };
}
