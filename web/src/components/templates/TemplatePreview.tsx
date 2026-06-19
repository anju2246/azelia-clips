import React, { useRef, useState } from "react";
import type { SubtitleSpec, LayoutSpec } from "../../lib/api";
import { pointToAlignment, ratioFromDivider } from "./snap";
import { assToCss } from "./colors";

const TARGET_W = 1080;
const TARGET_H = 1920;

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
export const TemplatePreview: React.FC<Props> = ({
  subtitles,
  layout,
  editable,
  onChange,
}) => {
  const frameRef = useRef<HTMLDivElement>(null);
  const [dragging, setDragging] = useState<null | "subs" | "divider">(null);
  const [livePos, setLivePos] = useState<null | { xPct: number; yPct: number }>(
    null,
  );

  const isSplit = layout.type === "split";
  // Divider Y as a % from the top: wide shot occupies the bottom region.
  const dividerPct = (1 - layout.wide_height_ratio) * 100;

  // ── subtitle CSS position from alignment + margin_v ──────────────────────
  const a = subtitles.alignment;
  const col = a % 3 === 1 ? "left" : a % 3 === 2 ? "center" : "right";
  const rowBottom = a <= 3;
  const rowTop = a >= 7;
  const marginPct = (subtitles.margin_v / TARGET_H) * 100;

  const subsStyle: React.CSSProperties = livePos
    ? {
        left: `${livePos.xPct}%`,
        top: `${livePos.yPct}%`,
        transform: "translate(-50%, -50%)",
      }
    : {
        left: col === "left" ? "6%" : col === "right" ? "94%" : "50%",
        ...(rowBottom
          ? { bottom: `${marginPct}%` }
          : rowTop
            ? { top: `${marginPct}%` }
            : { top: "50%" }),
        transform:
          col === "left"
            ? "translateX(0)"
            : col === "right"
              ? "translateX(-100%)"
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
      const placement = pointToAlignment(tx, ty, {
        width: TARGET_W,
        height: TARGET_H,
      });
      onChange({ subtitles: placement });
    } else if (dragging === "divider") {
      onChange({ layout: { wide_height_ratio: ratioFromDivider(ty, TARGET_H) } });
    }
    setDragging(null);
    setLivePos(null);
  };

  return (
    <div
      ref={frameRef}
      onPointerMove={onPointerMove}
      onPointerUp={endDrag}
      onPointerLeave={endDrag}
      className="relative mx-auto overflow-hidden rounded-xl border border-zinc-700 bg-zinc-950 select-none"
      style={{ aspectRatio: "9 / 16", width: 270, touchAction: "none" }}
    >
      {/* Layout regions */}
      {isSplit ? (
        <>
          <div
            className="absolute inset-x-0 top-0 flex items-center justify-center bg-zinc-800/60 text-[10px] text-zinc-500"
            style={{ height: `${dividerPct}%` }}
          >
            close-up
          </div>
          <div
            className="absolute inset-x-0 bottom-0 flex items-center justify-center bg-zinc-700/40 text-[10px] text-zinc-500"
            style={{ height: `${100 - dividerPct}%` }}
          >
            wide
          </div>
          {/* Draggable divider */}
          <div
            onPointerDown={() => editable && setDragging("divider")}
            className={`absolute inset-x-0 h-2 -translate-y-1/2 ${
              editable ? "cursor-ns-resize" : ""
            }`}
            style={{ top: `${dividerPct}%` }}
          >
            <div className="mx-auto h-0.5 w-full bg-cyan-400/70" />
          </div>
        </>
      ) : (
        <div className="absolute inset-0 flex items-center justify-center bg-zinc-800/50 text-[10px] text-zinc-500">
          full-screen
        </div>
      )}

      {/* Subtitle block */}
      <div
        onPointerDown={() => editable && setDragging("subs")}
        className={`absolute whitespace-nowrap px-1 ${
          editable ? "cursor-grab active:cursor-grabbing" : ""
        }`}
        style={{
          ...subsStyle,
          fontFamily: `"${subtitles.font_name}", sans-serif`,
          fontSize: `${(subtitles.font_size / TARGET_H) * 100 * 4.8}px`,
          fontWeight: subtitles.bold ? 800 : 500,
          color: assToCss(subtitles.primary_color),
          WebkitTextStroke: `${Math.max(0.5, subtitles.outline / 4)}px ${assToCss(
            subtitles.outline_color,
          )}`,
        }}
      >
        Tu <span style={{ color: assToCss(subtitles.secondary_color) }}>texto</span>
      </div>
    </div>
  );
};
