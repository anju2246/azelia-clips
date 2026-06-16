import React, { useEffect, useState } from "react";
import { ChevronDown, Check } from "lucide-react";
import { ProfilesApi, type ProfilesList } from "../../lib/api";

/**
 * Compact profile switcher for the dashboard header. Activating a profile
 * restarts the server (the backend trips the .restart sentinel), so we show a
 * "Reiniciando…" state and reload once the new process is back up.
 */
export const ProfileSwitcher: React.FC = () => {
  const [data, setData] = useState<ProfilesList | null>(null);
  const [open, setOpen] = useState(false);
  const [switching, setSwitching] = useState(false);

  useEffect(() => {
    ProfilesApi.list()
      .then(setData)
      .catch((e) => console.error("ProfileSwitcher: failed to load profiles", e));
  }, []);

  const active = data?.profiles.find((p) => p.active);

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
      }
    } catch (e) {
      setSwitching(false);
      console.error("ProfileSwitcher: activate failed", e);
      alert((e as Error).message);
    }
  };

  if (!data || data.profiles.length === 0) return null;

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        disabled={switching}
        className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm text-zinc-200 hover:bg-white/5 border border-zinc-800/50 transition-colors disabled:opacity-60"
      >
        <span className="font-medium max-w-[140px] truncate">
          {switching ? "Reiniciando…" : active?.name ?? "Perfil"}
        </span>
        <ChevronDown className="h-4 w-4 text-zinc-500" />
      </button>

      {open && (
        <div className="absolute right-0 mt-2 w-60 rounded-xl bg-zinc-900 border border-zinc-800 shadow-xl z-40 py-1">
          <p className="px-3 py-1.5 text-xs uppercase tracking-wide text-zinc-500">
            Podcasts
          </p>
          {data.profiles.map((p) => (
            <button
              key={p.id}
              onClick={() => activate(p.id)}
              className="w-full flex items-center justify-between px-3 py-2 text-sm text-zinc-200 hover:bg-white/5"
            >
              <span className="truncate">{p.name}</span>
              {p.active && <Check className="h-4 w-4 text-brand-500 shrink-0" />}
            </button>
          ))}
          <a
            href="/dashboard/settings"
            className="block px-3 py-2 text-xs text-zinc-500 hover:text-zinc-300 border-t border-zinc-800 mt-1"
          >
            Gestionar perfiles…
          </a>
        </div>
      )}
    </div>
  );
};
