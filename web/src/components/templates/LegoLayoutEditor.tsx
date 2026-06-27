import React, { useRef, useState } from "react";
import { Mic, User, Image as ImageIcon, Trash2, Plus } from "lucide-react";
import type { Region } from "../../lib/api";
import {
  regionsToBlocks,
  blocksToRegions,
  addBlock,
  removeBlock,
  resizeBoundary,
  type BlockMode,
  type LegoBlock,
} from "./legoSnap";

interface Props {
  regions: Region[];
  editable: boolean;
  onChange: (regions: Region[]) => void;
}

const BLOCKS: { mode: BlockMode; label: string; icon: React.ElementType }[] = [
  { mode: "active_speaker", label: "Quien habla", icon: Mic },
  { mode: "speaker", label: "Persona fija", icon: User },
  { mode: "wide", label: "Plano abierto", icon: ImageIcon },
];

const meta = (mode: BlockMode) => BLOCKS.find((b) => b.mode === mode)!;

/**
 * Lego layout builder. Video blocks stack vertically (full width — the natural
 * 9:16 composition); drag the boundary between two blocks to resize, with snap
 * to nice fractions. Add blocks from the palette, name "Persona fija" blocks.
 * Emits a regions list the render composites.
 */
export const LegoLayoutEditor: React.FC<Props> = ({ regions, editable, onChange }) => {
  const blocks = regionsToBlocks(regions);
  const stackRef = useRef<HTMLDivElement>(null);
  const [dragIdx, setDragIdx] = useState<number | null>(null);

  const emit = (next: LegoBlock[]) => onChange(blocksToRegions(next));

  const onBoundaryMove = (e: React.PointerEvent) => {
    if (dragIdx === null || !stackRef.current) return;
    const rect = stackRef.current.getBoundingClientRect();
    const frac = Math.min(Math.max((e.clientY - rect.top) / rect.height, 0), 1);
    emit(resizeBoundary(blocks, dragIdx, frac));
  };

  const setMode = (i: number, mode: BlockMode) =>
    emit(
      blocks.map((b, j) =>
        j === i ? { ...b, mode, speaker_ref: mode === "speaker" ? b.speaker_ref ?? "Invitado" : undefined } : b,
      ),
    );
  const setName = (i: number, name: string) =>
    emit(blocks.map((b, j) => (j === i ? { ...b, speaker_ref: name } : b)));

  return (
    <div className="flex gap-3">
      {/* the stack canvas (mini 9:16) */}
      <div
        ref={stackRef}
        onPointerMove={onBoundaryMove}
        onPointerUp={() => setDragIdx(null)}
        onPointerLeave={() => setDragIdx(null)}
        className="relative w-[90px] shrink-0 overflow-hidden rounded-lg border border-slate-700 bg-slate-900 select-none"
        style={{ aspectRatio: "9 / 16", touchAction: "none" }}
      >
        {blocks.map((b, i) => {
          const Icon = meta(b.mode).icon;
          const top = blocks.slice(0, i).reduce((s, x) => s + x.h, 0);
          return (
            <React.Fragment key={i}>
              <div
                className="absolute inset-x-0 flex flex-col items-center justify-center gap-0.5 border-b border-slate-700/60 text-center text-emerald-300"
                style={{ top: `${top * 100}%`, height: `${b.h * 100}%` }}
              >
                <Icon size={14} />
                <span className="px-1 text-[7px] font-semibold leading-tight text-white/80">
                  {b.mode === "speaker" ? b.speaker_ref || "Persona" : meta(b.mode).label}
                </span>
              </div>
              {/* resize handle on the boundary below this block */}
              {editable && i < blocks.length - 1 && (
                <div
                  onPointerDown={() => setDragIdx(i)}
                  className="absolute inset-x-0 z-10 h-2 -translate-y-1/2 cursor-ns-resize"
                  style={{ top: `${(top + b.h) * 100}%` }}
                >
                  <div className="mx-auto mt-[3px] h-0.5 w-6 rounded-full bg-emerald-400/80" />
                </div>
              )}
            </React.Fragment>
          );
        })}
      </div>

      {/* controls per block + palette */}
      <div className="flex min-w-0 flex-1 flex-col gap-2">
        {blocks.map((b, i) => (
          <div key={i} className="flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-800/50 p-1.5">
            <select
              value={b.mode}
              disabled={!editable}
              onChange={(e) => setMode(i, e.target.value as BlockMode)}
              className="rounded-md border border-slate-700 bg-slate-900 px-1.5 py-1 text-xs disabled:opacity-50"
            >
              {BLOCKS.map((opt) => (
                <option key={opt.mode} value={opt.mode}>
                  {opt.label}
                </option>
              ))}
            </select>
            {b.mode === "speaker" && (
              <input
                value={b.speaker_ref ?? ""}
                disabled={!editable}
                onChange={(e) => setName(i, e.target.value)}
                placeholder="Nombre"
                className="min-w-0 flex-1 rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-xs disabled:opacity-50"
              />
            )}
            <span className="ml-auto text-[10px] tabular-nums text-slate-500">
              {Math.round(b.h * 100)}%
            </span>
            {editable && blocks.length > 1 && (
              <button
                onClick={() => emit(removeBlock(blocks, i))}
                className="rounded p-1 text-slate-400 hover:bg-slate-700 hover:text-red-300"
                title="Quitar bloque"
              >
                <Trash2 size={12} />
              </button>
            )}
          </div>
        ))}

        {editable && blocks.length < 4 && (
          <div className="mt-1 flex flex-wrap gap-1">
            {BLOCKS.map(({ mode, label, icon: Icon }) => (
              <button
                key={mode}
                onClick={() => emit(addBlock(blocks, mode))}
                className="inline-flex items-center gap-1 rounded-md border border-slate-700 px-2 py-1 text-[11px] text-slate-300 hover:border-emerald-500/60 hover:text-white"
              >
                <Plus size={11} /> <Icon size={11} /> {label}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
