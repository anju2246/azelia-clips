import React, { useEffect, useState } from "react";
import toast from "react-hot-toast";
import { Copy, Trash2, Lock, Plus, Layout, Type } from "lucide-react";
import { TemplatesApi, type ClipTemplate } from "../../lib/api";

/**
 * Full-page Templates view — list/create/clone/delete of clip templates.
 * The field editor + live preview land in a later slice (T4); this slice makes
 * templates visible and manageable. Built-ins are read-only and only clonable.
 */
export const TemplatesView: React.FC = () => {
  const [templates, setTemplates] = useState<ClipTemplate[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = () =>
    TemplatesApi.list()
      .then((r) => setTemplates(r.templates))
      .catch((e) => toast.error(e.message))
      .finally(() => setLoading(false));

  useEffect(() => {
    refresh();
  }, []);

  const handleCreate = async () => {
    const name = window.prompt("Nombre del nuevo template:");
    if (!name?.trim()) return;
    try {
      await TemplatesApi.create({ name: name.trim() });
      toast.success("Template creado");
      refresh();
    } catch (e) {
      toast.error((e as Error).message);
    }
  };

  const handleClone = async (t: ClipTemplate) => {
    const name = window.prompt("Nombre de la copia:", `${t.name} (copia)`);
    if (!name?.trim()) return;
    try {
      await TemplatesApi.clone(t.id, name.trim());
      toast.success("Template clonado");
      refresh();
    } catch (e) {
      toast.error((e as Error).message);
    }
  };

  const handleDelete = async (t: ClipTemplate) => {
    if (!window.confirm(`¿Borrar "${t.name}"? No se puede deshacer.`)) return;
    try {
      await TemplatesApi.remove(t.id);
      toast.success("Template borrado");
      refresh();
    } catch (e) {
      toast.error((e as Error).message);
    }
  };

  return (
    <div className="max-w-4xl mx-auto pb-12">
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
        <button
          onClick={handleCreate}
          className="shrink-0 inline-flex items-center gap-2 rounded-lg bg-white px-4 py-2 text-sm font-semibold text-black hover:bg-zinc-200 transition"
        >
          <Plus size={16} /> Nuevo
        </button>
      </div>

      {loading ? (
        <p className="text-zinc-500">Cargando…</p>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {templates.map((t) => (
            <div
              key={t.id}
              className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-4 flex flex-col gap-3"
            >
              <div className="flex items-center justify-between gap-2">
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
              </div>

              <div className="flex flex-wrap gap-3 text-xs text-zinc-400">
                <span className="inline-flex items-center gap-1">
                  <Type size={12} /> {t.subtitles.font_name} · {t.subtitles.font_size}px
                </span>
                <span className="inline-flex items-center gap-1">
                  <Layout size={12} /> {t.layout.type}
                </span>
                <span className="inline-flex items-center gap-1">
                  {t.subtitles.animation}
                </span>
              </div>

              <div className="flex items-center gap-2 pt-1">
                <button
                  onClick={() => handleClone(t)}
                  className="inline-flex items-center gap-1 rounded-md border border-zinc-700 px-2.5 py-1.5 text-xs hover:bg-zinc-800 transition"
                >
                  <Copy size={13} /> Clonar
                </button>
                {!t.is_builtin && (
                  <button
                    onClick={() => handleDelete(t)}
                    className="inline-flex items-center gap-1 rounded-md border border-red-900/50 px-2.5 py-1.5 text-xs text-red-300 hover:bg-red-950/40 transition"
                  >
                    <Trash2 size={13} /> Borrar
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
