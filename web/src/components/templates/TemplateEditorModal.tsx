import React, { useState, useEffect, useRef } from "react";
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
  Megaphone,
  Image as ImageIcon,
} from "lucide-react";
import {
  TemplatesApi,
  DEFAULT_INTRO_TITLE,
  DEFAULT_BRANDING,
  DEFAULT_PROGRESS_BAR,
  twoGuestSplitLayout,
  type ClipTemplate,
  type SubtitleSpec,
  type LayoutSpec,
  type IntroTitleSpec,
  type BrandingSpec,
  type ProgressBarSpec,
  type BumpersSpec,
} from "../../lib/api";
import { TemplatePreview } from "./TemplatePreview";
import { TemplateChat } from "./TemplateChat";
import { LegoLayoutEditor } from "./LegoLayoutEditor";
import { assToHex, cssToAss } from "./colors";

// Mirror of layout.resolve_regions — turn any layout into an editable region list.
function layoutToRegions(l: LayoutSpec) {
  if (l.type === "regions") return l.regions ?? [];
  if (l.type === "fullscreen")
    return [{ x: 0, y: 0, w: 1, h: 1, source: { mode: "active_speaker" as const } }];
  const wide = l.wide_height_ratio;
  return [
    { x: 0, y: 0, w: 1, h: 1 - wide, source: { mode: "active_speaker" as const } },
    { x: 0, y: 1 - wide, w: 1, h: wide, source: { mode: "wide" as const, speaker_ref: null } },
  ];
}

