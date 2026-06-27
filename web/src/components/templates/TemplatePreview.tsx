import React, { useRef, useState, useEffect } from "react";
import { Minus, Plus, Trash2, Type as TypeIcon } from "lucide-react";
import {
  TemplatesApi,
  type ClipTemplate,
  type SubtitleSpec,
  type LayoutSpec,
  type BrandingSpec,
  type IntroTitleSpec,
} from "../../lib/api";
import { pointToAlignment, ratioFromDivider } from "./snap";
import { assToCss, assToHex, cssToAss } from "./colors";

const TARGET_W = 1080;
const TARGET_H = 1920;

interface Props {
  template: ClipTemplate;
  editable: boolean;
  onChange: (patch: {
    subtitles?: Partial<SubtitleSpec>;
    layout?: Partial<LayoutSpec>;
    branding?: Partial<BrandingSpec>;
    introTitle?: Partial<IntroTitleSpec>;
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
  const [dragging, setDragging] = useState<
    null | "subs" | "divider" | "logo" | "logo-resize" | "hook"
  >(null);
  const [livePos, setLivePos] = useState<null | { xPct: number; yPct: number }>(null);
  const [sample, setSample] = useState("Y ESO LO CAMBIA TODO");
  const [activeIdx, setActiveIdx] = useState(0); // live animation cursor
  const [selected, setSelected] = useState<null | "subs" | "logo" | "hook">(null);
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

  // Live animation: a cursor walks the words so highlight/karaoke/box/cumulative
  // actually move in the preview instead of a frozen frame.
  useEffect(() => {
    if (showHook || dragging || words.length === 0) return;
    const id = setInterval(() => setActiveIdx((i) => (i + 1) % words.length), 600);
    return () => clearInterval(id);
  }, [showHook, dragging, words.length, subtitles.animation]);
  const highlightWord = words.length ? activeIdx % words.length : -1;
  const anim = subtitles.animation;

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
    if (dragging === "logo-resize" && branding) {
      const side = (branding.position ?? "top-right").endsWith("left") ? "left" : "right";
      const marginFrac = (branding.margin ?? 40) / TARGET_W;
      const xFrac = xPx / rect.width;
      const w = side === "left" ? xFrac - marginFrac : 1 - marginFrac - xFrac;
      onChange({ branding: { scale: Math.min(0.3, Math.max(0.02, w)) } });
      return;
    }
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
    } else if (dragging === "logo") {
      const vert = yPx / rect.height < 0.5 ? "top" : "bottom";
      const side = xPx / rect.width < 0.5 ? "left" : "right";
      onChange({ branding: { position: `${vert}-${side}` as BrandingSpec["position"] } });
    } else if (dragging === "hook") {
      const f = yPx / rect.height;
      const position = f < 0.34 ? "top" : f > 0.66 ? "bottom" : "center";
      onChange({ introTitle: { position } });
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

      {/* contextual toolbar — appears for the selected element (on-canvas editing) */}
      {editable && (
        <div className="flex h-9 items-center gap-1.5 rounded-xl border border-slate-700 bg-slate-900/90 px-2 text-slate-200 shadow-lg">
          {selected === "subs" && (
            <>
              <TypeIcon size={14} className="text-slate-400" />
              <button
                onClick={() => onChange({ subtitles: { font_size: Math.max(12, subtitles.font_size - 2) } })}
                className="rounded p-1 hover:bg-slate-800"
              >
                <Minus size={13} />
              </button>
              <span className="w-7 text-center text-xs tabular-nums">{subtitles.font_size}</span>
              <button
                onClick={() => onChange({ subtitles: { font_size: Math.min(200, subtitles.font_size + 2) } })}
                className="rounded p-1 hover:bg-slate-800"
              >
                <Plus size={13} />
              </button>
              <div className="mx-1 h-5 w-px bg-slate-700" />
              <label
                className="relative h-6 w-6 cursor-pointer overflow-hidden rounded border border-slate-600"
                title="Color del texto"
                style={{ background: assToCss(subtitles.primary_color) }}
              >
                <input
                  type="color"
                  value={assToHex(subtitles.primary_color)}
                  onChange={(e) => onChange({ subtitles: { primary_color: cssToAss(e.target.value) } })}
                  className="absolute -inset-2 h-[200%] w-[200%] cursor-pointer opacity-0"
                />
              </label>
              <label
                className="relative h-6 w-6 cursor-pointer overflow-hidden rounded border border-slate-600"
                title="Color de resalte"
                style={{ background: assToCss(subtitles.secondary_color) }}
              >
                <input
                  type="color"
                  value={assToHex(subtitles.secondary_color)}
                  onChange={(e) => onChange({ subtitles: { secondary_color: cssToAss(e.target.value) } })}
                  className="absolute -inset-2 h-[200%] w-[200%] cursor-pointer opacity-0"
                />
              </label>
            </>
          )}
          {selected === "logo" && branding && (
            <>
              <span className="px-1 text-[10px] uppercase tracking-wide text-slate-400">Logo</span>
              <button
                onClick={() => onChange({ branding: { scale: Math.max(0.02, (branding.scale ?? 0.1) - 0.02) } })}
                className="rounded p-1 hover:bg-slate-800"
              >
                <Minus size={13} />
              </button>
              <span className="w-9 text-center text-xs tabular-nums">{Math.round((branding.scale ?? 0.1) * 100)}%</span>
              <button
                onClick={() => onChange({ branding: { scale: Math.min(0.3, (branding.scale ?? 0.1) + 0.02) } })}
                className="rounded p-1 hover:bg-slate-800"
              >
                <Plus size={13} />
              </button>
              <div className="mx-1 h-5 w-px bg-slate-700" />
              <span className="text-[10px] text-slate-400">opacidad</span>
              <button
                onClick={() => onChange({ branding: { opacity: Math.max(0, (branding.opacity ?? 1) - 0.1) } })}
                className="rounded p-1 hover:bg-slate-800"
              >
                <Minus size={13} />
              </button>
              <span className="w-9 text-center text-xs tabular-nums">{Math.round((branding.opacity ?? 1) * 100)}%</span>
              <button
                onClick={() => onChange({ branding: { opacity: Math.min(1, (branding.opacity ?? 1) + 0.1) } })}
                className="rounded p-1 hover:bg-slate-800"
              >
                <Plus size={13} />
              </button>
              <div className="mx-1 h-5 w-px bg-slate-700" />
              <button
                onClick={() => {
                  onChange({ branding: { logo_path: null } });
                  setSelected(null);
                }}
                className="rounded p-1 text-red-300 hover:bg-slate-800"
                title="Quitar logo"
              >
                <Trash2 size={13} />
              </button>
            </>
          )}
          {selected === "hook" && intro && (
            <>
              <span className="px-1 text-[10px] uppercase tracking-wide text-slate-400">Hook</span>
              <button
                onClick={() => onChange({ introTitle: { font_size: Math.max(12, (intro.font_size ?? 72) - 4) } })}
                className="rounded p-1 hover:bg-slate-800"
              >
                <Minus size={13} />
              </button>
              <span className="w-7 text-center text-xs tabular-nums">{intro.font_size ?? 72}</span>
              <button
                onClick={() => onChange({ introTitle: { font_size: Math.min(200, (intro.font_size ?? 72) + 4) } })}
                className="rounded p-1 hover:bg-slate-800"
              >
                <Plus size={13} />
              </button>
              <div className="mx-1 h-5 w-px bg-slate-700" />
              <label
                className="relative h-6 w-6 cursor-pointer overflow-hidden rounded border border-slate-600"
                title="Color del título"
                style={{ background: assToCss(intro.color ?? "&H00FFFFFF") }}
              >
                <input
                  type="color"
                  value={assToHex(intro.color ?? "&H00FFFFFF")}
                  onChange={(e) => onChange({ introTitle: { color: cssToAss(e.target.value) } })}
                  className="absolute -inset-2 h-[200%] w-[200%] cursor-pointer opacity-0"
                />
              </label>
            </>
          )}
          {!selected && (
            <span className="px-1 text-[11px] text-slate-500">
              Toca el subtítulo, el logo o el título para editarlo aquí · arrástralo para moverlo
            </span>
          )}
        </div>
      )}

      <div
        ref={frameRef}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerLeave={endDrag}
        onPointerDown={() => setSelected(null)}
        className="relative mx-auto overflow-hidden rounded-2xl border border-slate-700/70 bg-gradient-to-b from-slate-800 to-slate-900 shadow-2xl select-none"
        style={{ aspectRatio: "9 / 16", width: 300, touchAction: "none" }}
      >
        {/* faux subject silhouette (single-source layouts only) */}
        {!isRegions && (
          <>
            <div
              className="absolute left-1/2 -translate-x-1/2 rounded-full bg-amber-200/80"
              style={{ top: "22%", width: "42%", aspectRatio: "1" }}
            />
            <div
              className="absolute left-1/2 -translate-x-1/2 rounded-t-full bg-amber-950/40"
              style={{ top: "52%", width: "78%", height: "48%" }}
            />
          </>
        )}

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

        {/* region layout (2-guest stacked, grid, …) — each region a DISTINCT
            source tile so two people read as two people, not one repeated. */}
        {isRegions &&
          (layout.regions ?? []).map((r, i) => {
            const tints = [
              { bg: "from-sky-500/25 to-sky-900/40", dot: "bg-sky-300/80" },
              { bg: "from-amber-400/25 to-amber-900/40", dot: "bg-amber-200/80" },
              { bg: "from-violet-500/25 to-violet-900/40", dot: "bg-violet-300/80" },
              { bg: "from-rose-500/25 to-rose-900/40", dot: "bg-rose-300/80" },
            ];
            const t = tints[i % tints.length];
            const isWide = r.source.mode === "wide";
            return (
              <div
                key={i}
                className={`absolute z-10 flex flex-col items-center justify-center gap-1 overflow-hidden border border-white/10 bg-gradient-to-b ${t.bg}`}
                style={{
                  left: `${r.x * 100}%`,
                  top: `${r.y * 100}%`,
                  width: `${r.w * 100}%`,
                  height: `${r.h * 100}%`,
                }}
              >
                {isWide ? (
                  <div className="h-1/3 w-2/3 rounded-md border border-white/30 bg-white/10" />
                ) : (
                  <div className={`h-8 w-8 rounded-full ${t.dot}`} />
                )}
                <span className="rounded bg-black/55 px-1.5 py-0.5 text-[8px] font-bold tracking-wider text-white/90">
                  {regionLabel(r.source)}
                </span>
              </div>
            );
          })}

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

        {/* real logo — draggable to a corner, resize handle when selected */}
        {branding?.logo_path && (
          <div
            onPointerDown={(e) => {
              if (!editable) return;
              e.stopPropagation();
              setSelected("logo");
              setDragging("logo");
            }}
            className={`absolute z-30 ${editable ? "cursor-grab active:cursor-grabbing" : ""} ${
              selected === "logo" ? "outline outline-2 outline-emerald-400/80 outline-offset-2" : ""
            }`}
            style={
              dragging === "logo" && livePos
                ? { left: `${livePos.xPct}%`, top: `${livePos.yPct}%`, transform: "translate(-50%,-50%)", width: `${(branding.scale ?? 0.1) * 100}%`, opacity: branding.opacity ?? 1 }
                : logoCorner
            }
          >
            <img
              src={TemplatesApi.assetUrl(branding.logo_path)}
              alt="logo"
              draggable={false}
              className="pointer-events-none w-full object-contain"
            />
            {selected === "logo" && editable && (
              <div
                onPointerDown={(e) => {
                  e.stopPropagation();
                  setDragging("logo-resize");
                }}
                title="Redimensionar"
                className={`absolute h-3 w-3 cursor-nwse-resize rounded-sm border border-slate-900 bg-emerald-400 ${
                  (branding.position ?? "top-right").startsWith("top") ? "-bottom-1.5" : "-top-1.5"
                } ${(branding.position ?? "top-right").endsWith("left") ? "-right-1.5" : "-left-1.5"}`}
              />
            )}
          </div>
        )}

        {/* HOOK view: the title card shown during the first seconds */}
        {showHook ? (
          <div
            className="absolute inset-0 z-20 flex px-4"
            style={{ alignItems: hookVAlign, paddingTop: "8%", paddingBottom: "8%" }}
          >
            <div
              onPointerDown={(e) => {
                if (!editable) return;
                e.stopPropagation();
                setSelected("hook");
                setDragging("hook");
              }}
              className={`w-full text-center font-extrabold leading-tight text-white ${
                editable ? "cursor-grab active:cursor-grabbing" : ""
              } ${selected === "hook" ? "outline outline-2 outline-emerald-400/80 outline-offset-4" : ""}`}
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
            onPointerDown={(e) => {
              if (!editable) return;
              e.stopPropagation();
              setSelected("subs");
              setDragging("subs");
            }}
            className={`absolute z-20 flex flex-col items-center text-center leading-tight ${
              editable ? "cursor-grab active:cursor-grabbing" : ""
            } ${selected === "subs" ? "rounded outline outline-2 outline-emerald-400/80 outline-offset-4" : ""}`}
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
                  const active = idx === highlightWord;
                  let st: React.CSSProperties = { color: active ? hiColor : lineColor };
                  if (anim === "karaoke") st = { color: idx <= highlightWord ? hiColor : lineColor };
                  else if (anim === "box")
                    st = active
                      ? { color: lineColor, background: hiColor, borderRadius: 4, padding: "0 0.15em" }
                      : { color: lineColor };
                  else if (anim === "cumulative")
                    st = { color: active ? hiColor : lineColor, opacity: idx <= highlightWord ? 1 : 0.12 };
                  else // highlight
                    st = { color: active ? hiColor : lineColor, display: "inline-block", transform: active ? "scale(1.12)" : "none" };
                  return (
                    <span key={wi} style={{ transition: "transform .12s, opacity .12s", ...st }}>
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
