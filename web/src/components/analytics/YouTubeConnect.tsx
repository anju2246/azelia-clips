import React, { useEffect, useState } from "react";
import {
  Youtube,
  CheckCircle2,
  AlertCircle,
  RefreshCw,
  Loader2,
  Sparkles,
} from "lucide-react";
import toast from "react-hot-toast";
import { supabase } from "../../lib/supabase";
import { RetroactiveSyncModal } from "./RetroactiveSyncModal";
import { SyncProgressBubble } from "./SyncProgressBubble";

interface YouTubeStatus {
  connected: boolean;
  channel_name?: string;
  total_shorts: number;
  last_synced?: string;
}

interface YouTubeInsights {
  total_shorts: number;
  total_views: number;
  total_likes: number;
  avg_views: number;
  avg_duration: number;
  best_performing: { title: string; views: number; url: string }[];
  duration_breakdown: { range: string; count: number; avg_views: number }[];
}

const API_BASE = (import.meta.env?.PUBLIC_API_URL as string) || "/api";

async function fetchWithAuth(endpoint: string, options: RequestInit = {}) {
  const headers = new Headers(options.headers || {});
  try {
    const { data } = await supabase.auth.getSession();
    if (data?.session?.access_token) {
      headers.set("Authorization", `Bearer ${data.session.access_token}`);
    }
  } catch (e) {
    /* continue */
  }
  return fetch(`${API_BASE}${endpoint}`, { ...options, headers });
}

