import { useState, useEffect } from 'react';

// Providers we care about
export type AIProvider = 'openai' | 'anthropic' | 'google' | 'meta';

export interface AIModel {
    id: string; // The OpenRouter ID, e.g. "openai/gpt-4o"
    name: string; // "GPT-4o"
    provider: AIProvider;
    context_length: number;
    description: string;
    is_reasoning?: boolean;
}

export interface ModelGroup {
    provider: AIProvider;
    models: AIModel[];
}

export function useAIModels() {
    const [models, setModels] = useState<AIModel[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        let mounted = true;

        async function fetchModels() {
            try {
                const res = await fetch("https://openrouter.ai/api/v1/models");
                if (!res.ok) throw new Error("Failed to fetch models");
                const data = await res.json();

                if (!mounted) return;

                const filtered: AIModel[] = [];

                for (const m of data.data) {
                    const id = m.id as string;
                    const name = m.name as string;

                    let provider: AIProvider | null = null;
                    if (id.startsWith("openai/")) provider = "openai";
                    else if (id.startsWith("google/")) provider = "google";
                    else if (id.startsWith("anthropic/")) provider = "anthropic";
                    else if (id.startsWith("meta-llama/")) provider = "meta";

                    // Only take our top 4 providers
                    if (provider) {
                        filtered.push({
                            id,
                            name,
                            provider,
                            context_length: m.context_length || 0,
                            description: m.description || "",
                            // Basic heuristic for reasoning models
                            is_reasoning: name.toLowerCase().includes("reason") || name.toLowerCase().includes("think") || id.includes("-r1")
                        });
                    }
                }

                // Sort models alphabetically for a clean list, prioritizing newest/best by name heuristics
                filtered.sort((a, b) => b.name.localeCompare(a.name));

                setModels(filtered);
                setError(null);
            } catch (err: any) {
                if (mounted) setError(err.message);
            } finally {
                if (mounted) setLoading(false);
            }
        }

        fetchModels();
        return () => { mounted = false; };
    }, []);

    const groupedModels: ModelGroup[] = [
        { provider: "openai", models: models.filter(m => m.provider === "openai") },
        { provider: "anthropic", models: models.filter(m => m.provider === "anthropic") },
        { provider: "google", models: models.filter(m => m.provider === "google") },
        { provider: "meta", models: models.filter(m => m.provider === "meta") },
    ];

    return { models, groupedModels, loading, error };
}
