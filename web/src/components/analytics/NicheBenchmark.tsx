import React, { useState } from "react";
import { ChevronDown, Info } from "lucide-react";

export const NicheBenchmark: React.FC = () => {
  const [open, setOpen] = useState(false);

  return (
    <div className="bg-zinc-900/20 border border-white/5 rounded-2xl overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-6 py-4 hover:bg-white/[0.02] transition-colors"
      >
        <div className="flex items-center gap-2">
          <Info className="w-4 h-4 text-zinc-500" />
          <span className="text-sm font-medium text-zinc-300">
            How I compare to my niche
          </span>
          <span className="text-[10px] text-zinc-600 font-mono uppercase tracking-widest">
            optional
          </span>
        </div>
        <ChevronDown
          className={`w-4 h-4 text-zinc-500 transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>
      {open && (
        <div className="px-6 pb-6 text-sm text-zinc-400 space-y-2 border-t border-white/5 pt-4">
          <p>
            This benchmark is anonymous: we compare your aggregated retention,
            hook diversity and clip volume against the median of podcasters in
            your same <em>cohort</em> — no individual channels are identified.
          </p>
          <p className="text-xs text-zinc-500">
            Not enough cohort data in your niche yet. Keep processing episodes
            and this section will light up once the sample is large enough to be
            meaningful.
          </p>
        </div>
      )}
    </div>
  );
};
