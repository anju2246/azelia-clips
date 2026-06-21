import React, { useState } from "react";
import toast from "react-hot-toast";
import {
  Type,
  Frame,
  Wand2,
  LayoutGrid,
  Download,
  Save,
  X,
  Check,
  Lock,
  Minus,
  Plus,
} from "lucide-react";
import {
  TemplatesApi,
  type ClipTemplate,
  type SubtitleSpec,
  type LayoutSpec,
} from "../../lib/api";
import { TemplatePreview } from "./TemplatePreview";
import { TemplateChat } from "./TemplateChat";
import { assToHex, cssToAss } from "./colors";

type Section = "texto" | "encuadre" | "animacion" | "presets";
const ANIMATIONS = ["highlight", "karaoke", "box", "cumulative"] as const;
const FONTS = ["Montserrat", "Anton", "Bebas Neue", "Impact", "Inter", "Poppins", "Oswald"];

interface Props {
  template: ClipTemplate;
  presets: ClipTemplate[];
  visionAvailable: boolean;
  onClose: () => void;
  onSaved: (t: ClipTemplate) => void;
}

const NAV: { id: Section; label: string; icon: React.ElementType }[] = [
  { id: "texto", label: "Texto", icon: Type },
  { id: "encuadre", label: "Encuadre", icon: Frame },
  { id: "animacion", label: "Animación", icon: Wand2 },
  { id: "presets", label: "Presets", icon: LayoutGrid },
];

const Row: React.FC<{ label: string; value?: string; children: React.ReactNode }> = ({
  label,
  value,
  children,
}) => (
  <div className="flex flex-col gap-1.5">
    <div className="flex items-center justify-between text-[11px] uppercase tracking-wide text-slate-500">
      <span>{label}</span>
      {value && <span className="text-slate-400">{value}</span>}
    </div>
    {children}
  </div>
);

const Toggle: React.FC<{
  options: { value: string; label: string }[];
  value: string;
  disabled?: boolean;
  onChange: (v: string) => void;
}> = ({ options, value, disabled, onChange }) => (
  <div className="grid grid-cols-2 gap-1 rounded-lg bg-slate-800/70 p-1">
    {options.map((o) => (
      <button
        key={o.value}
        disabled={disabled}
        onClick={() => onChange(o.value)}
        className={`rounded-md py-1.5 text-sm font-medium transition ${
          value === o.value
            ? "bg-emerald-500 text-white"
            : "text-slate-300 hover:bg-slate-700/60"
        } disabled:opacity-50`}
      >
        {o.label}
      </button>
    ))}
  </div>
);

const Slider: React.FC<{
  min: number;
  max: number;
  step?: number;
  value: number;
  disabled?: boolean;
  onChange: (v: number) => void;
}> = ({ min, max, step, value, disabled, onChange }) => (
  <input
    type="range"
    min={min}
    max={max}
    step={step}
    value={value}
    disabled={disabled}
    onChange={(e) => onChange(Number(e.target.value))}
    className="w-full accent-emerald-500 disabled:opacity-50"
  />
);

const Swatch: React.FC<{ label: string; ass: string; disabled?: boolean; onChange: (ass: string) => void }> = ({
  label,
  ass,
  disabled,
  onChange,
}) => (
  <label className="flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-800/60 p-2">
    <span className="relative h-7 w-7 overflow-hidden rounded-md border border-slate-600">
      <input
        type="color"
        value={assToHex(ass)}
        disabled={disabled}
        onChange={(e) => onChange(cssToAss(e.target.value))}
        className="absolute -inset-2 h-[calc(100%+1rem)] w-[calc(100%+1rem)] cursor-pointer disabled:cursor-default"
      />
    </span>
    <span className="flex flex-col">
      <span className="text-xs font-medium text-slate-200">{label}</span>
      <span className="font-mono text-[10px] uppercase text-slate-500">{assToHex(ass)}</span>
    </span>
  </label>
);