export const YouTubeConnect: React.FC = () => {
  const [status, setStatus] = useState<YouTubeStatus>({
    connected: false,
    total_shorts: 0,
  });
  const [insights, setInsights] = useState<YouTubeInsights | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSyncing, setIsSyncing] = useState(false);

  // Channel picker state
  const [channels, setChannels] = useState<any[]>([]);
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [showChannelPicker, setShowChannelPicker] = useState(false);
  const [manualHandle, setManualHandle] = useState("");
  const [showRetroactiveModal, setShowRetroactiveModal] = useState(false);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [hasSyncedHistorical, setHasSyncedHistorical] = useState(() => {
    if (typeof window !== "undefined") {
      return localStorage.getItem("az_historical_synced") === "true";
    }
    return false;
  });
  // ToS + Privacy acceptance gate — required by Google's verification
  // policy at the point of OAuth handoff. Persisted in localStorage so
  // users who already accepted during onboarding don't see it again.
  const [tosAccepted, setTosAccepted] = useState<boolean>(() => {
    if (typeof window !== "undefined") {
      return localStorage.getItem("az_tos_accepted") === "true";
    }
    return false;
  });

  useEffect(() => {
    const urlParams = new URLSearchParams(window.location.search);
    const code = urlParams.get("code");

    if (code) {
      // Remove code from URL to prevent re-triggering on refresh
      const newUrl =
        window.location.protocol +
        "//" +
        window.location.host +
        window.location.pathname;
      window.history.replaceState({ path: newUrl }, "", newUrl);

      handleOAuthCallback(code);
    } else {
      checkStatus();
    }
  }, []);

  const checkStatus = async () => {
    try {
      const res = await fetchWithAuth("/analytics/youtube/status");
      if (res.ok) {
        const data = await res.json();
        setStatus(data);
        if (data.connected && data.total_shorts > 0) {
          loadInsights();
        }
      }
    } catch (e) {
      /* not connected */
    } finally {
      setIsLoading(false);
    }
  };

  const loadInsights = async () => {
    try {
      const res = await fetchWithAuth("/analytics/youtube/insights");
      if (res.ok) {
        const data = await res.json();
        setInsights(data);
      }
    } catch (e) {
      /* no insights yet */
    }
  };

  const handleConnect = async () => {
    if (!tosAccepted) {
      toast.error("Please accept the Terms and Privacy Policy first.");
      return;
    }
    try {
      // Google OAuth requires exact string matching for redirect URIs, and generally prefers localhost over IPs.
      const baseOrigin = window.location.origin
        .replace("127.0.0.1", "localhost")
        .replace("0.0.0.0", "localhost");
      const redirectUri = baseOrigin + "/dashboard/intelligence";
      const res = await fetchWithAuth(
        `/auth/youtube/authorize?redirect_uri=${encodeURIComponent(redirectUri)}`,
      );

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Failed to start YouTube authorization");
      }

      const { url } = await res.json();
      window.location.href = url;
    } catch (error: any) {
      toast.error(error.message || "Failed to connect YouTube");
    }
  };

  const handleOAuthCallback = async (code: string) => {
    setIsLoading(true);
    const toastId = toast.loading("Connecting your YouTube channel...");

    try {
      const baseOrigin = window.location.origin
        .replace("127.0.0.1", "localhost")
        .replace("0.0.0.0", "localhost");
      const redirectUri = baseOrigin + "/dashboard/intelligence";
      const res = await fetchWithAuth("/analytics/youtube/sync-with-code", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code, redirect_uri: redirectUri }),
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Failed to connect YouTube");
      }

      const result = await res.json();

      // If backend asks us to pick a channel
      if (result.needs_channel_selection) {
        toast.dismiss(toastId);
        setChannels(result.channels || []);
        setAccessToken(result.access_token);
        setShowChannelPicker(true);
        setIsLoading(false);
        if (result.channels?.length === 0) {
          toast("No channels found. Enter your channel handle below.", {
            icon: "🔍",
          });
        } else {
          toast.success(
            `Found ${result.channels.length} channel(s). Pick the one to sync.`,
            { icon: "📺" },
          );
        }
        return;
      }

      // Direct sync (single channel)
      toast.success(
        `Synced ${result.total_shorts} videos from ${result.channel_name}!`,
        { id: toastId, icon: "🎬" },
      );
      setStatus({
        connected: true,
        channel_name: result.channel_name,
        total_shorts: result.total_shorts,
        last_synced: new Date().toISOString(),
      });
      await loadInsights();
      setTimeout(() => setShowRetroactiveModal(true), 1500);
    } catch (error: any) {
      toast.error(error.message || "Connection failed", { id: toastId });
    } finally {
      setIsLoading(false);
    }
  };

  const handleSelectChannel = async (channelId: string) => {
    if (!accessToken) return;
    setIsSyncing(true);
    const toastId = toast.loading("Syncing channel...");

    try {
      const res = await fetchWithAuth("/analytics/youtube/sync-with-code", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          access_token: accessToken,
          channel_id: channelId,
        }),
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Sync failed");
      }

      const result = await res.json();
      toast.success(
        `Synced ${result.total_shorts} videos from ${result.channel_name}!`,
        { id: toastId, icon: "🎬" },
      );
      setShowChannelPicker(false);
      setStatus({
        connected: true,
        channel_name: result.channel_name,
        total_shorts: result.total_shorts,
        last_synced: new Date().toISOString(),
      });
      await loadInsights();
      setTimeout(() => setShowRetroactiveModal(true), 1500);
    } catch (error: any) {
      toast.error(error.message || "Sync failed", { id: toastId });
    } finally {
      setIsSyncing(false);
    }
  };

  const handleManualChannel = async () => {
    if (!accessToken || !manualHandle.trim()) return;
    // Extract handle: support @handle, youtube.com/@handle, or channel URL
    let handle = manualHandle.trim();
    if (handle.includes("youtube.com/")) {
      const match = handle.match(/@[\w-]+/);
      if (match) handle = match[0];
    }
    if (!handle.startsWith("@")) handle = `@${handle}`;

    setIsSyncing(true);
    const toastId = toast.loading(`Looking up ${handle}...`);

    try {
      // Use YouTube API to resolve handle to channel ID
      const searchRes = await fetch(
        `https://www.googleapis.com/youtube/v3/channels?part=snippet,statistics,contentDetails&forHandle=${encodeURIComponent(handle.replace("@", ""))}`,
        { headers: { Authorization: `Bearer ${accessToken}` } },
      );

      if (!searchRes.ok || !(await searchRes.clone().json()).items?.length) {
        throw new Error(`Channel ${handle} not found`);
      }

      const channelData = await searchRes.json();
      const channelId = channelData.items[0].id;
      toast.dismiss(toastId);
      await handleSelectChannel(channelId);
    } catch (error: any) {
      toast.error(error.message || "Channel not found", { id: toastId });
      setIsSyncing(false);
    }
  };

  const handleResync = async () => {
    setIsSyncing(true);
    const toastId = toast.loading("Re-syncing YouTube data...");
    try {
      // Re-sync requires re-auth since tokens expire
      handleConnect();
    } catch (error: any) {
      toast.error(error.message || "Re-sync failed", { id: toastId });
      setIsSyncing(false);
    }
  };

  if (isLoading) {
    return (
      <div className="flex justify-center items-center py-12">
        <Loader2 className="w-8 h-8 text-red-500 animate-spin" />
        <span className="ml-3 text-zinc-400">Connecting to YouTube...</span>
      </div>
    );
  }

  // Channel picker UI
  if (showChannelPicker) {
    return (
      <div className="space-y-6">
        <div className="bg-zinc-900/40 border border-white/5 rounded-2xl p-6">
          <h3 className="text-xl font-bold text-white mb-2">
            Select Your Channel
          </h3>
          <p className="text-sm text-zinc-400 mb-6">
            We found multiple channels. Pick the one you want to sync:
          </p>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-6">
            {channels.map((ch) => (
              <button
                key={ch.id}
                onClick={() => handleSelectChannel(ch.id)}
                disabled={isSyncing}
                className="flex items-center gap-4 p-4 bg-zinc-800/60 hover:bg-zinc-700/60 border border-white/5 hover:border-red-500/30 rounded-xl transition-all cursor-pointer text-left disabled:opacity-50"
              >
                {ch.thumbnail && (
                  <img
                    src={ch.thumbnail}
                    alt={ch.title}
                    className="w-12 h-12 rounded-full object-cover"
                  />
                )}
                <div className="min-w-0 flex-1">
                  <p className="text-white font-semibold truncate">
                    {ch.title}
                  </p>
                  {ch.handle && (
                    <p className="text-sm text-zinc-500">{ch.handle}</p>
                  )}
                  <p className="text-xs text-zinc-600">
                    {Number(ch.subscribers).toLocaleString()} subs ·{" "}
                    {ch.video_count} videos
                  </p>
                </div>
              </button>
            ))}
          </div>

          <div className="border-t border-white/5 pt-4">
            <p className="text-sm text-zinc-500 mb-3">
              Channel not listed? Enter its handle (e.g., @inminentepodcast):
            </p>
            <div className="flex gap-2">
              <input
                type="text"
                value={manualHandle}
                onChange={(e) => setManualHandle(e.target.value)}
                placeholder="@channelhandle"
                className="flex-1 bg-zinc-800 border border-white/10 rounded-lg px-4 py-2 text-white placeholder-zinc-600 focus:outline-none focus:border-red-500/50"
                onKeyDown={(e) => e.key === "Enter" && handleManualChannel()}
              />
              <button
                onClick={handleManualChannel}
                disabled={isSyncing || !manualHandle.trim()}
                className="px-5 py-2 bg-red-600 hover:bg-red-500 text-white rounded-lg font-medium transition-colors cursor-pointer disabled:opacity-50"
              >
                {isSyncing ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  "Sync"
                )}
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Connection Card */}
      <div className="bg-zinc-900/40 border border-white/5 rounded-2xl p-6 relative overflow-hidden flex flex-col md:flex-row gap-6 items-center justify-between">
        <div className="absolute -right-20 -top-20 w-64 h-64 bg-red-500/10 rounded-full blur-3xl pointer-events-none"></div>

        <div className="flex items-start gap-4 z-10">
          <div
            className={`p-3 rounded-xl ${status.connected ? "bg-red-500/10 text-red-500" : "bg-zinc-800 text-zinc-400"}`}
          >
            <Youtube className="w-8 h-8" />
          </div>
          <div>
            <h3 className="text-xl font-bold text-white mb-1">
              YouTube Analytics
            </h3>
            {status.connected ? (
              <>
                <div className="flex items-center gap-2 text-sm text-green-400">
                  <CheckCircle2 className="w-4 h-4" /> Connected
                  {status.channel_name ? ` — ${status.channel_name}` : ""}
                </div>
                <p className="text-sm text-zinc-500 mt-1">
                  {status.total_shorts} videos synced
                  {status.last_synced
                    ? ` · Last synced ${new Date(status.last_synced).toLocaleDateString()}`
                    : ""}
                </p>
              </>
            ) : (
              <>
                <div className="flex items-center gap-2 text-sm text-zinc-500">
                  <AlertCircle className="w-4 h-4" /> Not Connected
                </div>
                <p className="text-sm text-zinc-400 mt-2 max-w-sm">
                  Connect your YouTube channel to see performance insights from
                  all your videos. You can connect any Google account — it
                  doesn't have to be the one you logged in with.
                </p>
              </>
            )}
          </div>
        </div>

        <div className="z-10 flex flex-wrap gap-3 w-full md:w-auto justify-end">
          {status.connected ? (
            <div className="flex gap-2 w-full justify-end flex-wrap">
              {!hasSyncedHistorical ? (
                <button
                  onClick={() => setShowRetroactiveModal(true)}
                  className="flex-1 md:flex-none flex items-center justify-center gap-2 px-6 py-2.5 bg-brand-500/20 hover:bg-brand-500/30 border border-brand-500/50 text-brand-300 rounded-xl font-medium transition-colors shadow-lg shadow-brand-500/10 cursor-pointer"
                >
                  <Sparkles className="w-4 h-4" /> Historical Sync
                </button>
              ) : (
                <div className="flex-1 md:flex-none flex items-center justify-center gap-2 px-6 py-2.5 bg-zinc-800/50 border border-white/10 text-zinc-400 rounded-xl font-medium">
                  <CheckCircle2 className="w-4 h-4 text-brand-500" /> History
                  processed
                </div>
              )}
              <button
                onClick={handleResync}
                disabled={isSyncing}
                className="flex-1 md:flex-none flex items-center justify-center gap-2 px-6 py-2.5 bg-white/5 hover:bg-white/10 border border-white/10 text-white rounded-xl font-medium transition-colors disabled:opacity-50"
              >
                <RefreshCw
                  className={`w-4 h-4 ${isSyncing ? "animate-spin" : ""}`}
                />
                {isSyncing ? "Syncing..." : "Re-sync"}
              </button>
            </div>
          ) : (
            <div className="flex flex-col gap-2 w-full md:w-auto md:items-end">
              {!tosAccepted && (
                <label
                  htmlFor="yt-tos-accept"
                  className="flex items-start gap-2 text-xs text-zinc-300 max-w-xs cursor-pointer"
                >
                  <input
                    id="yt-tos-accept"
                    type="checkbox"
                    checked={tosAccepted}
                    onChange={(e) => {
                      const v = e.target.checked;
                      setTosAccepted(v);
                      try {
                        if (v) localStorage.setItem("az_tos_accepted", "true");
                        else localStorage.removeItem("az_tos_accepted");
                      } catch {
                        /* ignore */
                      }
                    }}
                    className="mt-0.5 w-4 h-4 shrink-0 rounded border-zinc-600 bg-black/40 text-red-500 focus:ring-red-500/40 focus:ring-offset-0 cursor-pointer"
                  />
                  <span className="leading-snug">
                    I accept the{" "}
                    <a
                      href="https://azelia.ai/terms"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-red-400 hover:text-red-300 underline underline-offset-2"
                    >
                      Terms
                    </a>{" "}
                    and{" "}
                    <a
                      href="https://azelia.ai/privacy"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-red-400 hover:text-red-300 underline underline-offset-2"
                    >
                      Privacy Policy
                    </a>
                    .
                  </span>
                </label>
              )}
              <button
                onClick={handleConnect}
                disabled={!tosAccepted}
                title={
                  !tosAccepted
                    ? "Accept the Terms and Privacy Policy first."
                    : undefined
                }
                className="flex-1 md:flex-none flex items-center justify-center gap-2 px-6 py-2.5 bg-red-600 hover:bg-red-500 text-white rounded-xl font-medium transition-colors shadow-lg shadow-red-500/20 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed disabled:shadow-none"
              >
                <Youtube className="w-4 h-4" /> Connect YouTube
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Insights */}
      {insights && insights.total_shorts > 0 && (
        <YouTubeInsightsView insights={insights} />
      )}

      <RetroactiveSyncModal
        isOpen={showRetroactiveModal}
        onClose={() => setShowRetroactiveModal(false)}
        onSuccess={(jobId: string) => {
          setActiveJobId(jobId);
          setHasSyncedHistorical(true);
          localStorage.setItem("az_historical_synced", "true");
          setShowRetroactiveModal(false);
        }}
      />

      {activeJobId && (
        <SyncProgressBubble
          jobId={activeJobId}
          onDismiss={() => setActiveJobId(null)}
          onComplete={() => {
            // Refresh insights when done
            loadInsights();
          }}
        />
      )}
    </div>
  );
};

