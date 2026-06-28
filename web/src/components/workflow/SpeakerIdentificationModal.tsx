import React, { useEffect, useState } from "react";
import {
  X,
  Loader2,
  Mic,
  User,
  SkipForward,
  Minus,
  Plus,
  Users,
  LayoutTemplate,
  Check,
} from "lucide-react";
import { ClipsApi, TemplatesApi, SettingsApi, type ClipTemplate } from "../../lib/api";
import toast from "react-hot-toast";

interface SpeakerIdentificationModalProps {
  episodeNum: number;
  // Pass the chosen template to apply to this episode (profile default if unset).
  onConfirm: (templateId?: string) => void; // start processing
  onClose: () => void;
  // When the episode's speakers are already labeled, show a compact "ready to
  // process" view (just pick the Template + Procesar) instead of the full flow.
  alreadyLabeled?: boolean;
}

interface SpeakerLabel {
  name: string;
  // Multi-select: the user can pick several thumbnails for the SAME
  // person if the embedder split them across "phantom" identities.
  face_ids: string[];
}

export const SpeakerIdentificationModal: React.FC<
  SpeakerIdentificationModalProps
> = ({ episodeNum, onConfirm, onClose, alreadyLabeled = false }) => {
  // Template to apply to this episode (defaults to the profile default).
  const [templates, setTemplates] = useState<ClipTemplate[]>([]);
  const [templateId, setTemplateId] = useState<string | undefined>(undefined);
  useEffect(() => {
    Promise.all([TemplatesApi.list(), SettingsApi.getSettings()])
      .then(([list, s]) => {
        setTemplates(list.templates);
        setTemplateId(s.default_template_id);
      })
      .catch(() => {});
  }, []);

  const TemplatePicker = () => (
    <div className="text-left">
      <label className="mb-2 flex items-center gap-2 text-sm font-medium text-zinc-300">
        <LayoutTemplate className="h-4 w-4" /> Template (estilo + layout)
      </label>
      <select
        value={templateId ?? ""}
        onChange={(e) => setTemplateId(e.target.value)}
        className="w-full rounded-xl border border-zinc-800 bg-black px-4 py-2.5 text-white focus:border-brand-500 focus:outline-none"
      >
        {templates.length === 0 && <option value="">Default del perfil</option>}
        {templates.map((t) => (
          <option key={t.id} value={t.id}>
            {t.name}
            {t.is_builtin ? " (preset)" : ""}
          </option>
        ))}
      </select>
      <p className="mt-1.5 text-xs text-zinc-500">
        Se aplica a los clips de este episodio. Edítalos en{" "}
        <a href="/dashboard/templates" className="text-brand-400 hover:underline">
          Templates
        </a>
        .
      </p>
    </div>
  );

  // Two-step flow:
  //   "count" — ask the user how many speakers their podcast has
  //             (single biggest accuracy lever; bypasses ECAPA auto-detect)
  //   "match" — preflight runs, then user matches faces↔voices
  const [step, setStep] = useState<"count" | "match">("count");
  const [numSpeakers, setNumSpeakers] = useState<number>(2);
  const [loading, setLoading] = useState(false);
  const [faces, setFaces] = useState<string[]>([]);
  const [speakers, setSpeakers] = useState<string[]>([]);
  const [labels, setLabels] = useState<Record<string, SpeakerLabel>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Compact path: speakers already identified → just pick template + Procesar.
  // (After all hooks are declared, to respect the Rules of Hooks.)
  if (alreadyLabeled) {
    return (
      <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm">
        <div className="w-full max-w-md rounded-2xl border border-zinc-800 bg-zinc-900 p-6">
          <div className="mb-4 flex items-start justify-between">
            <div>
              <h2 className="text-xl font-semibold text-white">
                Procesar EP{String(episodeNum).padStart(3, "0")}
              </h2>
              <p className="mt-1 inline-flex items-center gap-1.5 text-sm text-emerald-400">
                <Check className="h-4 w-4" /> Hablantes ya identificados
              </p>
            </div>
            <button onClick={onClose} className="text-zinc-500 hover:text-white">
              <X className="h-5 w-5" />
            </button>
          </div>
          {TemplatePicker()}
          <div className="mt-6 flex justify-end gap-2">
            <button
              onClick={onClose}
              className="rounded-xl border border-zinc-700 px-4 py-2.5 text-sm text-zinc-300 hover:bg-zinc-800"
            >
              Cancelar
            </button>
            <button
              onClick={() => onConfirm(templateId)}
              className="rounded-xl bg-brand-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-brand-500"
            >
              Procesar
            </button>
          </div>
        </div>
      </div>
    );
  }

  // Fire the preflight only after the user confirms the speaker count.
  const startPreflight = async () => {
    setStep("match");
    setLoading(true);
    setError(null);
    try {
      const data = await ClipsApi.identifyPrepare(episodeNum, numSpeakers);
      setFaces(data.faces);
      setSpeakers(data.speakers);
      // Seed from existing labels if any. Tolerate both new schema
      // (face_ids array) and legacy schema (single face_id).
      const seed: Record<string, SpeakerLabel> = {};
      for (const spk of data.speakers) {
        const prior = data.existing_labels?.[spk];
        let face_ids: string[] = [];
        if (prior?.face_ids?.length) face_ids = prior.face_ids;
        else if (prior?.face_id) face_ids = [prior.face_id];
        seed[spk] = { name: prior?.name || "", face_ids };
      }
      setLabels(seed);
    } catch (e: any) {
      setError(e?.message || "Preflight failed");
    } finally {
      setLoading(false);
    }
  };

  const updateLabel = (speakerId: string, patch: Partial<SpeakerLabel>) => {
    setLabels((prev) => ({
      ...prev,
      [speakerId]: { ...prev[speakerId], ...patch },
    }));
  };

  // Toggle a face thumbnail for a speaker. Clicking an unselected face
  // adds it to that speaker's set; clicking a selected face removes it.
  // Multi-select: same person split across thumbnails (phantoms) can be
  // grouped under one speaker.
  const toggleFace = (speakerId: string, faceId: string) => {
    setLabels((prev) => {
      const cur = prev[speakerId] || { name: "", face_ids: [] };
      const has = cur.face_ids.includes(faceId);
      const next = has
        ? cur.face_ids.filter((f) => f !== faceId)
        : [...cur.face_ids, faceId];
      return { ...prev, [speakerId]: { ...cur, face_ids: next } };
    });
  };

  const canSubmit = speakers.every(
    (s) =>
      (labels[s]?.name?.trim() || "").length > 0 &&
      (labels[s]?.face_ids?.length || 0) > 0,
  );

  const handleConfirm = async () => {
    if (!canSubmit) return;
    setSaving(true);
    try {
      const payload: Record<string, { name: string; face_ids: string[] }> = {};
      for (const s of speakers) {
        payload[s] = {
          name: labels[s].name.trim(),
          face_ids: labels[s].face_ids,
        };
      }
      await ClipsApi.identifySaveLabels(episodeNum, { labels: payload });
      toast.success("Speakers identified — starting processing");
      onConfirm(templateId);
    } catch (e: any) {
      toast.error(e?.message || "Could not save labels");
    } finally {
      setSaving(false);
    }
  };

  const handleSkip = async () => {
    setSaving(true);
    try {
      await ClipsApi.identifySaveLabels(episodeNum, { skipped: true });
      toast("Skipped — using auto detection", { icon: "⏭" });
      onConfirm(templateId);
    } catch (e: any) {
      toast.error(e?.message || "Could not skip");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/75 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-zinc-900 border border-zinc-800 rounded-2xl max-w-3xl w-full max-h-[90vh] flex flex-col">
        <div className="flex justify-between items-start p-6 border-b border-zinc-800">
          <div>
            <h2 className="text-xl font-semibold text-white">
              {step === "count"
                ? `How many speakers? — EP${String(episodeNum).padStart(3, "0")}`
                : `Identify speakers — EP${String(episodeNum).padStart(3, "0")}`}
            </h2>
            <p className="text-zinc-400 text-sm mt-1">
              {step === "count"
                ? "Telling us the exact count up front makes the diarization way more accurate — we skip auto-detection entirely and pin the model to your number."
                : "Listen to each voice, look at the detected faces, and match them. The result is saved and used across the whole episode. Skip to fall back to automatic detection."}
            </p>
          </div>
          <button
            onClick={onClose}
            className="text-zinc-500 hover:text-white cursor-pointer"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-6">
          {step === "count" ? (
            <div className="flex flex-col items-center py-8 gap-6">
              <Users className="w-10 h-10 text-brand-400" />
              <p className="text-zinc-300 text-sm text-center max-w-md">
                How many distinct speakers does this episode have? Include
                the host. Most interview podcasts are 2; panels can be 3–5.
              </p>
              <div className="flex items-center gap-4 bg-zinc-950/60 border border-zinc-800 rounded-2xl px-3 py-2">
                <button
                  onClick={() =>
                    setNumSpeakers((n) => Math.max(1, n - 1))
                  }
                  disabled={numSpeakers <= 1}
                  className={`p-2 rounded-lg transition-colors cursor-pointer ${
                    numSpeakers <= 1
                      ? "text-zinc-700 cursor-not-allowed"
                      : "text-zinc-300 hover:bg-zinc-800 hover:text-white"
                  }`}
                  aria-label="Decrement"
                >
                  <Minus className="w-5 h-5" />
                </button>
                <span className="text-4xl font-mono font-semibold text-white tabular-nums w-16 text-center">
                  {numSpeakers}
                </span>
                <button
                  onClick={() =>
                    setNumSpeakers((n) => Math.min(8, n + 1))
                  }
                  disabled={numSpeakers >= 8}
                  className={`p-2 rounded-lg transition-colors cursor-pointer ${
                    numSpeakers >= 8
                      ? "text-zinc-700 cursor-not-allowed"
                      : "text-zinc-300 hover:bg-zinc-800 hover:text-white"
                  }`}
                  aria-label="Increment"
                >
                  <Plus className="w-5 h-5" />
                </button>
              </div>
              <p className="text-xs text-zinc-600">
                Capped at 8 — beyond that the per-clip matching gets noisy
                anyway.
              </p>
              <div className="w-full max-w-md border-t border-zinc-800 pt-6">
                {TemplatePicker()}
              </div>
            </div>
          ) : loading ? (
            <div className="flex flex-col items-center justify-center py-12 gap-3">
              <Loader2 className="w-8 h-8 text-brand-400 animate-spin" />
              <p className="text-zinc-400">
                Detecting faces and extracting voice samples…
              </p>
              <p className="text-zinc-600 text-xs">
                ~30-45 s. One-time setup per episode.
              </p>
            </div>
          ) : error ? (
            <div className="p-4 bg-red-950/30 border border-red-900/50 rounded-xl">
              <p className="text-red-300 text-sm">{error}</p>
            </div>
          ) : speakers.length === 0 || faces.length === 0 ? (
            <div className="text-center py-8 text-zinc-400">
              Not enough speakers or faces were detected. You can skip
              this step and process with automatic detection.
            </div>
          ) : (
            <div className="space-y-5">
              {speakers.map((spk) => (
                <div
                  key={spk}
                  className="border border-zinc-800 rounded-xl p-4 bg-zinc-950/40"
                >
                  <div className="flex items-center gap-2 mb-3">
                    <Mic className="w-4 h-4 text-brand-400" />
                    <span className="text-xs font-mono text-zinc-500">
                      {spk}
                    </span>
                  </div>

                  <audio
                    controls
                    preload="metadata"
                    src={ClipsApi.identifyAudioUrl(episodeNum, spk)}
                    className="w-full mb-4"
                  />

                  <div className="flex items-center gap-2 mb-2">
                    <User className="w-4 h-4 text-zinc-500" />
                    <input
                      type="text"
                      placeholder="Speaker name (e.g. Juan Pablo)"
                      value={labels[spk]?.name || ""}
                      onChange={(e) =>
                        updateLabel(spk, { name: e.target.value })
                      }
                      className="flex-1 px-3 py-2 bg-black/40 border border-zinc-800 rounded-lg text-sm text-zinc-100 placeholder-zinc-600 focus:border-zinc-600 focus:outline-none"
                    />
                  </div>

                  <p className="text-xs text-zinc-500 mb-2">
                    Pick every face that matches this voice. If the same
                    person shows up split into multiple thumbnails (e.g.
                    different angle/lighting), select all of them — they
                    get treated as one identity.
                  </p>
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                    {faces.map((fid) => {
                      const selected = (labels[spk]?.face_ids || []).includes(
                        fid,
                      );
                      return (
                        <button
                          key={fid}
                          onClick={() => toggleFace(spk, fid)}
                          className={`rounded-lg overflow-hidden border-2 transition-all cursor-pointer ${
                            selected
                              ? "border-brand-500 ring-2 ring-brand-500/30"
                              : "border-zinc-800 hover:border-zinc-600"
                          }`}
                        >
                          <img
                            src={ClipsApi.identifyFaceUrl(episodeNum, fid)}
                            alt={fid}
                            className="w-full h-32 object-cover bg-zinc-950"
                          />
                          <div className="text-xs font-mono text-zinc-500 py-1 px-2 bg-black/40">
                            {fid}
                            {selected && (
                              <span className="text-brand-400 ml-1">✓</span>
                            )}
                          </div>
                        </button>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="flex items-center justify-between gap-3 p-4 border-t border-zinc-800">
          <button
            onClick={handleSkip}
            disabled={saving}
            className="flex items-center gap-2 px-4 py-2 text-sm text-zinc-400 hover:text-zinc-200 rounded-lg transition-colors cursor-pointer"
          >
            <SkipForward className="w-4 h-4" />
            Skip — use auto detection
          </button>
          {step === "count" ? (
            <button
              onClick={startPreflight}
              disabled={saving}
              className="px-5 py-2 rounded-xl text-sm font-medium bg-brand-600 hover:bg-brand-500 text-white transition-colors cursor-pointer flex items-center gap-2"
            >
              Continue — detect {numSpeakers} speaker
              {numSpeakers === 1 ? "" : "s"}
            </button>
          ) : (
            <button
              onClick={handleConfirm}
              disabled={!canSubmit || saving}
              className={`px-5 py-2 rounded-xl text-sm font-medium transition-colors cursor-pointer flex items-center gap-2 ${
                canSubmit && !saving
                  ? "bg-brand-600 hover:bg-brand-500 text-white"
                  : "bg-zinc-800 text-zinc-500 cursor-not-allowed"
              }`}
            >
              {saving && <Loader2 className="w-4 h-4 animate-spin" />}
              Save & process
            </button>
          )}
        </div>
      </div>
    </div>
  );
};
