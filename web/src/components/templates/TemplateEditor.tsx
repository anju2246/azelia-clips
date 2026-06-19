import React from "react";
import type { SubtitleSpec, LayoutSpec } from "../../lib/api";
import { assToHex, cssToAss } from "./colors";

interface Props {
  subtitles: SubtitleSpec;
  layout: LayoutSpec;
  disabled: boolean;
  onChange: (patch: {
    subtitles?: Partial<SubtitleSpec>;
    layout?: Partial<LayoutSpec>;
  }) => void;
}

const ANIMATIONS = ["highlight", "karaoke", "box", "cumulative"] as const;

const Field: React.FC<{ label: string; children: React.ReactNode }> = ({
  label,
  children,
}) => (
  <label className="flex flex-col gap-1 text-xs">
    <span className="text-zinc-400">{label}</span>
    {children}
  </label>
);

const inputCls =
  "rounded-md border border-zinc-700 bg-zinc-900 px-2 py-1.5 text-sm text-white disabled:opacity-50";

/** Field editor for a template's subtitles + layout. Position (alignment/
 * margin_v) and the split ratio are driven by the preview's drag, but shown
 * here read-only so the values are visible. */
export const TemplateEditor: React.FC<Props> = ({
  subtitles: s,
  layout: l,
  disabled,
  onChange,
}) => {
  const subs = (patch: Partial<SubtitleSpec>) => onChange({ subtitles: patch });
  const lay = (patch: Partial<LayoutSpec>) => onChange({ layout: patch });

  return (
    <div className="grid grid-cols-2 gap-3">
      <Field label="Fuente">
        <input
          className={inputCls}
          value={s.font_name}
          disabled={disabled}
          onChange={(e) => subs({ font_name: e.target.value })}
        />
      </Field>
      <Field label={`Tamaño (${s.font_size}px)`}>
        <input
          type="range"
          min={12}
          max={200}
          value={s.font_size}
          disabled={disabled}
          onChange={(e) => subs({ font_size: Number(e.target.value) })}
        />
      </Field>

      <Field label="Color texto">
        <input
          type="color"
          className="h-9 w-full rounded-md bg-zinc-900 disabled:opacity-50"
          value={assToHex(s.primary_color)}
          disabled={disabled}
          onChange={(e) => subs({ primary_color: cssToAss(e.target.value) })}
        />
      </Field>
      <Field label="Color resaltado">
        <input
          type="color"
          className="h-9 w-full rounded-md bg-zinc-900 disabled:opacity-50"
          value={assToHex(s.secondary_color)}
          disabled={disabled}
          onChange={(e) => subs({ secondary_color: cssToAss(e.target.value) })}
        />
      </Field>

      <Field label="Animación">
        <select
          className={inputCls}
          value={s.animation}
          disabled={disabled}
          onChange={(e) => subs({ animation: e.target.value as SubtitleSpec["animation"] })}
        >
          {ANIMATIONS.map((a) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
        </select>
      </Field>
      <Field label={`Palabras por línea (${s.words_per_line})`}>
        <input
          type="range"
          min={1}
          max={10}
          value={s.words_per_line}
          disabled={disabled}
          onChange={(e) => subs({ words_per_line: Number(e.target.value) })}
        />
      </Field>

      <Field label="Layout">
        <select
          className={inputCls}
          value={l.type}
          disabled={disabled}
          onChange={(e) => lay({ type: e.target.value as LayoutSpec["type"] })}
        >
          <option value="split">split</option>
          <option value="fullscreen">fullscreen</option>
        </select>
      </Field>
      <Field label="Posición (arrastra en el preview)">
        <div className={`${inputCls} flex items-center gap-3 text-zinc-400`}>
          <span>anchor {s.alignment}</span>
          <span>margen {s.margin_v}</span>
          {l.type === "split" && (
            <span>split {l.wide_height_ratio.toFixed(2)}</span>
          )}
        </div>
      </Field>
    </div>
  );
};
