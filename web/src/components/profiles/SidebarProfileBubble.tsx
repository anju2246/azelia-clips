import React, { useEffect, useState } from "react";
import { Check, Settings2 } from "lucide-react";
import { ProfilesApi, type ProfilesList } from "../../lib/api";

/**
 * Round profile bubble pinned at the bottom of the icon sidebar. Shows the
 * active podcast's initial; clicking opens a popover (to the right, like the
 * notifications one) to switch profiles. Switching restarts the server, so we
 * show a pulsing state and reload once it's back.
 */
export const SidebarProfileBubble: React.FC = () => {
  const [data, setData] = useState<ProfilesList | null>(null);
  const [open, setOpen] = useState(false);
  const [switching, setSwitching] = useState(false);

  useEffect(() => {
    ProfilesApi.list()
      .then(setData)
      .catch((e) => console.error("SidebarProfileBubble: failed to load profiles", e));
  }, []);

  const active = data?.profiles.find((p) => p.active);
  const initial = (active?.name?.trim()?.[0] ?? "?").toUpperCase();

  const activate = async (id: string) => {
    setOpen(false);
    if (active?.id === id) return;
    setSwitching(true);
    try {
      const res = await ProfilesApi.activate(id);
      if (res.status === "restarting") {
        setTimeout(() => window.location.reload(), 4000);
      } else {
        setSwitching(false);
        ProfilesApi.list().then(setData).catch(() => {});
      }
    } catch (e) {
      setSwitching(false);
      console.error("SidebarProfileBubble: activate failed", e);
      alert((e as Error).message);
    }
  };

  if (!data || data.profiles.length === 0) return null;

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        disabled={switching}
        title={active ? `Podcast: ${active.name}` : "Perfil"}
        className={`group relative w-11 h-11 flex items-center justify-center rounded-full border transition-all
          ${switching ? "animate-pulse border-brand-500/60" : "border-white/10 hover:border-brand-500/60 hover:scale-105"}
          bg-gradient-to-br from-brand-500/30 to-brand-600/30 text-white shadow-lg shadow-brand-500/10`}
      >
        <span className="text-sm font-bold">{switching ? "…" : initial}</span>
        {/* Tooltip mirrors the nav icons' style */}
        <span className="absolute left-full ml-3 px-2.5 py-1 bg-zinc-800 text-white text-xs font-medium rounded-lg opacity-0 pointer-events-none group-hover:opacity-100 whitespace-nowrap transition-opacity shadow-xl border border-white/10 z-50">
          {active ? active.name : "Perfil"}
        </span>
      </button>

      {open && (
        <div className="absolute left-full ml-3 bottom-0 w-60 bg-zinc-900 border border-white/10 rounded-2xl shadow-2xl z-50 overflow-hidden py-1">
          <p className="px-3 py-2 text-[10px] uppercase tracking-wide text-zinc-500">
            Podcast activo
          </p>
          {data.profiles.map((p) => (
            <button
              key={p.id}
              onClick={() => activate(p.id)}
              className="w-full flex items-center justify-between px-3 py-2 text-sm text-zinc-200 hover:bg-white/5"
            >
              <span className="truncate">{p.name}</span>
              {p.active && <Check className="w-4 h-4 text-brand-500 shrink-0" />}
            </button>
          ))}
          <a
            href="/dashboard/settings"
            className="flex items-center gap-2 px-3 py-2 text-xs text-zinc-500 hover:text-zinc-300 border-t border-white/5 mt-1"
          >
            <Settings2 className="w-3.5 h-3.5" /> Gestionar perfiles…
          </a>
        </div>
      )}
    </div>
  );
};
