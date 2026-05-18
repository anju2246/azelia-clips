import React, { useState } from "react";
import { Loader2 } from "lucide-react";
import type { ChannelOption } from "../../../lib/youtubeApi";

interface ChannelPickerProps {
  channels: ChannelOption[];
  isSyncing: boolean;
  onPickChannel: (channelId: string) => void;
  onPickByHandle: (handle: string) => void;
}

/**
 * UI shown right after OAuth when the user owns multiple YouTube channels.
 * Lets them pick one from the list, or type a handle (e.g. "@inminentepodcast")
 * to look up a channel that didn't show up in the picker.
 */
export const ChannelPicker: React.FC<ChannelPickerProps> = ({
  channels,
  isSyncing,
  onPickChannel,
  onPickByHandle,
}) => {
  const [manualHandle, setManualHandle] = useState("");

  const submitHandle = () => {
    if (!manualHandle.trim()) return;
    onPickByHandle(manualHandle);
  };

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
              onClick={() => onPickChannel(ch.id)}
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
                <p className="text-white font-semibold truncate">{ch.title}</p>
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
              onKeyDown={(e) => e.key === "Enter" && submitHandle()}
            />
            <button
              onClick={submitHandle}
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
};
