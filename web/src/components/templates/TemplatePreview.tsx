import React, { useRef, useState } from "react";
import type { ClipTemplate, SubtitleSpec, LayoutSpec } from "../../lib/api";
import { pointToAlignment, ratioFromDivider } from "./snap";
import { assToCss } from "./colors";

const TARGET_W = 1080;
const TARGET_H = 1920;

interface Props {
  template: ClipTemplate;
  editable: boolean;
  onChange: (patch: {
    subtitles?: Partial<SubtitleSpec>;
    layout?: Partial<LayoutSpec>;
  }) => void;
}

/**
 * Faithful WYSIWYG mockup. Renders the ACTUAL template state — your own sample
 * text, the real layout, the hook title, the logo, and the progress bar — so a
 * change is always visible. Two views ("Captions" / "Inicio") let you preview
 * the hook-title moment vs the captions moment. CSS only (no FFmpeg).
 */
export const TemplatePreview: React.FC<Props> = ({ template, editable, onChange }) => {
  const subtitles = template.subtitles;
  const layout = template.layout;
  const intro = template.intro_title;
  const branding = template.branding;
  const pbar = template.progress_bar;

  const frameRef = useRef<HTMLDivElement>(null);
  const [dragging, setDragging] = useState<null | "subs" | "divider">(null);
  const [livePos, setLivePos] = useState<null | { xPct: number; yPct: number }>(null);
  const [sample, setSample] = useState("Y ESO LO CAMBIA TODO");
  const introOn = !!intro?.enabled;
  const [view, setView] = useState<"captions" | "hook">("captions");
  const showHook = introOn && view === "hook";

  const isSplit = layout.type === "split";
  const isRegions = layout.type === "regions";
  const dividerPct = (1 - layout.wide_height_ratio) * 100;
  const widePct = Math.round(layout.wide_height_ratio * 100);
  const regionLabel = (src: { mode: string; speaker_ref?: string | null }) =>
    src.mode === "wide" ? "PLANO ABIERTO" : src.mode === "speaker" ? src.speaker_ref || "INVITADO" : "ACTIVE";

  const words = sample.trim().split(/\s+/).filter(Boolean);
  const wpl = subtitles.words_per_line;
  const lines: string[][] = [];
  for (let i = 0; i < words.length; i += wpl) lines.push(words.slice(i, i + wpl));
  const highlightWord = words.length - 1; // last word shown in the accent color

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
          col === "left" ? "translateX(0)" : col === "right" ? "translate(-100%, 0)" : "translateX(-50%)",
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

  const fontPx = (subtitles.font_size / TARGET_H) * 100 * 4.8;
  const lineColor = assToCss(subtitles.primary_color);
  const hiColor = assToCss(subtitles.secondary_color);

  // ── hook title position ──────────────────────────────────────────────────
  const hookVAlign =
    intro?.position === "top" ? "flex-start" : intro?.position === "bottom" ? "flex-end" : "center";
  const hookFontPx = ((intro?.font_size ?? 72) / TARGET_H) * 100 * 4.8;

  // ── logo corner ──────────────────────────────────────────────────────────
  const logoCorner: React.CSSProperties = (() => {
    const m = `${((branding?.margin ?? 40) / TARGET_W) * 100}%`;
    const p = branding?.position ?? "top-right";
    return {
      top: p.startsWith("top") ? m : undefined,
      bottom: p.startsWith("bottom") ? m : undefined,
      left: p.endsWith("left") ? m : undefined,
      right: p.endsWith("right") ? m : undefined,
      width: `${(branding?.scale ?? 0.1) * 100}%`,
      opacity: branding?.opacity ?? 1,
    };
  })();

  return (
    <div className="flex flex-col items-center gap-3">
      {introOn && (
        <div className="flex items-center gap-1 rounded-lg bg-slate-800/70 p-1 text-xs">
          {(["hook", "captions"] as const).map((v) => (
            <button
              key={v}
              onClick={() => setView(v)}
              className={`rounded-md px-3 py-1 font-medium transition ${
                view === v ? "bg-emerald-500 text-white" : "text-slate-300 hover:bg-slate-700/60"
              }`}
            >
              {v === "hook" ? `Inicio (0–${(intro?.duration_s ?? 4).toFixed(0)}s)` : "Captions"}
            </button>
          ))}
        </div>
      )}

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

        {/* anchor guide dots (3×3) when editing the caption position */}
        {editable &&
          !showHook &&
          [25, 50, 75].map((y) =>
            [25, 50, 75].map((x) => (
              <span
                key={`${x}-${y}`}
                className="absolute h-1 w-1 -translate-x-1/2 -translate-y-1/2 rounded-full bg-white/20"
                style={{ left: `${x}%`, top: `${y}%` }}
              />
            )),
          )}

        {isSplit && (
          <div className="absolute left-2 top-2 flex items-center gap-1.5 rounded-md bg-black/60 px-2 py-1 text-[9px] font-bold tracking-wider text-white/90">
            <span className="h-1.5 w-1.5 rounded-full bg-red-500" /> CLOSE-UP
          </div>
        )}

        {/* region layout (2-guest stacked, grid, …) */}
        {isRegions &&
          (layout.regions ?? []).map((r, i) => (
            <div
              key={i}
              className="absolute z-10 flex items-end justify-start border border-dashed border-emerald-400/40 bg-emerald-400/5"
              style={{
                left: `${r.x * 100}%`,
                top: `${r.y * 100}%`,
                width: `${r.w * 100}%`,
                height: `${r.h * 100}%`,
              }}
            >
              <span className="m-1 rounded bg-black/60 px-1.5 py-0.5 text-[8px] font-bold tracking-wider text-white/90">
                {regionLabel(r.source)}
              </span>
            </div>
          ))}

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

        {/* progress bar */}
        {pbar?.enabled && (
          <div
            className="absolute inset-x-0 z-30 bg-black/30"
            style={{
              height: Math.max(2, (pbar.height / TARGET_H) * 100 * 4),
              top: pbar.position === "top" ? 0 : undefined,
              bottom: pbar.position === "bottom" ? 0 : undefined,
            }}
          >
            <div className="h-full" style={{ width: "60%", background: assToCss(pbar.color) }} />
          </div>
        )}

        {/* logo placeholder */}
        {branding?.logo_path && (
          <div
            className="absolute z-30 flex items-center justify-center rounded border border-white/40 bg-white/10 text-[7px] font-bold tracking-wider text-white/80"
            style={{ ...logoCorner, aspectRatio: "2 / 1" }}
          >
            LOGO
          </div>
        )}

        {/* HOOK view: the title card shown during the first seconds */}
        {showHook ? (
          <div
            className="absolute inset-0 z-20 flex px-4"
            style={{ alignItems: hookVAlign, paddingTop: "8%", paddingBottom: "8%" }}
          >
            <div
              className="w-full text-center font-extrabold leading-tight text-white"
              style={{
                fontFamily: `"${intro?.font_name || subtitles.font_name}", sans-serif`,
                fontSize: `${hookFontPx}px`,
                color: assToCss(intro?.color ?? "&H00FFFFFF"),
                background: intro?.box ? "rgba(0,0,0,0.55)" : "transparent",
                borderRadius: intro?.box ? 8 : 0,
                padding: intro?.box ? "6px 8px" : 0,
                WebkitTextStroke: `0.5px ${assToCss(intro?.outline_color ?? "&H00000000")}`,
                paintOrder: "stroke fill",
              }}
            >
              {template.name?.toUpperCase() || "TÍTULO DEL CLIP"}
            </div>
          </div>
        ) : (
          /* CAPTIONS view: the subtitle block */
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
            {lines.map((line, li) => (
              <span key={li} className="whitespace-nowrap">
                {line.map((w, wi) => {
                  const idx = li * wpl + wi;
                  return (
                    <span key={wi} style={{ color: idx === highlightWord ? hiColor : lineColor }}>
                      {w}{" "}
                    </span>
                  );
                })}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* editable sample text — so the preview reflects YOUR words */}
      {!showHook && (
        <input
          value={sample}
          onChange={(e) => setSample(e.target.value)}
          placeholder="Texto de ejemplo…"
          className="w-[300px] rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-center text-xs text-slate-300 placeholder:text-slate-600 focus:border-emerald-500 focus:outline-none"
        />
      )}
    </div>
  );
};
