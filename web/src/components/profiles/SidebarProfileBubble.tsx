import React, { useEffect, useState } from "react";
import { ProfilesApi, type ProfilesList } from "../../lib/api";

interface Props {
  currentPath?: string;
}

/**
 * Round profile button at the bottom of the icon sidebar. It's just a nav
 * button (like the other sidebar icons): shows the active podcast's initial and
 * navigates to the /dashboard/profiles page — no popover, no modal. All profile
 * management lives on that page, styled like the rest of the dashboard.
 */
export const SidebarProfileBubble: React.FC<Props> = ({ currentPath = "" }) => {
  const [data, setData] = useState<ProfilesList | null>(null);

  useEffect(() => {
    ProfilesApi.list()
      .then(setData)
      .catch((e) => console.error("SidebarProfileBubble: failed to load profiles", e));
  }, []);

  if (!data || data.profiles.length === 0) return null;

  const active = data.profiles.find((p) => p.active);
  const initial = (active?.name?.trim()?.[0] ?? "?").toUpperCase();
  const onProfiles = currentPath.startsWith("/dashboard/profiles");

  return (
    <a
      href="/dashboard/profiles"
      title={active ? `Podcast: ${active.name}` : "Podcasts"}
      className={`group relative w-11 h-11 flex items-center justify-center rounded-full border transition-all
        ${
          onProfiles
            ? "border-brand-500 ring-2 ring-brand-500/40"
            : "border-white/10 hover:border-brand-500/60 hover:scale-105"
        }
        bg-gradient-to-br from-brand-500/30 to-brand-600/30 text-white shadow-lg shadow-brand-500/10`}
    >
      <span className="text-sm font-bold">{initial}</span>
      <span className="absolute left-full ml-3 px-2.5 py-1 bg-zinc-800 text-white text-xs font-medium rounded-lg opacity-0 pointer-events-none group-hover:opacity-100 whitespace-nowrap transition-opacity shadow-xl border border-white/10 z-50">
        {active ? active.name : "Podcasts"}
      </span>
    </a>
  );
};
