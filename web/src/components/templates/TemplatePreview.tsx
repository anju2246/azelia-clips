import React, { useRef, useState } from "react";
import type { SubtitleSpec, LayoutSpec } from "../../lib/api";
import { pointToAlignment, ratioFromDivider } from "./snap";
import { assToCss } from "./colors";

const TARGET_W = 1080;
const TARGET_H = 1920;

const SAMPLE_WORDS = ["Y", "ESO", "LO", "CAMBIA", "TODO"];
const HIGHLIGHT_IDX = 4; // "TODO" rendered in the secondary color

interface Props {
  subtitles: SubtitleSpec;
  layout: LayoutSpec;
  editable: boolean;
  onChange: (patch: {
    subtitles?: Partial<SubtitleSpec>;
    layout?: Partial<LayoutSpec>;
  }) => void;
}

/**
 * Interactive WYSIWYG mockup. Approximates subtitles + layout in CSS (no FFmpeg).
 * Dragging the subtitle snaps to an ASS anchor + margin_v; dragging the split
 * divider adjusts wide_height_ratio. Everything stays in the 1080×1920 space.
 */
export const TemplatePreview: React.FC<Props> = ({ subtitles, layout, editable, onChange }) => {
  const frameRef = useRef<HTMLDivElement>(null);
  const [dragging, setDragging] = useState<null | "subs" | "divider">(null);
  const [livePos, setLivePos] = useState<null | { xPct: number; yPct: number }>(null);

  const isSplit = layout.type === "split";
  const dividerPct = (1 - layout.wide_height_ratio) * 100;
  const widePct = Math.round(layout.wide_height_ratio * 100);

  // ── subtitle CSS position from alignment + margin_v ──────────────────────
  const a = subtitles.alignment;
  const col = a % 3 === 1 ? "left" : a % 3 === 2 ? "center" : "right";
  const rowBottom = a <= 3;
  const rowTop = a >= 7;
  const marginPct = (subtitles.margin_v / TARGET_H) * 100;

  const subsStyle: React.CSSProperties = livePos
    ? { left: `${livePos.xPct}%`, top: `${livePos.yPct}%`, transform: "translate(-50%, -50%)" }
    : {
        left: col === "left" ? "6%" : col === "right" ? "94%" : "50%",
        ...(rowBottom ? { bottom: `${marginPct}%` } : rowTop ? { top: `${marginPct}%` } : { top: "50%" }),
        transform:
          col === "left"
            ? "translateX(0)"
            : col === "right"
              ? "translate(-100%, 0)"
              : "translateX(-50%)",
      };

  const relFromEvent = (e: React.PointerEvent) => {
    const rect = frameRef.current!.getBoundingClientRect();
    const xPx = Math.min(Math.max(e.clientX - rect.left, 0), rect.width);
    const yPx = Math.min(Math.max(e.clientY - rect.top, 0), rect.height);
    return { rect, xPx, yPx };
  };

  const onPointerMove = (e: React.PointerEvent) => {
    if (!dragging) return;
    const { rect, xPx, yPx } = relFromEvent(e);
    setLivePos({ xPct: (xPx / rect.width) * 100, yPct: (yPx / rect.height) * 100 });
  };

  const endDrag = (e: React.PointerEvent) => {
    if (!dragging) return;
    const { rect, xPx, yPx } = relFromEvent(e);
    const ty = (yPx / rect.height) * TARGET_H;
    if (dragging === "subs") {
      const tx = (xPx / rect.width) * TARGET_W;
      onChange({ subtitles: pointToAlignment(tx, ty, { width: TARGET_W, height: TARGET_H }) });
    } else if (dragging === "divider") {
      onChange({ layout: { wide_height_ratio: ratioFromDivider(ty, TARGET_H) } });
    }
    setDragging(null);
    setLivePos(null);
  };

  // Font size scaled into the preview's coordinate space.
  const fontPx = (subtitles.font_size / TARGET_H) * 100 * 4.8;
  const lineColor = assToCss(subtitles.primary_color);
  const hiColor = assToCss(subtitles.secondary_color);

  return (
    <div
      ref={frameRef}
      onPointerMove={onPointerMove}
      onPointerUp={endDrag}
      onPointerLeave={endDrag}
      className="relative mx-auto overflow-hidden rounded-2xl border border-slate-700/70 bg-gradient-to-b from-slate-800 to-slate-900 shadow-2xl select-none"
      style={{ aspectRatio: "9 / 16", width: 300, touchAction: "none" }}
    >
      {/* faux subject silhouette */}
      <div
        className="absolute left-1/2 -translate-x-1/2 rounded-full bg-amber-200/80"
        style={{ top: "22%", width: "42%", aspectRatio: "1" }}
      />
      <div
        className="absolute left-1/2 -translate-x-1/2 rounded-t-full bg-amber-950/40"
        style={{ top: "52%", width: "78%", height: "48%" }}
      />

      {/* anchor guide dots (3×3) */}
      {editable &&
        [25, 50, 75].map((y) =>
          [25, 50, 75].map((x) => (
            <span
              key={`${x}-${y}`}
              className="absolute h-1 w-1 -translate-x-1/2 -translate-y-1/2 rounded-full bg-white/20"
              style={{ left: `${x}%`, top: `${y}%` }}
            />
          )),
        )}

      {/* CLOSE-UP label */}
      {isSplit && (
        <div className="absolute left-2 top-2 flex items-center gap-1.5 rounded-md bg-black/60 px-2 py-1 text-[9px] font-bold tracking-wider text-white/90">
          <span className="h-1.5 w-1.5 rounded-full bg-red-500" /> CLOSE-UP
        </div>
      )}

      {/* split divider + WIDE label */}
      {isSplit && (
        <>
          <div
            onPointerDown={() => editable && setDragging("divider")}
            className={`absolute inset-x-0 z-10 flex h-4 -translate-y-1/2 items-center justify-center ${
              editable ? "cursor-ns-resize" : ""
            }`}
            style={{ top: `${dividerPct}%` }}
          >
            <div className="absolute inset-x-0 top-1/2 h-px bg-emerald-400/70" />
            <span className="relative rounded-full bg-emerald-500 px-2 py-0.5 text-[9px] font-bold text-white shadow">
              ↕ {widePct}%
            </span>
          </div>
          <div className="absolute bottom-1.5 left-2 text-[9px] font-bold tracking-wider text-white/60">
            WIDE
          </div>
        </>
      )}

      {/* subtitle block */}
      <div
        onPointerDown={() => editable && setDragging("subs")}
        className={`absolute z-20 flex flex-col items-center text-center leading-tight ${
          editable ? "cursor-grab active:cursor-grabbing" : ""
        }`}
        style={{
          ...subsStyle,
          fontFamily: `"${subtitles.font_name}", sans-serif`,
          fontSize: `${fontPx}px`,
          fontWeight: subtitles.bold ? 800 : 500,
          WebkitTextStroke: `${Math.max(0.4, subtitles.outline / 5)}px ${assToCss(subtitles.outline_color)}`,
          paintOrder: "stroke fill",
        }}
      >
        {[SAMPLE_WORDS.slice(0, subtitles.words_per_line), SAMPLE_WORDS.slice(subtitles.words_per_line)]
          .filter((l) => l.length)
          .map((line, li) => (
            <span key={li} className="whitespace-nowrap">
              {line.map((w, wi) => {
                const idx = li === 0 ? wi : subtitles.words_per_line + wi;
                return (
                  <span key={wi} style={{ color: idx === HIGHLIGHT_IDX ? hiColor : lineColor }}>
                    {w}{" "}
                  </span>
                );
              })}
            </span>
          ))}
      </div>
    </div>
  );
};
