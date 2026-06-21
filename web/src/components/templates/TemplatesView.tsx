import React, { useEffect, useRef, useState } from "react";
import toast from "react-hot-toast";
import { Copy, Trash2, Lock, Plus, Layout, Type, Pencil, Download, Upload } from "lucide-react";
import { TemplatesApi, SettingsApi, type ClipTemplate } from "../../lib/api";
import { TemplateEditorModal } from "./TemplateEditorModal";

/**
 * Full-page Templates gallery. Editing/viewing a template opens a full-screen
 * 3-panel editor (controls · interactive preview · AI chat). Built-ins are
 * read-only (clone to edit); custom templates save via PUT.
 */
export const TemplatesView: React.FC = () => {
  const [templates, setTemplates] = useState<ClipTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [draft, setDraft] = useState<ClipTemplate | null>(null);
  const [visionAvailable, setVisionAvailable] = useState(false);
  const importRef = useRef<HTMLInputElement>(null);

  const refresh = () =>
    TemplatesApi.list()
      .then((r) => setTemplates(r.templates))
      .catch((e) => toast.error(e.message))
      .finally(() => setLoading(false));

  useEffect(() => {
    refresh();
    SettingsApi.getSettings()
      .then((s) => setVisionAvailable(!!s.vision_available))
      .catch(() => setVisionAvailable(false));
  }, []);

  const handleCreate = async () => {
    const name = window.prompt("Nombre del nuevo template:");
    if (!name?.trim()) return;
    try {
      const t = await TemplatesApi.create({ name: name.trim() });
      toast.success("Template creado");
      await refresh();
      setDraft(t);
    } catch (e) {
      toast.error((e as Error).message);
    }
  };

  const handleClone = async (t: ClipTemplate) => {
    const name = window.prompt("Nombre de la copia:", `${t.name} (copia)`);
    if (!name?.trim()) return;
    try {
      const c = await TemplatesApi.clone(t.id, name.trim());
      toast.success("Template clonado");
      await refresh();
      setDraft(c);
    } catch (e) {
      toast.error((e as Error).message);
    }
  };

  const handleDelete = async (t: ClipTemplate) => {
    if (!window.confirm(`¿Borrar "${t.name}"? No se puede deshacer.`)) return;
    try {
      await TemplatesApi.remove(t.id);
      toast.success("Template borrado");
      if (draft?.id === t.id) setDraft(null);
      refresh();
    } catch (e) {
      toast.error((e as Error).message);
    }
  };

  const handleExport = (t: ClipTemplate) => {
    const blob = new Blob([JSON.stringify(t, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${t.id}.azt`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    try {
      const res = await TemplatesApi.importFile(file);
      if (res.warnings?.includes("FONT_NOT_INSTALLED")) {
        toast(`Importado. Ojo: la fuente "${res.template.subtitles.font_name}" no está instalada.`, {
          icon: "⚠️",
        });
      } else {
        toast.success("Template importado");
      }
      await refresh();
      setDraft(res.template);
    } catch (err) {
      toast.error((err as Error).message);
    }
  };

  const presets = templates.filter((t) => t.is_builtin);

  return (
    <div className="max-w-5xl mx-auto pb-12">
      <div className="mb-8 flex items-start justify-between gap-4">
        <div>
          <h2 className="text-3xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-white to-zinc-400">
            Templates
          </h2>
          <p className="text-zinc-500 mt-2">
            Diseña el estilo de tus clips (subtítulos + layout). Los presets son
            de solo lectura: clónalos para editarlos a tu gusto.
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <input
            ref={importRef}
            type="file"
            accept=".azt,application/json"
            className="hidden"
            onChange={handleImport}
          />
          <button
            onClick={() => importRef.current?.click()}
            className="inline-flex items-center gap-2 rounded-lg border border-zinc-700 px-3 py-2 text-sm hover:bg-zinc-800 transition"
          >
            <Upload size={15} /> Importar
          </button>
          <button
            onClick={handleCreate}
            className="inline-flex items-center gap-2 rounded-lg bg-emerald-500 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-400 transition"
          >
            <Plus size={16} /> Nuevo
          </button>
        </div>
      </div>

      {/* Full-screen 3-panel editor */}
      {draft && (
        <TemplateEditorModal
          template={draft}
          presets={presets}
          visionAvailable={visionAvailable}
          onClose={() => setDraft(null)}
          onSaved={(t) => {
            setDraft(t);
            refresh();
          }}
        />
      )}

      {loading ? (
        <p className="text-zinc-500">Cargando…</p>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {templates.map((t) => (
            <div
              key={t.id}
              className={`rounded-xl border bg-zinc-900/50 p-4 flex flex-col gap-3 transition hover:border-emerald-500/40 ${
                draft?.id === t.id ? "border-emerald-500/60" : "border-zinc-800"
              }`}
            >
              <div className="flex items-center gap-2 min-w-0">
                <span className="font-semibold truncate">{t.name}</span>
                {t.is_builtin && (
                  <span
                    title="Preset de solo lectura"
                    className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wide text-amber-400/90 border border-amber-400/30 rounded px-1.5 py-0.5"
                  >
                    <Lock size={10} /> Preset
                  </span>
                )}
              </div>

              <div className="flex flex-wrap gap-3 text-xs text-zinc-400">
                <span className="inline-flex items-center gap-1">
                  <Type size={12} /> {t.subtitles.font_name} · {t.subtitles.font_size}px
                </span>
                <span className="inline-flex items-center gap-1">
                  <Layout size={12} /> {t.layout.type}
                </span>
              </div>

              <div className="flex items-center gap-2 pt-1">
                <button
                  onClick={() => setDraft(t)}
                  className="inline-flex items-center gap-1 rounded-md border border-zinc-700 px-2.5 py-1.5 text-xs hover:bg-zinc-800 transition"
                >
                  <Pencil size={13} /> {t.is_builtin ? "Ver" : "Editar"}
                </button>
                <button
                  onClick={() => handleClone(t)}
                  className="inline-flex items-center gap-1 rounded-md border border-zinc-700 px-2.5 py-1.5 text-xs hover:bg-zinc-800 transition"
                >
                  <Copy size={13} /> Clonar
                </button>
                <button
                  onClick={() => handleExport(t)}
                  title="Exportar .azt"
                  className="inline-flex items-center gap-1 rounded-md border border-zinc-700 px-2.5 py-1.5 text-xs hover:bg-zinc-800 transition"
                >
                  <Download size={13} />
                </button>
                {!t.is_builtin && (
                  <button
                    onClick={() => handleDelete(t)}
                    className="inline-flex items-center gap-1 rounded-md border border-red-900/50 px-2.5 py-1.5 text-xs text-red-300 hover:bg-red-950/40 transition"
                  >
                    <Trash2 size={13} />
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
