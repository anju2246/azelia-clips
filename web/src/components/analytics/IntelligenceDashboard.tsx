import React, { useEffect, useState } from "react";
import { TrendingUp, Users, Activity, Loader2, Zap, Film } from "lucide-react";
import { supabase } from "../../lib/supabase";

interface PipelineStats {
  totalClips: number;
  totalEpisodes: number;
  avgViralityScore: number;
  topHookTypes: Record<string, number>;
  topCategories: Record<string, number>;
  avgDuration: number;
}

/**
 * MyPipelineStats — what Azelia (local) is doing with the creator's episodes.
 *
 * Shows clips generated, predicted virality, and top hook patterns detected
 * by the pipeline. Kept focused on the pipeline universe: no YouTube real
 * data, no IC Cascade comparison.
 */
export const MyPipelineStats: React.FC = () => {
  const [stats, setStats] = useState<PipelineStats | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [hasData, setHasData] = useState(false);

  useEffect(() => {
    loadStats();
  }, []);

  const loadStats = async () => {
    try {
      const API_BASE = (import.meta.env?.PUBLIC_API_URL as string) || "/api";
      const { data: session } = await supabase.auth.getSession();
      const headers: HeadersInit = { Accept: "application/json" };
      if (session?.session?.access_token) {
        headers["Authorization"] = `Bearer ${session.session.access_token}`;
      }

      const res = await fetch(`${API_BASE}/analytics/insights`, { headers });
      if (res.ok) {
        const data = await res.json();
        if (data && (data.total_clips > 0 || data.totalClips > 0)) {
          setStats({
            totalClips: data.total_clips || data.totalClips || 0,
            totalEpisodes: data.total_episodes || data.totalEpisodes || 0,
            avgViralityScore: data.average_score || data.avgViralityScore || 0,
            topHookTypes: data.top_hook_types || data.topHookTypes || {},
            topCategories: data.top_categories || data.topCategories || {},
            avgDuration: data.avg_duration || data.avgDuration || 0,
          });
          setHasData(true);
        }
      }
    } catch {
      /* show empty state */
    } finally {
      setIsLoading(false);
    }
  };

  if (isLoading) {
    return (
      <div className="flex justify-center py-8">
        <Loader2 className="w-6 h-6 text-brand-500 animate-spin" />
      </div>
    );
  }

  if (!hasData) {
    return (
      <div className="bg-zinc-900/40 border border-white/5 rounded-2xl p-8 text-center">
        <div className="w-14 h-14 mx-auto mb-4 bg-brand-500/10 rounded-2xl flex items-center justify-center">
          <Zap className="w-7 h-7 text-brand-400" />
        </div>
        <h3 className="text-lg font-semibold text-white mb-2">
          Your pipeline hasn't run yet
        </h3>
        <p className="text-sm text-zinc-400 max-w-md mx-auto mb-4">
          Process your first episode to see clips generated, predicted virality,
          and the hook patterns Azelia detected in your content.
        </p>
        <a
          href="/dashboard"
          className="inline-flex items-center gap-2 px-5 py-2.5 bg-brand-600 hover:bg-brand-500 text-white rounded-xl text-sm font-medium transition-colors"
        >
          <Film className="w-4 h-4" /> Go to dashboard
        </a>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
      <div className="bg-zinc-900/40 border border-white/5 p-6 rounded-2xl flex flex-col justify-between">
        <div className="flex justify-between items-start mb-4">
          <div className="p-3 bg-brand-500/10 rounded-xl">
            <Activity className="w-6 h-6 text-brand-400" />
          </div>
          <span className="text-xs font-medium px-2 py-1 bg-white/5 rounded-md text-zinc-400">
            All Time
          </span>
        </div>
        <div>
          <h4 className="text-zinc-400 text-sm font-medium mb-1">
            Avg. predicted virality
          </h4>
          <div className="flex items-end gap-2">
            <span className="text-4xl font-bold text-white">
              {stats!.avgViralityScore.toFixed(1)}
            </span>
            <span className="text-lg text-zinc-500 mb-1">/ 100</span>
          </div>
        </div>
      </div>

      <div className="bg-zinc-900/40 border border-white/5 p-6 rounded-2xl flex flex-col justify-between">
        <div className="flex justify-between items-start mb-4">
          <div className="p-3 bg-emerald-500/10 rounded-xl">
            <Film className="w-6 h-6 text-emerald-400" />
          </div>
          <span className="text-xs font-medium px-2 py-1 bg-white/5 rounded-md text-zinc-400">
            Pipeline
          </span>
        </div>
        <div>
          <h4 className="text-zinc-400 text-sm font-medium mb-1">
            Clips generated
          </h4>
          <div className="flex items-end gap-2">
            <span className="text-4xl font-bold text-white">
              {stats!.totalClips}
            </span>
            <span className="text-sm text-zinc-500 mb-1">
              from {stats!.totalEpisodes} episodes
            </span>
          </div>
        </div>
      </div>

      <div className="bg-zinc-900/40 border border-white/5 p-6 rounded-2xl">
        <div className="flex items-center gap-3 mb-6">
          <div className="p-2 bg-blue-500/10 rounded-lg">
            <TrendingUp className="w-5 h-5 text-blue-400" />
          </div>
          <h4 className="text-zinc-200 font-medium">
            Top hook patterns detected
          </h4>
        </div>

        <div className="space-y-4">
          {Object.entries(stats!.topHookTypes || stats!.topCategories)
            .slice(0, 3)
            .map(([name, score], idx) => (
              <div key={name}>
                <div className="flex justify-between text-sm mb-1.5">
                  <span className="text-zinc-300 capitalize">
                    {name.replace(/_/g, " ")}
                  </span>
                  <span className="text-zinc-500 font-mono">
                    {typeof score === "number" ? score : 0}
                  </span>
                </div>
                <div className="h-1.5 w-full bg-black rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full ${idx === 0 ? "bg-blue-500" : idx === 1 ? "bg-blue-500/60" : "bg-blue-500/30"}`}
                    style={{
                      width: `${Math.min(100, typeof score === "number" ? score : 0)}%`,
                    }}
                  />
                </div>
              </div>
            ))}
        </div>
      </div>
    </div>
  );
};

// Backwards-compatible default export (some callers may still reference
// IntelligenceDashboard). Composes the new pipeline-stats section without
// the CreatorSignalsCard — that lives in <MyContentIntelligence /> now.
export const IntelligenceDashboard: React.FC = () => <MyPipelineStats />;