export const TemplateEditorModal: React.FC<Props> = ({
  template,
  presets,
  visionAvailable,
  onClose,
  onSaved,
}) => {
  const [draft, setDraft] = useState<ClipTemplate>(template);
  const [section, setSection] = useState<Section>("texto");
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState(false);

  const editable = !draft.is_builtin;
  const s = draft.subtitles;
  const l = draft.layout;

  const patch = (p: { subtitles?: Partial<SubtitleSpec>; layout?: Partial<LayoutSpec> }) => {
    setSavedAt(false);
    setDraft((d) => ({
      ...d,
      subtitles: { ...d.subtitles, ...p.subtitles },
      layout: { ...d.layout, ...p.layout },
    }));
  };
  const subs = (p: Partial<SubtitleSpec>) => patch({ subtitles: p });
  const lay = (p: Partial<LayoutSpec>) => patch({ layout: p });

  const handleSave = async () => {
    setSaving(true);
    try {
      const saved = await TemplatesApi.update(draft.id, {
        name: draft.name,
        description: draft.description,
        author: draft.author,
        subtitles: draft.subtitles,
        layout: draft.layout,
      });
      setDraft(saved);
      setSavedAt(true);
      onSaved(saved);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const handleExport = () => {
    const blob = new Blob([JSON.stringify(draft, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${draft.id}.azt`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-slate-950 text-slate-100">
      {/* Header */}
      <header className="flex h-14 shrink-0 items-center justify-between border-b border-slate-800 px-4">
        <div className="flex items-center gap-2 text-sm">
          <button onClick={onClose} className="rounded-md p-1.5 text-slate-400 hover:bg-slate-800">
            <X size={16} />
          </button>
          <span className="text-slate-500">Templates</span>
          <span className="text-slate-600">/</span>
          <span className="font-semibold">{draft.name}</span>
          {draft.is_builtin && (
            <span className="inline-flex items-center gap-1 rounded border border-amber-400/30 px-1.5 py-0.5 text-[10px] uppercase text-amber-400/90">
              <Lock size={10} /> preset
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleExport}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 px-3 py-1.5 text-sm hover:bg-slate-800"
          >
            <Download size={14} /> Exportar
          </button>
          {editable && (
            <button
              onClick={handleSave}
              disabled={saving}
              className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-500 px-4 py-1.5 text-sm font-semibold text-white hover:bg-emerald-400 disabled:opacity-50"
            >
              {savedAt ? <Check size={14} /> : <Save size={14} />}
              {saving ? "Guardando…" : savedAt ? "Guardado" : "Guardar"}
            </button>
          )}
        </div>
      </header>

      {/* 3-panel body */}
      <div className="grid min-h-0 flex-1 grid-cols-[330px_1fr_360px]">
        {/* Left: nav rail + controls */}
        <div className="flex min-h-0 border-r border-slate-800">
          <nav className="flex w-16 shrink-0 flex-col items-center gap-1 border-r border-slate-800 py-3">
            {NAV.map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                onClick={() => setSection(id)}
                className={`flex w-14 flex-col items-center gap-1 rounded-lg py-2 text-[10px] transition ${
                  section === id
                    ? "bg-emerald-500/15 text-emerald-400"
                    : "text-slate-500 hover:bg-slate-800/60 hover:text-slate-300"
                }`}
              >
                <Icon size={18} />
                {label}
              </button>
            ))}
          </nav>

          <div className="flex-1 overflow-y-auto p-4">
            {section === "texto" && (
              <div className="flex flex-col gap-5">
                <h3 className="text-sm font-semibold text-slate-200">Subtítulos</h3>
                <Row label="Fuente">
                  <select
                    value={s.font_name}
                    disabled={!editable}
                    onChange={(e) => subs({ font_name: e.target.value })}
                    className="rounded-lg border border-slate-700 bg-slate-800/60 px-3 py-2 text-sm disabled:opacity-50"
                  >
                    {[...new Set([s.font_name, ...FONTS])].map((f) => (
                      <option key={f} value={f}>
                        {f}
                      </option>
                    ))}
                  </select>
                </Row>
                <Row label="Tamaño" value={`${s.font_size}px`}>
                  <Slider min={12} max={200} value={s.font_size} disabled={!editable} onChange={(v) => subs({ font_size: v })} />
                </Row>
                <Row label="Peso">
                  <Toggle
                    options={[
                      { value: "regular", label: "Regular" },
                      { value: "bold", label: "Bold" },
                    ]}
                    value={s.bold ? "bold" : "regular"}
                    disabled={!editable}
                    onChange={(v) => subs({ bold: v === "bold" })}
                  />
                </Row>
                <Row label="Colores">
                  <div className="grid grid-cols-2 gap-2">
                    <Swatch label="Texto" ass={s.primary_color} disabled={!editable} onChange={(c) => subs({ primary_color: c })} />
                    <Swatch label="Resalte" ass={s.secondary_color} disabled={!editable} onChange={(c) => subs({ secondary_color: c })} />
                  </div>
                </Row>
                <Row label="Palabras por línea" value={`${s.words_per_line}`}>
                  <Slider min={1} max={10} value={s.words_per_line} disabled={!editable} onChange={(v) => subs({ words_per_line: v })} />
                </Row>
                <Row label="Contorno" value={`${s.outline}`}>
                  <Slider min={0} max={10} value={s.outline} disabled={!editable} onChange={(v) => subs({ outline: v })} />
                </Row>
                <Row label="Sombra" value={`${s.shadow}`}>
                  <Slider min={0} max={10} value={s.shadow} disabled={!editable} onChange={(v) => subs({ shadow: v })} />
                </Row>
              </div>
            )}

            {section === "encuadre" && (
              <div className="flex flex-col gap-5">
                <h3 className="text-sm font-semibold text-slate-200">Encuadre</h3>
                <Row label="Composición">
                  <Toggle
                    options={[
                      { value: "split", label: "Split" },
                      { value: "fullscreen", label: "Full-screen" },
                    ]}
                    value={l.type}
                    disabled={!editable}
                    onChange={(v) => lay({ type: v as LayoutSpec["type"] })}
                  />
                  <p className="mt-1 text-xs text-slate-500">
                    {l.type === "split"
                      ? "Close-up arriba + plano abierto 16:9 abajo."
                      : "Un solo plano a pantalla completa 9:16."}
                  </p>
                </Row>
                {l.type === "split" && (
                  <Row label="Proporción wide" value={`${Math.round(l.wide_height_ratio * 100)}%`}>
                    <Slider
                      min={0.2}
                      max={0.5}
                      step={0.01}
                      value={l.wide_height_ratio}
                      disabled={!editable}
                      onChange={(v) => lay({ wide_height_ratio: v })}
                    />
                    <p className="mt-1 text-xs text-slate-500">
                      También puedes arrastrar el divisor en el preview.
                    </p>
                  </Row>
                )}
              </div>
            )}

            {section === "animacion" && (
              <div className="flex flex-col gap-4">
                <h3 className="text-sm font-semibold text-slate-200">Animación</h3>
                <div className="flex flex-col gap-2">
                  {ANIMATIONS.map((anim) => (
                    <button
                      key={anim}
                      disabled={!editable}
                      onClick={() => subs({ animation: anim })}
                      className={`flex items-center justify-between rounded-lg border px-3 py-2.5 text-sm transition ${
                        s.animation === anim
                          ? "border-emerald-500/60 bg-emerald-500/10 text-white"
                          : "border-slate-700 text-slate-300 hover:bg-slate-800/60"
                      } disabled:opacity-50`}
                    >
                      <span className="capitalize">{anim}</span>
                      {s.animation === anim && <Check size={15} className="text-emerald-400" />}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {section === "presets" && (
              <div className="flex flex-col gap-4">
                <h3 className="text-sm font-semibold text-slate-200">Aplicar estilo de preset</h3>
                <p className="text-xs text-slate-500">
                  Copia el estilo de un preset a este template. Puedes seguir ajustándolo después.
                </p>
                <div className="flex flex-col gap-2">
                  {presets.map((p) => (
                    <button
                      key={p.id}
                      disabled={!editable}
                      onClick={() => patch({ subtitles: p.subtitles, layout: p.layout })}
                      className="flex items-center justify-between rounded-lg border border-slate-700 px-3 py-2.5 text-sm text-slate-200 hover:border-emerald-500/60 hover:bg-slate-800/60 disabled:opacity-50"
                    >
                      <span>{p.name}</span>
                      <span className="text-xs text-slate-500">{p.subtitles.font_name}</span>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Center: preview + floating toolbar */}
        <div className="flex min-h-0 flex-col items-center justify-center gap-4 bg-slate-900/40 p-6">
          <TemplatePreview subtitles={s} layout={l} editable={editable} onChange={patch} />

          <div className="flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-900/90 px-2 py-1.5 shadow-lg">
            <span className="px-1 text-slate-400">
              <Type size={15} />
            </span>
            <button
              disabled={!editable}
              onClick={() => subs({ font_size: Math.max(12, s.font_size - 2) })}
              className="rounded p-1 text-slate-300 hover:bg-slate-800 disabled:opacity-40"
            >
              <Minus size={14} />
            </button>
            <span className="w-7 text-center text-xs tabular-nums text-slate-300">{s.font_size}</span>
            <button
              disabled={!editable}
              onClick={() => subs({ font_size: Math.min(200, s.font_size + 2) })}
              className="rounded p-1 text-slate-300 hover:bg-slate-800 disabled:opacity-40"
            >
              <Plus size={14} />
            </button>
            <div className="mx-1 h-5 w-px bg-slate-700" />
            <ColorDot ass={s.primary_color} disabled={!editable} onChange={(c) => subs({ primary_color: c })} />
            <ColorDot ass={s.secondary_color} disabled={!editable} onChange={(c) => subs({ secondary_color: c })} />
          </div>
        </div>

        {/* Right: chat */}
        <div className="min-h-0 border-l border-slate-800">
          <TemplateChat
            draft={draft}
            visionAvailable={visionAvailable}
            onApply={(t) => {
              setSavedAt(false);
              setDraft(t);
            }}
          />
        </div>
      </div>
    </div>
  );
};

const ColorDot: React.FC<{ ass: string; disabled?: boolean; onChange: (ass: string) => void }> = ({
  ass,
  disabled,
  onChange,
}) => (
  <span className="relative h-6 w-6 overflow-hidden rounded-md border border-slate-600">
    <span className="block h-full w-full" style={{ background: assToHex(ass) }} />
    <input
      type="color"
      value={assToHex(ass)}
      disabled={disabled}
      onChange={(e) => onChange(cssToAss(e.target.value))}
      className="absolute -inset-2 h-[calc(100%+1rem)] w-[calc(100%+1rem)] cursor-pointer opacity-0 disabled:cursor-default"
    />
  </span>
);
