import React, { useEffect, useState } from "react";
import { Bell, User } from "lucide-react";
import { supabase } from "../../lib/supabase";

export const Header: React.FC = () => {
  const [displayName, setDisplayName] = useState("");
  const [avatarUrl, setAvatarUrl] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const {
          data: { user },
        } = await supabase.auth.getUser();
        if (user) {
          setDisplayName(
            user.user_metadata?.full_name ||
              user.user_metadata?.name ||
              user.email?.split("@")[0] ||
              "Creator",
          );
          setAvatarUrl(user.user_metadata?.avatar_url || null);
        }
      } catch (e) {
        // Silently ignore
      }
    })();
  }, []);

  return (
    <header className="h-16 border-b border-zinc-800/50 bg-black/40 backdrop-blur-xl sticky top-0 z-30 flex items-center justify-between px-6">
      {/* Header search removed in v0.1.0 — LibraryView has its own contextual
          search and a global search across the dashboard isn't useful yet. */}
      <div className="flex items-center gap-4 flex-1" />

      <div className="flex items-center gap-4">
        {/* Notifications */}
        <button className="p-2 rounded-full text-zinc-400 hover:text-zinc-100 hover:bg-white/5 transition-colors relative">
          <Bell className="h-5 w-5" />
          <span className="absolute top-1.5 right-1.5 h-2 w-2 rounded-full bg-brand-500 border border-black"></span>
        </button>

        {/* Local user indicator (no profile page in v0.1.0 — single-user local) */}
        <div className="flex items-center gap-3 pl-4 border-l border-zinc-800/50">
          <div className="text-right hidden md:block">
            <p className="text-sm font-medium text-zinc-200 leading-tight">
              {displayName || "Loading..."}
            </p>
            <p className="text-xs text-zinc-500">Local Environment</p>
          </div>
          {avatarUrl ? (
            <img
              src={avatarUrl}
              alt={displayName}
              className="h-8 w-8 rounded-full object-cover border border-zinc-700 hover:border-brand-500 transition-colors"
            />
          ) : (
            <div className="h-8 w-8 rounded-full bg-zinc-800 flex items-center justify-center border border-zinc-700 overflow-hidden hover:border-brand-500 transition-colors">
              {displayName ? (
                <span className="text-xs font-medium text-zinc-300">
                  {displayName.charAt(0).toUpperCase()}
                </span>
              ) : (
                <User className="h-4 w-4 text-zinc-400" />
              )}
            </div>
          )}
        </div>
      </div>
    </header>
  );
};
