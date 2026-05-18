import React, { useEffect, useRef, useState } from "react";
import { SettingsApi, type UpdateSettingsRequest } from "../../lib/api";
import { supabase } from "../../lib/supabase";
import { DirectoryPicker } from "../settings/DirectoryPicker";
import {
  ChevronDown,
  ChevronRight,
  Key,
  Loader2,
  Sparkles,
  FolderOpen,
  ArrowRight,
  ArrowLeft,
  CheckCircle2,
  User,
  Target,
  BarChart,
  Youtube,
  Link as LinkIcon,
  Shield,
} from "lucide-react";
import toast from "react-hot-toast";
import { RetroactiveSyncModal } from "../analytics/RetroactiveSyncModal";
import {
  SearchableCombobox,
  type ComboboxItem,
} from "../ui/SearchableCombobox";
import { fetchTaxonomy } from "../../lib/taxonomy";

const API_BASE = (import.meta.env?.PUBLIC_API_URL as string) || "/api";

// Synchronous belt-and-suspenders: if the user is on /onboarding and
// localStorage still claims onboarding is complete, that's a contradiction
// (server must have reset them). Wipe stale flags before any state hook
// initialises from localStorage. This complements the async server check
// inside the component for the case when /auth/onboarding-status fails.
if (
  typeof window !== "undefined" &&
  window.location.pathname.startsWith("/onboarding") &&
  window.localStorage.getItem("az_onboarding_complete") === "true"
) {
  [
    "az_onboard_step",
    "az_onboard_profile",
    "az_onboard_telemetry",
    "az_onboard_form",
    "az_historical_synced",
    "az_onboarding_complete",
  ].forEach((k) => window.localStorage.removeItem(k));
}

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