type Section = "texto" | "encuadre" | "animacion" | "hook" | "marca" | "presets";
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
  { id: "hook", label: "Hook", icon: Megaphone },
  { id: "marca", label: "Extras", icon: ImageIcon },
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
  // Lowercased set of fonts the machine actually has. The preview loads web
  // fonts so it looks right, but the ASS render can only use installed fonts —
  // so we flag a chosen font that isn't installed (it would be substituted).
  const [installedFonts, setInstalledFonts] = useState<Set<string> | null>(null);

  useEffect(() => {
    TemplatesApi.fonts()
      .then((r) => setInstalledFonts(new Set(r.installed.map((f) => f.toLowerCase()))))
      .catch(() => setInstalledFonts(null));
  }, []);

  // null = unknown (fetch failed) → don't warn; otherwise exact membership.
  const fontInstalled = (name: string) =>
    installedFonts === null || installedFonts.has(name.trim().toLowerCase());

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
  // Hook title lives at the template root (nullable). Editing any field while
  // it's off implicitly turns it on from the default.
  const intro = (p: Partial<IntroTitleSpec>) => {
    setSavedAt(false);
    setDraft((d) => ({
      ...d,
      intro_title: { ...(d.intro_title ?? DEFAULT_INTRO_TITLE), ...p },
    }));
  };
  const brand = (p: Partial<BrandingSpec>) => {
    setSavedAt(false);
    setDraft((d) => ({
      ...d,
      branding: { ...(d.branding ?? DEFAULT_BRANDING), ...p },
    }));
  };
  const pbar = (p: Partial<ProgressBarSpec>) => {
    setSavedAt(false);
    setDraft((d) => ({
      ...d,
      progress_bar: { ...(d.progress_bar ?? DEFAULT_PROGRESS_BAR), ...p },
    }));
  };
  const logoInputRef = useRef<HTMLInputElement>(null);
  const handleLogoUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    try {
      const { logo_path } = await TemplatesApi.uploadLogo(file);
      brand({ logo_path });
      toast.success("Logo subido");
    } catch (err) {
      toast.error((err as Error).message);
    }
  };

  const bmp = (p: Partial<BumpersSpec>) => {
    setSavedAt(false);
    setDraft((d) => ({ ...d, bumpers: { ...(d.bumpers ?? {}), ...p } }));
  };
  const introInputRef = useRef<HTMLInputElement>(null);
  const outroInputRef = useRef<HTMLInputElement>(null);
  const handleBumperUpload =
    (slot: "intro_path" | "outro_path") =>
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      e.target.value = "";
      if (!file) return;
      try {
        const { path } = await TemplatesApi.uploadBumper(file);
        bmp({ [slot]: path });
        toast.success(slot === "intro_path" ? "Intro subido" : "Outro subido");
      } catch (err) {
        toast.error((err as Error).message);
      }
    };

  const handleSave = async () => {
    setSaving(true);
    try {
      const saved = await TemplatesApi.update(draft.id, {
        name: draft.name,
        description: draft.description,
        author: draft.author,
        subtitles: draft.subtitles,
        layout: draft.layout,
        intro_title: draft.intro_title ?? null,
        branding: draft.branding ?? null,
        progress_bar: draft.progress_bar ?? null,
        bumpers: draft.bumpers ?? null,
      });
      setDraft(saved);
      setSavedAt(true);
      onSaved(saved);
      if (!fontInstalled(saved.subtitles.font_name)) {
        toast(
          `Guardado. Ojo: la fuente "${saved.subtitles.font_name}" no está instalada en esta máquina; el render usará una de reemplazo.`,
          { icon: "⚠️", duration: 6000 },
        );
      }
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
                        {fontInstalled(f) ? "" : " — no instalada"}
                      </option>
                    ))}
                  </select>
                  {!fontInstalled(s.font_name) && (
                    <p className="text-xs text-amber-400/90">
                      No instalada en esta máquina; el render usará una de reemplazo.
                    </p>
                  )}
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
                  <div className="grid grid-cols-3 gap-1 rounded-lg bg-slate-800/70 p-1">
                    {(
                      [
                        ["split", "1 invitado"],
                        ["regions", "2 invitados"],
                        ["fullscreen", "Full-screen"],
                      ] as const
                    ).map(([t, label]) => (
                      <button
                        key={t}
                        disabled={!editable}
                        onClick={() =>
                          t === "regions" ? lay(twoGuestSplitLayout()) : lay({ type: t })
                        }
                        className={`rounded-md py-1.5 text-xs font-medium transition ${
                          l.type === t
                            ? "bg-emerald-500 text-white"
                            : "text-slate-300 hover:bg-slate-700/60"
                        } disabled:opacity-50`}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                  <p className="mt-1 text-xs text-slate-500">
                    {l.type === "split"
                      ? "Close-up arriba + plano abierto 16:9 abajo."
                      : l.type === "regions"
                        ? "Dos invitados apilados (cada cara fija en su mitad)."
                        : "Un solo plano a pantalla completa 9:16."}
                  </p>
                </Row>

                {l.type !== "regions" && editable && (
                  <button
                    onClick={() => lay({ type: "regions", regions: layoutToRegions(l) })}
                    className="self-start rounded-lg border border-slate-700 px-3 py-1.5 text-xs text-slate-300 hover:border-emerald-500/60 hover:text-white"
                  >
                    🧩 Personalizar layout (Lego)
                  </button>
                )}

                {l.type === "regions" && (
                  <Row label="Bloques del layout">
                    <LegoLayoutEditor
                      regions={l.regions ?? []}
                      editable={editable}
                      onChange={(regions) => lay({ regions })}
                    />
                    <p className="mt-1 text-xs text-slate-500">
                      Apila bloques (quien habla / persona fija / plano abierto) y arrastra los
                      bordes para redimensionar — el snap te lleva a proporciones limpias. Mostrar 2
                      personas a la vez requiere que ambas caras estén en el video original.
                    </p>
                  </Row>
                )}
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

                <div className="mt-2 border-t border-slate-800 pt-4">
                  <Row label="Barra de progreso">
                    <Toggle
                      options={[
                        { value: "off", label: "Off" },
                        { value: "on", label: "On" },
                      ]}
                      value={draft.progress_bar?.enabled ? "on" : "off"}
                      disabled={!editable}
                      onChange={(v) => pbar({ enabled: v === "on" })}
                    />
                  </Row>
                  {draft.progress_bar?.enabled && (
                    <div className="mt-4 flex flex-col gap-4">
                      <Row label="Color">
                        <Swatch
                          label="Barra"
                          ass={draft.progress_bar.color}
                          disabled={!editable}
                          onChange={(c) => pbar({ color: c })}
                        />
                      </Row>
                      <Row label="Alto" value={`${draft.progress_bar.height}px`}>
                        <Slider
                          min={2}
                          max={40}
                          value={draft.progress_bar.height}
                          disabled={!editable}
                          onChange={(v) => pbar({ height: v })}
                        />
                      </Row>
                      <Row label="Borde">
                        <Toggle
                          options={[
                            { value: "bottom", label: "Abajo" },
                            { value: "top", label: "Arriba" },
                          ]}
                          value={draft.progress_bar.position}
                          disabled={!editable}
                          onChange={(v) => pbar({ position: v as ProgressBarSpec["position"] })}
                        />
                      </Row>
                    </div>
                  )}
                </div>
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

            {section === "hook" && (
              <div className="flex flex-col gap-5">
                <h3 className="text-sm font-semibold text-slate-200">
                  Título inicial (hook)
                </h3>
                <p className="text-xs text-slate-500">
                  Muestra el título del clip en pantalla los primeros segundos,
                  antes de que salgan los subtítulos. El texto sale del título
                  que genera la curación; aquí solo defines el estilo.
                </p>
                <Row label="Activar">
                  <Toggle
                    options={[
                      { value: "off", label: "Off" },
                      { value: "on", label: "On" },
                    ]}
                    value={draft.intro_title?.enabled ? "on" : "off"}
                    disabled={!editable}
                    onChange={(v) => intro({ enabled: v === "on" })}
                  />
                </Row>
                {draft.intro_title?.enabled && (
                  <>
                    <Row
                      label="Duración"
                      value={`${draft.intro_title.duration_s.toFixed(1)}s`}
                    >
                      <Slider
                        min={1}
                        max={8}
                        step={0.5}
                        value={draft.intro_title.duration_s}
                        disabled={!editable}
                        onChange={(v) => intro({ duration_s: v })}
                      />
                    </Row>
                    <Row label="Tamaño" value={`${draft.intro_title.font_size}px`}>
                      <Slider
                        min={24}
                        max={160}
                        value={draft.intro_title.font_size}
                        disabled={!editable}
                        onChange={(v) => intro({ font_size: v })}
                      />
                    </Row>
                    <Row label="Posición">
                      <div className="grid grid-cols-3 gap-1 rounded-lg bg-slate-800/70 p-1">
                        {(["top", "center", "bottom"] as const).map((pos) => (
                          <button
                            key={pos}
                            disabled={!editable}
                            onClick={() => intro({ position: pos })}
                            className={`rounded-md py-1.5 text-sm font-medium capitalize transition ${
                              draft.intro_title?.position === pos
                                ? "bg-emerald-500 text-white"
                                : "text-slate-300 hover:bg-slate-700/60"
                            } disabled:opacity-50`}
                          >
                            {pos === "top" ? "Arriba" : pos === "center" ? "Centro" : "Abajo"}
                          </button>
                        ))}
                      </div>
                    </Row>
                    <Row label="Color">
                      <Swatch
                        label="Texto"
                        ass={draft.intro_title.color}
                        disabled={!editable}
                        onChange={(c) => intro({ color: c })}
                      />
                    </Row>
                    <Row label="Caja de fondo">
                      <Toggle
                        options={[
                          { value: "off", label: "No" },
                          { value: "on", label: "Sí" },
                        ]}
                        value={draft.intro_title.box ? "on" : "off"}
                        disabled={!editable}
                        onChange={(v) => intro({ box: v === "on" })}
                      />
                    </Row>
                    <Row label="Retrasar subtítulos">
                      <Toggle
                        options={[
                          { value: "off", label: "No" },
                          { value: "on", label: "Sí" },
                        ]}
                        value={draft.intro_title.delay_captions ? "on" : "off"}
                        disabled={!editable}
                        onChange={(v) => intro({ delay_captions: v === "on" })}
                      />
                      <p className="mt-1 text-xs text-slate-500">
                        Si está activo, los subtítulos no aparecen hasta que
                        termina el título.
                      </p>
                    </Row>
                  </>
                )}
              </div>
            )}

            {section === "marca" && (
              <div className="flex flex-col gap-5">
                <h3 className="text-sm font-semibold text-slate-200">
                  Logo / marca de agua
                </h3>
                <p className="text-xs text-slate-500">
                  Superpone tu logo en una esquina del clip. PNG con transparencia
                  recomendado.
                </p>
                <input
                  ref={logoInputRef}
                  type="file"
                  accept="image/png,image/webp,image/jpeg"
                  className="hidden"
                  onChange={handleLogoUpload}
                />
                <Row label="Logo">
                  <div className="flex items-center gap-2">
                    <button
                      disabled={!editable}
                      onClick={() => logoInputRef.current?.click()}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 px-3 py-2 text-sm hover:bg-slate-800 disabled:opacity-50"
                    >
                      <ImageIcon size={14} />
                      {draft.branding?.logo_path ? "Cambiar logo" : "Subir logo"}
                    </button>
                    {draft.branding?.logo_path && (
                      <>
                        <span className="truncate font-mono text-[11px] text-slate-400">
                          {draft.branding.logo_path}
                        </span>
                        <button
                          disabled={!editable}
                          onClick={() => brand({ logo_path: null })}
                          className="rounded p-1 text-slate-400 hover:bg-slate-800 disabled:opacity-50"
                          title="Quitar logo"
                        >
                          <X size={14} />
                        </button>
                      </>
                    )}
                  </div>
                </Row>
                {draft.branding?.logo_path && (
                  <>
                    <Row label="Posición">
                      <div className="grid grid-cols-2 gap-1 rounded-lg bg-slate-800/70 p-1">
                        {(
                          [
                            ["top-left", "Arriba izq."],
                            ["top-right", "Arriba der."],
                            ["bottom-left", "Abajo izq."],
                            ["bottom-right", "Abajo der."],
                          ] as const
                        ).map(([pos, label]) => (
                          <button
                            key={pos}
                            disabled={!editable}
                            onClick={() => brand({ position: pos })}
                            className={`rounded-md py-1.5 text-xs font-medium transition ${
                              draft.branding?.position === pos
                                ? "bg-emerald-500 text-white"
                                : "text-slate-300 hover:bg-slate-700/60"
                            } disabled:opacity-50`}
                          >
                            {label}
                          </button>
                        ))}
                      </div>
                    </Row>
                    <Row
                      label="Tamaño"
                      value={`${Math.round((draft.branding.scale ?? 0.1) * 100)}% del ancho`}
                    >
                      <Slider
                        min={0.02}
                        max={0.3}
                        step={0.01}
                        value={draft.branding.scale}
                        disabled={!editable}
                        onChange={(v) => brand({ scale: v })}
                      />
                    </Row>
                    <Row
                      label="Opacidad"
                      value={`${Math.round((draft.branding.opacity ?? 1) * 100)}%`}
                    >
                      <Slider
                        min={0}
                        max={1}
                        step={0.05}
                        value={draft.branding.opacity}
                        disabled={!editable}
                        onChange={(v) => brand({ opacity: v })}
                      />
                    </Row>
                    <Row label="Margen" value={`${draft.branding.margin}px`}>
                      <Slider
                        min={0}
                        max={200}
                        value={draft.branding.margin}
                        disabled={!editable}
                        onChange={(v) => brand({ margin: v })}
                      />
                    </Row>
                  </>
                )}

                <div className="mt-2 border-t border-slate-800 pt-4">
                  <h3 className="mb-1 text-sm font-semibold text-slate-200">
                    Intro / Outro
                  </h3>
                  <p className="mb-3 text-xs text-slate-500">
                    Clips que se concatenan antes y después (se normalizan a
                    1080×1920).
                  </p>
                  <input
                    ref={introInputRef}
                    type="file"
                    accept="video/mp4,video/quicktime,video/x-matroska"
                    className="hidden"
                    onChange={handleBumperUpload("intro_path")}
                  />
                  <input
                    ref={outroInputRef}
                    type="file"
                    accept="video/mp4,video/quicktime,video/x-matroska"
                    className="hidden"
                    onChange={handleBumperUpload("outro_path")}
                  />
                  {(
                    [
                      ["intro_path", "Intro", introInputRef],
                      ["outro_path", "Outro", outroInputRef],
                    ] as const
                  ).map(([slot, label, ref]) => (
                    <div key={slot} className="mb-2 flex items-center gap-2">
                      <button
                        disabled={!editable}
                        onClick={() => ref.current?.click()}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 px-3 py-2 text-sm hover:bg-slate-800 disabled:opacity-50"
                      >
                        {draft.bumpers?.[slot] ? `Cambiar ${label}` : `Subir ${label}`}
                      </button>
                      {draft.bumpers?.[slot] && (
                        <>
                          <span className="truncate font-mono text-[11px] text-slate-400">
                            {draft.bumpers[slot]}
                          </span>
                          <button
                            disabled={!editable}
                            onClick={() => bmp({ [slot]: null })}
                            className="rounded p-1 text-slate-400 hover:bg-slate-800 disabled:opacity-50"
                            title={`Quitar ${label}`}
                          >
                            <X size={14} />
                          </button>
                        </>
                      )}
                    </div>
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
          <TemplatePreview template={draft} editable={editable} onChange={patch} />

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
