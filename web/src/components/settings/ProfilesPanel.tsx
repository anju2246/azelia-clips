import React, { useEffect, useState } from "react";
import { Plus, Trash2, Pencil, Check, Cpu } from "lucide-react";
import { Card } from "./ui";
import {
  ProfilesApi,
  type ProfilesList,
  type ClaudeDetectResponse,
  type ProfileInfo,
} from "../../lib/api";

/**
 * Multi-podcast management: create / rename / delete / switch profiles, and
 * pick the Claude Code account (CLAUDE_CONFIG_DIR) per profile — identified by
 * the logged-in email so the user picks "juanpa@…" not a cryptic path.
 */
export const ProfilesPanel: React.FC = () => {
  const [data, setData] = useState<ProfilesList | null>(null);
  const [claude, setClaude] = useState<ClaudeDetectResponse | null>(null);
  const [newName, setNewName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    ProfilesApi.list().then(setData).catch((e) => setError((e as Error).message));
    ProfilesApi.claudeInstallations().then(setClaude).catch(() => {});
  };
  useEffect(() => {
    load();
  }, []);

  const accountLabel = (p: ProfileInfo): string => {
    const acc = claude?.accounts.find(
      (a) => (a.config_dir ?? null) === (p.claude_config_dir ?? null),
    );
    if (acc?.email) return `${acc.email}${acc.plan ? ` · ${acc.plan}` : ""}`;
    return p.claude_config_dir || "Cuenta por defecto";
  };

  const create = async () => {
    if (!newName.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await ProfilesApi.create({ name: newName.trim() });
      setNewName("");
      load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const activate = async (id: string) => {
    setBusy(true);
    setError(null);
    try {
      const res = await ProfilesApi.activate(id);
      if (res.status === "restarting") {
        setTimeout(() => window.location.reload(), 4000);
      } else {
        setBusy(false);
        load();
      }
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };

  const rename = async (p: ProfileInfo) => {
    const name = window.prompt("Nuevo nombre del podcast:", p.name);
    if (!name || name.trim() === p.name) return;
    try {
      await ProfilesApi.update(p.id, { name: name.trim() });
      load();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const remove = async (p: ProfileInfo) => {
    if (p.active) {
      setError("No puedes borrar el perfil activo. Cambia primero.");
      return;
    }
    const wipe = window.confirm(
      `¿Borrar el perfil "${p.name}" y sus datos en disco?\n\nAceptar = borrar también los datos.\nCancelar = no borrar.`,
    );
    if (!wipe) return;
    try {
      await ProfilesApi.remove(p.id, true);
      load();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const setAccount = async (p: ProfileInfo, configDir: string | null) => {
    try {
      await ProfilesApi.update(p.id, { claude_config_dir: configDir });
      load();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <Card
      title="Podcasts (perfiles)"
      description="Cada podcast es un espacio aislado: sus clips, transcripciones y cuenta de Claude no se mezclan. Cambiar de perfil reinicia el servidor."
    >
      {error && (
        <div className="mb-4 px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/30 text-sm text-red-300">
          {error}
        </div>
      )}

      <div className="space-y-3">
        {data?.profiles.map((p) => (
          <div
            key={p.id}
            className="flex flex-col gap-3 p-4 rounded-xl border border-zinc-800 bg-zinc-900/40 md:flex-row md:items-center md:justify-between"
          >
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="font-medium text-zinc-100 truncate">{p.name}</span>
                {p.active && (
                  <span className="px-2 py-0.5 text-[10px] font-bold rounded-full bg-brand-500/20 text-brand-300 border border-brand-500/30">
                    ACTIVO
                  </span>
                )}
              </div>
              <div className="flex items-center gap-1.5 mt-1 text-xs text-zinc-500">
                <Cpu className="h-3 w-3" />
                <span className="truncate">{accountLabel(p)}</span>
              </div>
            </div>

            <div className="flex items-center gap-2 shrink-0">
              <select
                value={p.claude_config_dir ?? ""}
                onChange={(e) => setAccount(p, e.target.value || null)}
                className="bg-zinc-800 border border-zinc-700 rounded-lg px-2 py-1.5 text-xs text-zinc-200 max-w-[200px]"
                title="Cuenta de Claude para este perfil"
              >
                <option value="">Cuenta por defecto</option>
                {claude?.accounts
                  .filter((a) => a.config_dir)
                  .map((a) => (
                    <option key={a.config_dir} value={a.config_dir as string}>
                      {a.email ?? a.config_dir} {a.plan ? `· ${a.plan}` : ""}
                    </option>
                  ))}
              </select>

              {!p.active && (
                <button
                  onClick={() => activate(p.id)}
                  disabled={busy}
                  className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium bg-brand-500/20 text-brand-200 border border-brand-500/30 hover:bg-brand-500/30 disabled:opacity-50"
                >
                  <Check className="h-3.5 w-3.5" /> Usar
                </button>
              )}
              <button
                onClick={() => rename(p)}
                className="p-1.5 rounded-lg text-zinc-400 hover:text-white hover:bg-white/5"
                title="Renombrar"
              >
                <Pencil className="h-4 w-4" />
              </button>
              <button
                onClick={() => remove(p)}
                className="p-1.5 rounded-lg text-zinc-400 hover:text-red-400 hover:bg-white/5"
                title="Borrar"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          </div>
        ))}
      </div>

      <div className="flex items-center gap-2 mt-5">
        <input
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && create()}
          placeholder="Nombre del nuevo podcast"
          className="flex-1 bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 placeholder:text-zinc-600"
        />
        <button
          onClick={create}
          disabled={busy || !newName.trim()}
          className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium bg-brand-500/20 text-brand-200 border border-brand-500/30 hover:bg-brand-500/30 disabled:opacity-50"
        >
          <Plus className="h-4 w-4" /> Crear
        </button>
      </div>
    </Card>
  );
};