export const OnboardingWizard: React.FC = () => {
  const [showProCard, setShowProCard] = useState(false);
  const [step, setStep] = useState<1 | 2 | 3 | 4>(() => {
    if (typeof window !== "undefined") {
      const saved = localStorage.getItem("az_onboard_step");
      if (saved) return parseInt(saved) as 1 | 2 | 3 | 4;
    }
    return 1;
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [showDirPicker, setShowDirPicker] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);

  // Core settings
  const [formData, setFormData] = useState<Partial<UpdateSettingsRequest>>({});

  // Strategic Profiling (Step 2)
  const [profile, setProfile] = useState(() => {
    if (typeof window !== "undefined") {
      const saved = localStorage.getItem("az_onboard_profile");
      if (saved) return JSON.parse(saved);
    }
    return {
      content_niche: "",
      user_role: "",
      primary_goal: "",
      region: "",
      episode_format: "",
      language: "",
    };
  });

  // Canonical taxonomies served by /api/taxonomy (single source of truth).
  // Language is auto-detected per episode from the transcript, so we don't
  // load the language list here — Settings → Advanced exposes the override
  // for bilingual podcasts.
  const [niches, setNiches] = useState<ComboboxItem[]>([]);
  const [countries, setCountries] = useState<ComboboxItem[]>([]);
  useEffect(() => {
    fetchTaxonomy()
      .then((bundle) => {
        setNiches(bundle.niches);
        setCountries(bundle.countries);
      })
      .catch((err) => console.warn("Taxonomy fetch failed", err));
  }, []);

  // Telemetry (Step 3) - Opt-in: default OFF, user must explicitly enable
  const [telemetry, setTelemetry] = useState(() => {
    if (typeof window !== "undefined") {
      return localStorage.getItem("az_onboard_telemetry") === "true";
    }
    return false;
  });

  // Terms & Conditions
  const [acceptedTerms, setAcceptedTerms] = useState(false);

  // YouTube connection state
  const [ytConnected, setYtConnected] = useState(false);
  const [ytChannelName, setYtChannelName] = useState("");
  const [ytConnecting, setYtConnecting] = useState(false);
  const [ytChannels, setYtChannels] = useState<any[]>([]);
  const [ytAccessToken, setYtAccessToken] = useState<string | null>(null);
  const [ytShowPicker, setYtShowPicker] = useState(false);
  const [ytManualHandle, setYtManualHandle] = useState("");
  const [showRetroactiveModal, setShowRetroactiveModal] = useState(false);
  const [hasSyncedHistorical, setHasSyncedHistorical] = useState(() => {
    if (typeof window !== "undefined") {
      return localStorage.getItem("az_historical_synced") === "true";
    }
    return false;
  });

  const PROVIDERS: Record<
    string,
    {
      name: string;
      desc: string;
      field: keyof UpdateSettingsRequest;
      modelField: keyof UpdateSettingsRequest;
      ph: string;
      keyUrl: string;
    }
  > = {
    anthropic: {
      name: "Anthropic (Claude)",
      desc: "Best for long-form content curation",
      field: "anthropic_api_key",
      modelField: "anthropic_model",
      ph: "sk-ant-...",
      keyUrl: "https://console.anthropic.com/settings/keys",
    },
    openai: {
      name: "OpenAI (GPT)",
      desc: "High-quality reasoning",
      field: "openai_api_key",
      modelField: "openai_model",
      ph: "sk-...",
      keyUrl: "https://platform.openai.com/api-keys",
    },
    groq: {
      name: "Groq",
      desc: "Ultra-fast inference, free tier",
      field: "groq_api_key",
      modelField: "groq_model",
      ph: "gsk_...",
      keyUrl: "https://console.groq.com/keys",
    },
    google: {
      name: "Google (Gemini)",
      desc: "Gemini 2.5 Pro — API key simple",
      field: "google_api_key",
      modelField: "google_model",
      ph: "AIza...",
      keyUrl: "https://aistudio.google.com/apikey",
    },
  };

  // v0.1.0: only Anthropic is exposed. Claude Code is offered separately
  // via the auto-detect card above. Other providers come back in v0.2.
  const providerOrder = ["anthropic"];

  // Step 4 state: primary provider + optional extras
  const [primaryProvider, setPrimaryProvider] = useState("");
  const [extraProviders, setExtraProviders] = useState<string[]>([]);
  const [detectedModels, setDetectedModels] = useState<Record<string, string>>(
    {},
  );
  const [detectingProvider, setDetectingProvider] = useState<string | null>(
    null,
  );
  const detectTimers = React.useRef<
    Record<string, ReturnType<typeof setTimeout>>
  >({});

  // Claude Code detection — checked once on mount.
  // If active, the user gets a 'Use Claude Code (no key needed)' shortcut and
  // can skip configuring an API key entirely.
  const [claudeCode, setClaudeCode] = useState<{
    active: boolean;
    method?: string;
  } | null>(null);
  useEffect(() => {
    fetchWithAuth("/providers")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (d?.claude_code)
          setClaudeCode({
            active: !!d.claude_code.active,
            method: d.claude_code.auth_method,
          });
      })
      .catch(() => setClaudeCode({ active: false }));
  }, []);

  const [detectionErrors, setDetectionErrors] = useState<
    Record<string, string>
  >({});

  const detectModelForProvider = async (
    providerId: string,
    keyValue: string,
  ) => {
    // Clear previous result immediately so stale data never persists
    setDetectedModels((prev) => {
      const n = { ...prev };
      delete n[providerId];
      return n;
    });
    setDetectionErrors((prev) => {
      const n = { ...prev };
      delete n[providerId];
      return n;
    });

    if (keyValue.trim().length < 12) return;

    clearTimeout(detectTimers.current[providerId]);
    detectTimers.current[providerId] = setTimeout(async () => {
      const cfg = PROVIDERS[providerId];
      setDetectingProvider(providerId);
      try {
        // 1. Save the key — check for 422 (format validation error)
        const saveRes = await fetchWithAuth("/settings", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ [cfg.field]: keyValue }),
        });
        if (!saveRes.ok) {
          if (saveRes.status === 422) {
            const err = await saveRes.json().catch(() => ({}));
            const msg = err.detail || "Invalid API key format";
            setDetectionErrors((prev) => ({ ...prev, [providerId]: msg }));
          } else {
            setDetectionErrors((prev) => ({
              ...prev,
              [providerId]: "Could not save the key",
            }));
          }
          return;
        }
        // 2. Force registry refresh and get live models
        const res = await fetchWithAuth("/models/refresh", { method: "POST" });
        if (!res.ok) throw new Error("refresh failed");
        const data = await res.json();
        const providerModels: any[] = (data.data || []).filter(
          (m: any) => m.provider === providerId,
        );
        if (providerModels.length > 0) {
          const best = providerModels[0].id;
          setDetectedModels((prev) => ({ ...prev, [providerId]: best }));
          setDetectionErrors((prev) => {
            const n = { ...prev };
            delete n[providerId];
            return n;
          });
          handleUpdate({
            [cfg.modelField]: best,
          } as Partial<UpdateSettingsRequest>);
        } else {
          setDetectionErrors((prev) => ({
            ...prev,
            [providerId]: "Invalid key or no model access",
          }));
        }
      } catch {
        setDetectionErrors((prev) => ({
          ...prev,
          [providerId]: "Could not verify the key",
        }));
      } finally {
        setDetectingProvider(null);
      }
    }, 1200);
  };

  const ROLES = [
    { id: "solo_creator", label: "Solo creator" },
    { id: "video_editor", label: "Freelance video editor" },
    { id: "agency", label: "Agency (multi-client)" },
    { id: "network_producer", label: "Network producer" },
  ];
  const GOALS = [
    { id: "grow_audience", label: "Grow my audience (virality)" },
    { id: "save_time", label: "Save editing time" },
    { id: "monetize", label: "Monetize / sell products" },
  ];
  const FORMATS = [
    { id: "interview", label: "Interview (host + guest)" },
    { id: "solo", label: "Solo / monologue" },
    { id: "co_host", label: "Co-hosts (2+ speakers)" },
    { id: "panel", label: "Panel (3+ participants)" },
    { id: "narrative", label: "Narrative / storytelling" },
  ];

  const stripMasked = (data: Record<string, any>) => {
    // Always remove all API key fields from onboarding state —
    // they must never be pre-filled (not from server masked values, not from localStorage cache)
    const keyFields = [
      "groq_api_key",
      "openai_api_key",
      "anthropic_api_key",
      "google_api_key",
    ];
    const cleaned = { ...data };
    for (const f of keyFields) {
      delete cleaned[f];
    }
    return cleaned;
  };

  useEffect(() => {
    const init = async () => {
      // Detect a true fresh start: server says onboarding isn't complete
      // AND the profile has no required data yet. In that case, wipe any
      // stale localStorage from a previous session so we land on step 1
      // with empty fields (instead of replaying old answers).
      try {
        const statusRes = await fetchWithAuth("/auth/onboarding-status");
        if (statusRes.ok) {
          const status = await statusRes.json();
          const freshStart =
            !status.onboarding_complete && !status.data_complete;
          if (freshStart) {
            [
              "az_onboard_step",
              "az_onboard_profile",
              "az_onboard_telemetry",
              "az_onboard_form",
              "az_historical_synced",
              "az_onboarding_complete",
            ].forEach((k) => localStorage.removeItem(k));
            setStep(1);
            setProfile({
              content_niche: "",
              user_role: "",
              primary_goal: "",
              region: "",
              episode_format: "",
              language: "",
            });
            setTelemetry(false);
            setHasSyncedHistorical(false);
          }
        }
      } catch {
        /* gate will re-check on each render */
      }

      try {
        const existing = await SettingsApi.getSettings();
        const savedForm = localStorage.getItem("az_onboard_form");
        if (savedForm) {
          setFormData(stripMasked({ ...existing, ...JSON.parse(savedForm) }));
        } else {
          setFormData(stripMasked(existing));
        }
      } catch (e) {
        console.warn("Could not load existing settings", e);
      }

      // Check if YouTube is already connected
      try {
        const res = await fetchWithAuth("/analytics/youtube/status");
        if (res.ok) {
          const data = await res.json();
          if (data.connected) {
            setYtConnected(true);
            setYtChannelName(data.channel_name || "Connected");
          }
        }
      } catch (e) {
        /* not connected */
      }

      // Check for YouTube OAuth callback
      const urlParams = new URLSearchParams(window.location.search);
      const code = urlParams.get("code");
      if (code) {
        window.history.replaceState({}, "", window.location.pathname);
        setStep(3);
        setLoading(false);
        handleYouTubeCallback(code);
        return;
      }

      setLoading(false);
    };
    init();
  }, []);
  // Save state to localStorage as it changes
  useEffect(() => {
    if (typeof window !== "undefined") {
      localStorage.setItem("az_onboard_step", String(step));
      localStorage.setItem("az_onboard_profile", JSON.stringify(profile));
      localStorage.setItem("az_onboard_telemetry", String(telemetry));
      localStorage.setItem("az_historical_synced", String(hasSyncedHistorical));
      if (Object.keys(formData).length > 0) {
        // Never persist API keys to localStorage
        const {
          groq_api_key,
          openai_api_key,
          anthropic_api_key,
          google_api_key,
          ...safeForm
        } = formData as any;
        localStorage.setItem("az_onboard_form", JSON.stringify(safeForm));
      }
    }
  }, [step, profile, telemetry, formData]);

  useEffect(() => {
    boxRef.current?.scrollTo({ top: 0, behavior: "smooth" });
  }, [step]);

  const handleUpdate = (updates: Partial<UpdateSettingsRequest>) => {
    setFormData((prev) => ({ ...prev, ...updates }));
  };

  // v0.1.0: 3 visible steps — Workspace (1) → YouTube optional (3) → AI (4).
  // Step 2 (strategic profile) is skipped — it was tied to the central backend.
  const handleNext = () =>
    setStep((prev) => {
      if (prev === 1) return 3;
      return (prev + 1) as 1 | 2 | 3 | 4;
    });
  const handlePrev = () =>
    setStep((prev) => {
      if (prev === 4) return 3;
      if (prev === 3) return 1;
      return (prev - 1) as 1 | 2 | 3 | 4;
    });

  const handleFinish = async () => {
    setSaving(true);
    try {
      // 1. Sync Profile to Supabase. Use upsert so the wizard works even
      // when the profile row doesn't exist yet (deleted during testing,
      // or auth.users insert trigger never created one). `id` matches
      // auth.uid() so RLS still scopes the write to this user.
      const {
        data: { user },
      } = await supabase.auth.getUser();
      if (user) {
        await supabase.from("profiles").upsert(
          {
            id: user.id,
            email: user.email,
            content_niche: profile.content_niche,
            user_role: profile.user_role,
            primary_goal: profile.primary_goal,
            preferences: {
              region: profile.region,
              episode_format: profile.episode_format,
              language: profile.language,
            },
          },
          { onConflict: "id" },
        );
      }

      // 2. Sync Local Settings (Env)
      await SettingsApi.updateSettings({ ...formData });

      // 3. Save Telemetry Consent via API
      try {
        await fetchWithAuth("/telemetry/consent", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ enabled: telemetry }),
        });
      } catch {
        /* non-critical — telemetry preference saved on next settings visit */
      }
      // 4. Clear local storage checkpoints & mark as complete (DB + localStorage)
      localStorage.removeItem("az_onboard_step");
      localStorage.removeItem("az_onboard_profile");
      localStorage.removeItem("az_onboard_telemetry");
      localStorage.removeItem("az_onboard_form");
      localStorage.setItem("az_onboarding_complete", "true");
      try {
        await fetchWithAuth("/auth/onboarding-complete", { method: "POST" });
      } catch {
        /* non-critical — gate will re-check on next login */
      }

      toast.success("Welcome to Azelia Clips!");
      setShowProCard(true);
    } catch (e) {
      console.error("Failed to save onboarding data", e);
      toast.error("Hubo un error guardando tu perfil.");
      setSaving(false);
    }
  };

  const handleYouTubeConnect = async () => {
    try {
      // Google OAuth requires exact string matching for redirect URIs, and generally prefers localhost over IPs.
      const baseOrigin = window.location.origin
        .replace("127.0.0.1", "localhost")
        .replace("0.0.0.0", "localhost");
      const redirectUri = baseOrigin + "/onboarding";
      const res = await fetchWithAuth(
        `/auth/youtube/authorize?redirect_uri=${encodeURIComponent(redirectUri)}`,
      );
      if (!res.ok) throw new Error("Failed to start authorization");
      const { url } = await res.json();
      window.location.href = url;
    } catch (error: any) {
      toast.error(error.message || "Failed to connect YouTube");
    }
  };

  const handleYouTubeCallback = async (code: string) => {
    setYtConnecting(true);
    const toastId = toast.loading("Connecting YouTube...");
    try {
      const baseOrigin = window.location.origin
        .replace("127.0.0.1", "localhost")
        .replace("0.0.0.0", "localhost");
      const redirectUri = baseOrigin + "/onboarding";
      const res = await fetchWithAuth("/analytics/youtube/sync-with-code", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code, redirect_uri: redirectUri }),
      });
      if (!res.ok)
        throw new Error((await res.json()).detail || "Connection failed");
      const result = await res.json();

      if (result.needs_channel_selection) {
        toast.dismiss(toastId);
        setYtChannels(result.channels || []);
        setYtAccessToken(result.access_token);
        setYtShowPicker(true);
        toast.success(
          `Found ${result.channels?.length || 0} channel(s). Pick the one to sync.`,
          { icon: "📺" },
        );
      } else {
        toast.success(
          `Connected — ${result.total_shorts} videos synced from ${result.channel_name}.`,
          { id: toastId, icon: "🔗" },
        );
        setYtConnected(true);
        setYtChannelName(result.channel_name);
        // Gate the retroactive sync modal on having an AI key — the
        // sync calls Claude per video, so without a key it 401s and
        // produces no data. New users haven't reached step 4 yet.
        if (!hasSyncedHistorical && hasAnyKey) {
          setTimeout(() => setShowRetroactiveModal(true), 800);
        }
        // If coming back from YouTube OAuth during the optional Pro step (removed v0.1.0), go to dashboard
        if (showProCard) {
          setTimeout(() => window.location.replace("/dashboard"), 1500);
        }
      }
    } catch (error: any) {
      toast.error(error.message || "Connection failed", { id: toastId });
    } finally {
      setYtConnecting(false);
    }
  };

  const handleYtSelectChannel = async (channelId: string) => {
    if (!ytAccessToken) return;
    setYtConnecting(true);
    const toastId = toast.loading("Syncing channel...");
    try {
      const res = await fetchWithAuth("/analytics/youtube/sync-with-code", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          access_token: ytAccessToken,
          channel_id: channelId,
        }),
      });
      if (!res.ok) throw new Error((await res.json()).detail || "Sync failed");
      const result = await res.json();
      toast.success(
        `Synced ${result.total_shorts} videos from ${result.channel_name}!`,
        { id: toastId, icon: "🎬" },
      );
      setYtConnected(true);
      setYtChannelName(result.channel_name);
      setYtShowPicker(false);
      if (!hasSyncedHistorical && hasAnyKey) {
        setTimeout(() => setShowRetroactiveModal(true), 1500);
      }
    } catch (error: any) {
      toast.error(error.message || "Sync failed", { id: toastId });
    } finally {
      setYtConnecting(false);
    }
  };

  const handleYtManualHandle = async () => {
    if (!ytAccessToken || !ytManualHandle.trim()) return;
    let handle = ytManualHandle.trim();
    if (handle.includes("youtube.com/")) {
      const match = handle.match(/@[\w-]+/);
      if (match) handle = match[0];
    }
    if (!handle.startsWith("@")) handle = `@${handle}`;
    setYtConnecting(true);
    const toastId = toast.loading(`Looking up ${handle}...`);
    try {
      const searchRes = await fetch(
        `https://www.googleapis.com/youtube/v3/channels?part=snippet,statistics,contentDetails&forHandle=${encodeURIComponent(handle.replace("@", ""))}`,
        { headers: { Authorization: `Bearer ${ytAccessToken}` } },
      );
      if (!searchRes.ok) throw new Error(`Channel ${handle} not found`);
      const data = await searchRes.json();
      if (!data.items?.length) throw new Error(`Channel ${handle} not found`);
      toast.dismiss(toastId);
      await handleYtSelectChannel(data.items[0].id);
    } catch (error: any) {
      toast.error(error.message || "Channel not found", { id: toastId });
      setYtConnecting(false);
    }
  };

  const handleSocialConnect = (platform: string) => {
    toast("Coming soon — TikTok integration", { icon: "🔜" });
  };

  // v0.1.0: Claude Code OR Anthropic API key is sufficient.
  // (Other provider fields stay only as safety net in case formData was hydrated from legacy localStorage.)
  const hasAnyKey =
    !!claudeCode?.active ||
    [
      formData.groq_api_key,
      formData.openai_api_key,
      formData.anthropic_api_key,
      formData.google_api_key,
    ].some(
      (key) =>
        typeof key === "string" &&
        key.trim().length >= 20 &&
        !key.includes("..."),
    );

  if (loading)
    return (
      <div className="flex justify-center items-center py-20">
        <Loader2 className="w-8 h-8 text-brand-500 animate-spin" />
      </div>
    );

  // showProCard was a SaaS-era Pro tier upsell — removed in v0.1.0.
  // If anything sets showProCard=true, redirect straight to dashboard.
  if (showProCard) {
    if (typeof window !== "undefined") window.location.replace("/dashboard");
    return null;
  }

  return (
    <div
      ref={boxRef}
      className="bg-zinc-900/60 border border-white/10 rounded-3xl p-8 backdrop-blur-xl shadow-2xl relative transition-all duration-500 h-[75vh] overflow-y-auto"
    >
      {/* Progress indicator — v0.1.0 has 3 visible steps: Workspace, YouTube (optional), AI */}
      <div className="flex items-center gap-2 mb-8">
        {[1, 3, 4].map((i) => (
          <div
            key={i}
            className={`flex-1 h-1.5 rounded-full transition-colors duration-300 ${step >= i ? "bg-brand-500 shadow-[0_0_10px_rgba(168,85,247,0.5)]" : "bg-zinc-800"}`}
          />
        ))}
      </div>

      {/* STEP 1: WORKSPACE */}
      {step === 1 && (
        <div className="space-y-6 animate-in fade-in slide-in-from-right-4 duration-500">
          <div>
            <h1 className="text-3xl font-bold bg-gradient-to-r from-white to-zinc-400 bg-clip-text text-transparent">
              Let's set up your workspace
            </h1>
            <p className="text-zinc-400 mt-2 text-lg">
              Azelia processes your videos locally. Tell us your project's name
              and where to find the material.
            </p>
          </div>

          <div className="space-y-5 mt-8">
            <div>
              <label className="block text-sm font-medium text-zinc-300 mb-2">
                Podcast Name
              </label>
              <input
                type="text"
                className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-3 text-white placeholder-zinc-600 focus:outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500 transition-all font-mono"
                placeholder="Ej: The Inminente Podcast"
                value={formData.podcast_name || ""}
                onChange={(e) => handleUpdate({ podcast_name: e.target.value })}
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-zinc-300 mb-2">
                Base Video Directory
              </label>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={formData.podcast_dir || ""}
                  onChange={(e) =>
                    handleUpdate({ podcast_dir: e.target.value })
                  }
                  className="flex-1 bg-black/40 border border-white/10 rounded-xl px-4 py-3 text-white placeholder-zinc-600 focus:outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500 transition-all font-mono text-sm"
                  placeholder="/Users/name/Documents/Podcasts/"
                />
                <button
                  type="button"
                  onClick={async () => {
                    try {
                      // @ts-ignore — File System Access API
                      const dirHandle = await window.showDirectoryPicker({
                        mode: "read",
                      });
                      const folderName = dirHandle.name;
                      toast.loading(`Buscando "${folderName}"...`, {
                        id: "resolve",
                      });

                      const res = await fetchWithAuth(
                        `/resolve-path?name=${encodeURIComponent(folderName)}`,
                      );
                      const data = await res.json();

                      if (data.count === 1) {
                        handleUpdate({ podcast_dir: data.matches[0] });
                        toast.success(`Encontrado: ${data.matches[0]}`, {
                          id: "resolve",
                        });
                      } else if (data.count > 1) {
                        handleUpdate({ podcast_dir: data.matches[0] });
                        toast.success(
                          `${data.count} coincidencias, usando: ${data.matches[0]}`,
                          { id: "resolve" },
                        );
                      } else {
                        toast.error(
                          `Could not find "${folderName}". Use the manual picker.`,
                          { id: "resolve" },
                        );
                        setShowDirPicker(true);
                      }
                    } catch (err: any) {
                      if (err.name === "AbortError") return;
                      setShowDirPicker(true);
                    }
                  }}
                  className="px-4 py-3 bg-white/5 hover:bg-white/10 border border-white/10 rounded-xl text-sm text-zinc-300 transition-colors flex items-center gap-2 whitespace-nowrap cursor-pointer"
                >
                  <FolderOpen className="w-4 h-4" /> Buscar
                </button>
              </div>
              <p className="text-xs text-zinc-500 mt-2">
                Use the native picker or type the path. Videos must live here or
                in subfolders.
              </p>

              {/* Fallback: server-side picker */}
              <DirectoryPicker
                isOpen={showDirPicker}
                currentPath={formData.podcast_dir || ""}
                onSelect={(path) => handleUpdate({ podcast_dir: path })}
                onClose={() => setShowDirPicker(false)}
              />
            </div>
          </div>

          <div className="flex items-center justify-end pt-8 border-t border-white/10 mt-8">
            <button
              onClick={handleNext}
              disabled={!formData.podcast_name}
              className="flex items-center gap-2 px-6 py-3 bg-white text-black font-semibold rounded-xl hover:bg-zinc-200 focus:ring-4 focus:ring-white/20 transition-all disabled:opacity-50"
            >
              Next <ArrowRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}

      {/* STEP 2: STRATEGIC PROFILING */}
      {step === 2 && (
        <div className="space-y-6 animate-in fade-in slide-in-from-right-4 duration-500">
          <div>
            <h1 className="text-3xl font-bold bg-gradient-to-r from-white to-zinc-400 bg-clip-text text-transparent">
              Let's get to know you
            </h1>
            <p className="text-zinc-400 mt-2 text-lg">
              This info tunes Azelia's recommendation algorithms to your
              specific niche.
            </p>
            <p className="text-zinc-500 mt-2 text-xs">
              The setup wizard stays in English. Azelia auto-detects the
              language of every episode from its transcript and writes titles,
              summaries and reasoning in that language — no need to pick one.
            </p>
          </div>

          <div className="space-y-6 mt-6">
            <div>
              <label className="flex items-center gap-2 text-sm font-medium text-zinc-300 mb-3">
                <User className="w-4 h-4 text-brand-400" /> What's your main
                role??
              </label>
              <div className="grid grid-cols-2 gap-3">
                {ROLES.map((r) => (
                  <button
                    key={r.id}
                    onClick={() => setProfile({ ...profile, user_role: r.id })}
                    className={`px-4 py-3 rounded-xl border text-left text-sm transition-all ${profile.user_role === r.id ? "bg-brand-500/20 border-brand-500 text-white" : "bg-black/20 border-white/5 hover:border-white/20 text-zinc-400"}`}
                  >
                    {r.label}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className="flex items-center gap-2 text-sm font-medium text-zinc-300 mb-3">
                <Target className="w-4 h-4 text-brand-400" /> What's your goal??
              </label>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                {GOALS.map((g) => (
                  <button
                    key={g.id}
                    onClick={() =>
                      setProfile({ ...profile, primary_goal: g.id })
                    }
                    className={`px-4 py-3 rounded-xl border text-center text-sm transition-all ${profile.primary_goal === g.id ? "bg-brand-500/20 border-brand-500 text-white" : "bg-black/20 border-white/5 hover:border-white/20 text-zinc-400"}`}
                  >
                    {g.label}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-zinc-300 mb-2 ml-1">
                Content niche
              </label>
              <SearchableCombobox
                items={niches}
                value={profile.content_niche}
                onChange={(id) => setProfile({ ...profile, content_niche: id })}
                placeholder={niches.length ? "Select a category…" : "Loading…"}
                disabled={!niches.length}
              />
              <p className="text-xs text-zinc-500 mt-1.5 ml-1">
                Drives how Azelia ranks clips for your audience.
              </p>
            </div>

            <div>
              <label className="block text-sm font-medium text-zinc-300 mb-2 ml-1">
                Country / region
              </label>
              <SearchableCombobox
                items={countries}
                value={profile.region}
                onChange={(id) => setProfile({ ...profile, region: id })}
                placeholder={
                  countries.length ? "Select a country…" : "Loading…"
                }
                disabled={!countries.length}
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-zinc-300 mb-3 ml-1">
                Episode Format
              </label>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                {FORMATS.map((f) => (
                  <button
                    key={f.id}
                    onClick={() =>
                      setProfile({ ...profile, episode_format: f.id })
                    }
                    className={`px-4 py-3 rounded-xl border text-center text-sm transition-all ${profile.episode_format === f.id ? "bg-brand-500/20 border-brand-500 text-white" : "bg-black/20 border-white/5 hover:border-white/20 text-zinc-400"}`}
                  >
                    {f.label}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div className="flex items-center justify-between pt-8 border-t border-white/10 mt-8">
            <button
              onClick={handlePrev}
              className="text-zinc-400 hover:text-white transition-colors text-sm font-medium flex items-center gap-2"
            >
              <ArrowLeft className="w-4 h-4" /> Back
            </button>
            <button
              onClick={handleNext}
              disabled={
                !profile.user_role ||
                !profile.primary_goal ||
                !profile.content_niche
              }
              className="flex items-center gap-2 px-6 py-3 bg-white text-black font-semibold rounded-xl hover:bg-zinc-200 focus:ring-4 focus:ring-white/20 transition-all disabled:opacity-50"
            >
              Next <ArrowRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}

      {/* STEP 3: SOCIAL & TELEMETRY */}
      {step === 3 && (
        <div className="space-y-6 animate-in fade-in slide-in-from-right-4 duration-500">
          <div>
            <h1 className="text-3xl font-bold bg-gradient-to-r from-white to-zinc-400 bg-clip-text text-transparent">
              Connect YouTube{" "}
              <span className="text-zinc-500 text-base font-normal">
                — optional
              </span>
            </h1>
            <p className="text-zinc-400 mt-2 text-lg">
              Azelia analyzes your past Shorts (entirely local — uses your
              Claude Code or Anthropic key) and biases the curation agents
              toward what already works for
              <em> your</em> audience. You can do this later from Settings →
              Integrations.
            </p>
          </div>

          <div className="bg-amber-950/30 border border-amber-500/30 rounded-xl p-3 flex gap-2.5 items-start">
            <Shield className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
            <p className="text-xs text-amber-200/90 leading-relaxed">
              Azelia is in alpha and the Google OAuth app isn't verified yet.
              When you connect, Google will warn you to{" "}
              <em>"go back to safety"</em> — click{" "}
              <strong>Advanced → Continue</strong> to proceed. Your tokens stay
              on your machine.
            </p>
          </div>

          <div className="space-y-6 mt-6">
            {/* Social Connections */}
            <div className="pt-4">
              <h4 className="text-sm font-medium text-zinc-300 mb-3 flex items-center gap-2">
                <LinkIcon className="w-4 h-4" /> Conexiones Sociales
              </h4>
              <div className="space-y-3">
                {/* YouTube Button */}
                {ytConnected ? (
                  <div className="p-4 rounded-xl bg-green-500/10 border border-green-500/30 flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <CheckCircle2 className="w-6 h-6 text-green-500" />
                      <div>
                        <div className="text-white font-medium text-sm">
                          YouTube Connected
                        </div>
                        <div className="text-green-400 text-xs mt-0.5">
                          {ytChannelName}
                        </div>
                      </div>
                    </div>
                    <div className="px-3 py-1.5 bg-zinc-800/40 border border-white/10 text-zinc-500 text-[11px] rounded-lg leading-tight max-w-[180px]">
                      Historical sync runs from the dashboard once setup is
                      done.
                    </div>
                  </div>
                ) : ytShowPicker ? (
                  <div className="p-4 rounded-xl bg-black/20 border border-red-500/20 space-y-3">
                    <h4 className="text-white font-medium text-sm flex items-center gap-2">
                      <Youtube className="w-5 h-5 text-red-500" /> Select Your
                      Channel
                    </h4>
                    <div className="space-y-2 max-h-48 overflow-y-auto">
                      {ytChannels.map((ch: any) => (
                        <button
                          key={ch.id}
                          onClick={() => handleYtSelectChannel(ch.id)}
                          disabled={ytConnecting}
                          className="w-full flex items-center gap-3 p-3 rounded-lg bg-zinc-800/50 border border-white/5 hover:border-red-500/30 transition-all text-left disabled:opacity-50"
                        >
                          {ch.thumbnail && (
                            <img
                              src={ch.thumbnail}
                              alt=""
                              className="w-8 h-8 rounded-full"
                            />
                          )}
                          <div className="flex-1 min-w-0">
                            <div className="text-zinc-200 text-sm font-medium truncate">
                              {ch.title}
                            </div>
                            <div className="text-zinc-500 text-xs">
                              {ch.handle ? `@${ch.handle}` : ""} ·{" "}
                              {ch.subscriber_count || 0} subs
                            </div>
                          </div>
                        </button>
                      ))}
                    </div>
                    <div className="flex gap-2 pt-2 border-t border-white/5">
                      <input
                        type="text"
                        value={ytManualHandle}
                        onChange={(e) => setYtManualHandle(e.target.value)}
                        placeholder="@channelhandle"
                        className="flex-1 bg-black/40 border border-white/10 rounded-lg px-3 py-2 text-sm text-zinc-200 placeholder-zinc-600 focus:outline-none focus:border-red-500/50"
                      />
                      <button
                        onClick={handleYtManualHandle}
                        disabled={ytConnecting || !ytManualHandle.trim()}
                        className="px-4 py-2 bg-red-600 text-white text-sm font-medium rounded-lg hover:bg-red-500 disabled:opacity-50 transition-all"
                      >
                        Sync
                      </button>
                    </div>
                  </div>
                ) : (
                  <button
                    onClick={handleYouTubeConnect}
                    disabled={ytConnecting}
                    className="w-full flex items-center gap-3 p-4 rounded-xl bg-black/20 border border-white/5 hover:bg-black/40 hover:border-red-500/30 transition-all text-left cursor-pointer disabled:opacity-50"
                  >
                    {ytConnecting ? (
                      <Loader2 className="w-6 h-6 text-red-500 animate-spin" />
                    ) : (
                      <Youtube className="w-6 h-6 text-red-500" />
                    )}
                    <div className="flex-1">
                      <div className="text-zinc-200 font-medium text-sm">
                        YouTube Channel
                      </div>
                      <div className="text-zinc-500 text-xs mt-0.5">
                        Connect to unlock Personal Intelligence
                      </div>
                    </div>
                    <span className="text-[10px] uppercase tracking-wider text-brand-400 font-bold bg-brand-500/10 px-2 py-1 rounded-md">
                      Recommended
                    </span>
                  </button>
                )}
              </div>
            </div>
          </div>

          <div className="flex items-center justify-between pt-8 border-t border-white/10 mt-8">
            <button
              onClick={handlePrev}
              className="text-zinc-400 hover:text-white transition-colors text-sm font-medium flex items-center gap-2"
            >
              <ArrowLeft className="w-4 h-4" /> Back
            </button>
            <div className="flex items-center gap-3">
              <button
                onClick={handleNext}
                className="text-zinc-400 hover:text-zinc-200 transition-colors text-sm font-medium px-4 py-2 rounded-lg hover:bg-white/5"
              >
                Skip for now
              </button>
              <button
                onClick={handleNext}
                className="flex items-center gap-2 px-6 py-3 bg-white text-black font-semibold rounded-xl hover:bg-zinc-200 focus:ring-4 focus:ring-white/20 transition-all"
              >
                {ytConnected ? "Continue" : "Next"}{" "}
                <ArrowRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        </div>
      )}

      {/* STEP 4: AI ENGINES */}
      {step === 4 && (
        <div className="space-y-6 animate-in fade-in slide-in-from-right-4 duration-500">
          <div>
            <h1 className="text-3xl font-bold bg-gradient-to-r from-white to-zinc-400 bg-clip-text text-transparent">
              Connect an LLM
            </h1>
            <p className="text-zinc-400 mt-2">
              Azelia uses your own LLM. Either Claude Code (your local
              subscription) or an Anthropic API key.
            </p>
          </div>

          {/* Claude Code auto-detection — preferred path when installed */}
          {claudeCode?.active ? (
            <div className="bg-emerald-950/30 border border-emerald-500/30 rounded-2xl p-5">
              <div className="flex items-start gap-4">
                <div className="w-10 h-10 rounded-xl bg-emerald-500/20 border border-emerald-500/30 flex items-center justify-center shrink-0">
                  <CheckCircle2 className="w-6 h-6 text-emerald-400" />
                </div>
                <div className="flex-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <h3 className="text-white font-semibold">
                      Claude Code detected
                    </h3>
                    <span className="text-[10px] uppercase tracking-wider text-emerald-400 font-bold bg-emerald-500/10 px-2 py-1 rounded-md">
                      Recommended · $0
                    </span>
                  </div>
                  <p className="text-sm text-emerald-200/80 mt-1.5 leading-relaxed">
                    We'll route Azelia's LLM calls through your local Claude
                    Code ({claudeCode.method || "subscription"}). No API key
                    needed, no extra cost beyond your existing Claude plan. You
                    can still add an Anthropic API key below as a backup.
                  </p>
                </div>
              </div>
            </div>
          ) : (
            <div className="bg-zinc-900/50 border border-white/10 rounded-2xl p-5">
              <p className="text-sm text-zinc-400 leading-relaxed">
                <strong className="text-zinc-200">
                  Claude Code not detected
                </strong>{" "}
                on this machine. Install it from{" "}
                <a
                  href="https://claude.com/download"
                  target="_blank"
                  rel="noreferrer"
                  className="text-brand-400 underline"
                >
                  claude.com/download
                </a>{" "}
                (uses your Claude.ai plan, $0 per clip) — or paste an Anthropic
                API key below.
              </p>
            </div>
          )}

          {/* Provider Cascade — primary + optional extras */}
          <div className="space-y-4 mt-6">
            {[primaryProvider, ...extraProviders].map((selectedId, slotIdx) => {
              const isExtra = slotIdx > 0;
              const usedIds = [primaryProvider, ...extraProviders];
              const availableForSlot = providerOrder.filter(
                (id) => !usedIds.includes(id) || id === selectedId,
              );

              return (
                <div
                  key={slotIdx}
                  className="bg-black/30 border border-white/10 rounded-2xl overflow-hidden"
                >
                  {/* Header row */}
                  <div className="px-5 pt-4 pb-3 flex items-center gap-3">
                    <div className="flex-1">
                      <label className="text-xs font-semibold text-zinc-500 uppercase tracking-wider">
                        {isExtra
                          ? `Proveedor de respaldo ${slotIdx}`
                          : "Primary provider"}
                      </label>
                      <select
                        value={selectedId}
                        onChange={(e) => {
                          if (slotIdx === 0) setPrimaryProvider(e.target.value);
                          else
                            setExtraProviders((prev) =>
                              prev.map((id, i) =>
                                i === slotIdx - 1 ? e.target.value : id,
                              ),
                            );
                        }}
                        className="mt-1 w-full bg-zinc-900 border border-white/15 rounded-xl px-3 py-2.5 text-white text-sm focus:border-brand-500 outline-none appearance-none"
                      >
                        <option value="">Selecciona un proveedor...</option>
                        {providerOrder
                          .filter(
                            (id) => !usedIds.includes(id) || id === selectedId,
                          )
                          .map((id) => (
                            <option key={id} value={id} className="bg-zinc-900">
                              {PROVIDERS[id].name}
                            </option>
                          ))}
                      </select>
                    </div>
                    {isExtra && (
                      <button
                        type="button"
                        onClick={() =>
                          setExtraProviders((prev) =>
                            prev.filter((_, i) => i !== slotIdx - 1),
                          )
                        }
                        className="mt-5 p-1.5 text-zinc-600 hover:text-red-400 transition-colors"
                        title="Quitar"
                      >
                        <span className="text-lg leading-none">×</span>
                      </button>
                    )}
                  </div>

                  {/* Key input — only when provider selected */}
                  {selectedId &&
                    (() => {
                      const cfg = PROVIDERS[selectedId];
                      // @ts-ignore
                      const rawVal: string = formData[cfg.field] || "";
                      // Never show masked server values (e.g. "sk-ant-***...") in the input
                      const isMasked =
                        rawVal.includes("*") || rawVal.includes("...");
                      const currentVal = isMasked ? "" : rawVal;
                      const detected = detectedModels[selectedId];
                      const detectionError = detectionErrors[selectedId];
                      const isDetecting = detectingProvider === selectedId;
                      const hasKey = currentVal.trim().length >= 12;
                      return (
                        <div className="px-5 pb-4 space-y-2 border-t border-white/5 pt-3">
                          <div className="flex items-center justify-between">
                            <label className="text-xs text-zinc-500">
                              {selectedId === "vertex"
                                ? "GCP Project ID"
                                : "API Key"}
                            </label>
                            <a
                              href={cfg.keyUrl}
                              target="_blank"
                              rel="noreferrer"
                              className="text-[10px] text-zinc-600 hover:text-zinc-400 underline"
                            >
                              Obtener key →
                            </a>
                          </div>
                          <div className="relative">
                            <Key className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-zinc-600" />
                            <input
                              type="password"
                              value={currentVal}
                              placeholder={cfg.ph}
                              onChange={(e) => {
                                const val = e.target.value;
                                // Bubble up priority order: primary provider goes first
                                const ordered = [
                                  selectedId,
                                  ...providerOrder.filter(
                                    (id) => id !== selectedId,
                                  ),
                                ];
                                handleUpdate({
                                  [cfg.field]: val,
                                  ai_provider_order: ordered,
                                } as Partial<UpdateSettingsRequest>);
                                detectModelForProvider(selectedId, val);
                              }}
                              className="w-full bg-black/50 border border-white/10 rounded-xl pl-9 pr-4 py-2.5 text-sm text-zinc-200 placeholder-zinc-700 focus:outline-none focus:border-brand-500 font-mono transition-all"
                            />
                          </div>
                          {/* Model detection feedback */}
                          {hasKey && (
                            <div className="flex items-center gap-1.5 text-xs">
                              {isDetecting ? (
                                <>
                                  <Loader2 className="w-3 h-3 text-brand-400 animate-spin" />
                                  <span className="text-zinc-500">
                                    Verificando key...
                                  </span>
                                </>
                              ) : detected ? (
                                <>
                                  <CheckCircle2 className="w-3 h-3 text-green-400" />
                                  <span className="text-zinc-400">
                                    Modelo:{" "}
                                    <code className="text-green-400 font-mono">
                                      {detected}
                                    </code>
                                  </span>
                                </>
                              ) : detectionError ? (
                                <span className="text-red-400">
                                  {detectionError}
                                </span>
                              ) : (
                                <span className="text-zinc-600">
                                  Verificando...
                                </span>
                              )}
                            </div>
                          )}
                        </div>
                      );
                    })()}
                </div>
              );
            })}

            {/* Add backup provider */}
            {primaryProvider &&
              extraProviders.length < 2 &&
              providerOrder.filter(
                (id) => id !== primaryProvider && !extraProviders.includes(id),
              ).length > 0 && (
                <button
                  type="button"
                  onClick={() => {
                    const next = providerOrder.find(
                      (id) =>
                        id !== primaryProvider && !extraProviders.includes(id),
                    );
                    if (next) setExtraProviders((prev) => [...prev, next]);
                  }}
                  className="w-full py-2.5 border border-dashed border-white/15 rounded-xl text-xs text-zinc-500 hover:text-zinc-300 hover:border-white/30 transition-all"
                >
                  + Agregar proveedor de respaldo
                </button>
              )}
            <p className="text-xs text-zinc-600 text-center">
              The model is detected automatically when your key is verified.
              Change it in <span className="text-zinc-500">Settings → AI</span>.
            </p>
          </div>

          <div className="flex flex-col gap-4 pt-6 border-t border-white/10 mt-6">
            <div className="flex items-center justify-between">
              <button
                onClick={handlePrev}
                className="text-zinc-400 hover:text-white transition-colors text-sm font-medium flex items-center gap-2"
              >
                <ArrowLeft className="w-4 h-4" /> Back
              </button>
              <div className="flex flex-col items-end gap-1">
                <button
                  onClick={handleFinish}
                  disabled={!hasAnyKey || saving}
                  className="flex items-center gap-2 px-6 py-3 bg-gradient-to-r from-brand-600 to-brand-500 text-white font-semibold rounded-xl hover:from-brand-500 focus:ring-4 focus:ring-brand-500/30 transition-all disabled:opacity-50 disabled:cursor-not-allowed shadow-lg shadow-brand-500/20"
                >
                  {saving ? (
                    <Loader2 className="w-5 h-5 animate-spin" />
                  ) : (
                    <Sparkles className="w-5 h-5" />
                  )}{" "}
                  Finish setup
                </button>
                {!hasAnyKey && (
                  <span className="text-xs text-red-400/80 mr-1">
                    Connect Claude Code or paste an Anthropic API key
                  </span>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      <RetroactiveSyncModal
        isOpen={showRetroactiveModal}
        onClose={() => setShowRetroactiveModal(false)}
        onSuccess={() => {
          setHasSyncedHistorical(true);
          setShowRetroactiveModal(false);
        }}
      />
    </div>
  );
};