// ─── Insights View ──────────────────────────────────────────────────────────

const YouTubeInsightsView: React.FC<{ insights: YouTubeInsights }> = ({
  insights,
}) => {
  const formatNumber = (n: number) => {
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
    if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
    return n.toString();
  };

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard
          label="Total Videos"
          value={insights.total_shorts.toString()}
        />
        <StatCard
          label="Total Views"
          value={formatNumber(insights.total_views)}
        />
        <StatCard label="Avg. Views" value={formatNumber(insights.avg_views)} />
        <StatCard
          label="Total Likes"
          value={formatNumber(insights.total_likes)}
        />
      </div>

      {insights.best_performing.length > 0 && (
        <div className="bg-zinc-900/40 border border-white/5 rounded-2xl p-6">
          <h4 className="text-sm font-medium text-zinc-400 uppercase tracking-widest mb-4">
            🏆 Top Performing Videos
          </h4>
          <div className="space-y-3">
            {insights.best_performing.map((vid, i) => (
              <div
                key={i}
                className="flex items-center justify-between gap-4 py-2 border-b border-white/5 last:border-0"
              >
                <div className="flex items-center gap-3 min-w-0">
                  <span className="text-zinc-600 text-sm font-mono w-5">
                    #{i + 1}
                  </span>
                  <a
                    href={vid.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-zinc-200 text-sm truncate hover:text-white transition-colors"
                  >
                    {vid.title}
                  </a>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <span className="text-sm font-medium text-white">
                    {formatNumber(vid.views)}
                  </span>
                  <span className="text-xs text-zinc-500">views</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {insights.duration_breakdown.length > 0 && (
        <div className="bg-zinc-900/40 border border-white/5 rounded-2xl p-6">
          <h4 className="text-sm font-medium text-zinc-400 uppercase tracking-widest mb-4">
            ⏱️ Performance by Duration
          </h4>
          <div className="space-y-4">
            {insights.duration_breakdown.map((bucket) => {
              const maxViews = Math.max(
                ...insights.duration_breakdown.map((b) => b.avg_views),
              );
              const pct =
                maxViews > 0 ? (bucket.avg_views / maxViews) * 100 : 0;
              return (
                <div key={bucket.range}>
                  <div className="flex justify-between text-sm mb-1.5">
                    <span className="text-zinc-300">{bucket.range}</span>
                    <span className="text-zinc-500">
                      {bucket.count} videos · avg{" "}
                      {formatNumber(bucket.avg_views)} views
                    </span>
                  </div>
                  <div className="h-2 w-full bg-black rounded-full overflow-hidden">
                    <div
                      className="h-full rounded-full bg-red-500/70"
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
};

const StatCard: React.FC<{ label: string; value: string }> = ({
  label,
  value,
}) => (
  <div className="bg-zinc-900/40 border border-white/5 rounded-xl p-4">
    <p className="text-xs text-zinc-500 mb-1">{label}</p>
    <p className="text-2xl font-bold text-white">{value}</p>
  </div>
);
