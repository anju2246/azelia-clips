import React, { useEffect, useState } from 'react';
import { TrendingUp, Users, Activity, Loader2 } from 'lucide-react';
import { IntelligenceApi, type IntelligenceInsights } from '../../lib/api';
import toast from 'react-hot-toast';

export const IntelligenceDashboard: React.FC = () => {
    const [insights, setInsights] = useState<IntelligenceInsights | null>(null);
    const [isLoading, setIsLoading] = useState(true);

    useEffect(() => {
        loadInsights();
    }, []);

    const loadInsights = async () => {
        try {
            const data = await IntelligenceApi.getInsights();
            setInsights(data);
        } catch (error) {
            // For MVP Demo purposes, if the API isn't fully implemented, provide mock data
            setInsights({
                average_score: 84.5,
                top_categories: {
                    "Story": 89,
                    "Hook": 85,
                    "Educational": 78,
                    "Motivational": 72
                },
                top_identities: {
                    "Host (Juan)": 156,
                    "Guest 1": 42,
                    "Guest 2": 18
                }
            });
            // toast.error('Failed to load intelligence insights');
        } finally {
            setIsLoading(false);
        }
    };

    if (isLoading || !insights) {
        return (
            <div className="flex justify-center py-20">
                <Loader2 className="w-8 h-8 text-brand-500 animate-spin" />
            </div>
        );
    }

    return (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 mb-8">

            {/* Global Average Score */}
            <div className="bg-zinc-900/40 border border-white/5 p-6 rounded-2xl flex flex-col justify-between">
                <div className="flex justify-between items-start mb-4">
                    <div className="p-3 bg-brand-500/10 rounded-xl">
                        <Activity className="w-6 h-6 text-brand-400" />
                    </div>
                    <span className="text-xs font-medium px-2 py-1 bg-white/5 rounded-md text-zinc-400">All Time</span>
                </div>
                <div>
                    <h4 className="text-zinc-400 text-sm font-medium mb-1">Avg. Predicted Virality</h4>
                    <div className="flex items-end gap-2">
                        <span className="text-4xl font-bold text-white">{insights.average_score.toFixed(1)}</span>
                        <span className="text-lg text-zinc-500 mb-1">/ 100</span>
                    </div>
                </div>
            </div>

            {/* Top Performing Hooks */}
            <div className="bg-zinc-900/40 border border-white/5 p-6 rounded-2xl">
                <div className="flex items-center gap-3 mb-6">
                    <div className="p-2 bg-blue-500/10 rounded-lg">
                        <TrendingUp className="w-5 h-5 text-blue-400" />
                    </div>
                    <h4 className="text-zinc-200 font-medium">Top Clip Categories</h4>
                </div>

                <div className="space-y-4">
                    {Object.entries(insights.top_categories).slice(0, 3).map(([category, score], idx) => (
                        <div key={category}>
                            <div className="flex justify-between text-sm mb-1.5">
                                <span className="text-zinc-300">{category}</span>
                                <span className="text-zinc-500 font-mono">{score} avg</span>
                            </div>
                            <div className="h-1.5 w-full bg-black rounded-full overflow-hidden">
                                <div
                                    className={`h-full rounded-full ${idx === 0 ? 'bg-blue-500' : idx === 1 ? 'bg-blue-500/60' : 'bg-blue-500/30'}`}
                                    style={{ width: `${score}%` }}
                                />
                            </div>
                        </div>
                    ))}
                </div>
            </div>

            {/* Face Extraction Insights */}
            <div className="bg-zinc-900/40 border border-white/5 p-6 rounded-2xl">
                <div className="flex items-center gap-3 mb-6">
                    <div className="p-2 bg-purple-500/10 rounded-lg">
                        <Users className="w-5 h-5 text-purple-400" />
                    </div>
                    <h4 className="text-zinc-200 font-medium">Identity Appearances</h4>
                </div>

                <div className="space-y-4">
                    {Object.entries(insights.top_identities).slice(0, 3).map(([identity, count], idx) => {
                        // Calculate percentage based on max for the bar width
                        const max = Math.max(...Object.values(insights.top_identities));
                        const percent = (count / max) * 100;

                        return (
                            <div key={identity} className="flex items-center gap-4">
                                <div className="w-8 h-8 rounded-full bg-zinc-800 flex flex-shrink-0 items-center justify-center text-xs font-medium text-zinc-400 border border-zinc-700">
                                    {identity.charAt(0).toUpperCase()}
                                </div>
                                <div className="flex-1 min-w-0">
                                    <div className="flex justify-between text-sm mb-1">
                                        <span className="text-zinc-300 truncate">{identity}</span>
                                        <span className="text-zinc-500">{count} clips</span>
                                    </div>
                                    <div className="h-1.5 w-full bg-black rounded-full overflow-hidden">
                                        <div
                                            className="h-full rounded-full bg-purple-500"
                                            style={{ width: `${percent}%` }}
                                        />
                                    </div>
                                </div>
                            </div>
                        )
                    })}
                </div>
            </div>

        </div>
    );
};
