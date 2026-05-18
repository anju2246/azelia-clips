import React, { useEffect, useRef, useState } from "react";
import {
  X,
  ThumbsUp,
  ThumbsDown,
  Loader2,
  BookOpen,
  Check,
  CircleAlert,
} from "lucide-react";
import {
  ClipsApi,
  type CriticDecision,
} from "../../lib/api";
import toast from "react-hot-toast";

interface CriticInsightsModalProps {
  jobId: string;
  onClose: () => void;
}

// Per-rejection draft state. `noteState` drives the inline auto-save
// indicator next to the textarea so the user can see their typing is
// being persisted — there's no separate Save button, the verdict
// buttons + auto-save on note edits is the entire save model.
type NoteSaveState = "idle" | "pending" | "saving" | "saved" | "error";

type DraftMap = Record<
  string,
  {
    verdict: "agree" | "disagree" | "neutral" | null;
    note: string;
    saving: boolean; // verdict button submitting
    noteState: NoteSaveState;
    lastSavedNote: string;
  }
>;

function keyOf(d: CriticDecision): string {
  return `${d.start_time.toFixed(2)}-${d.end_time.toFixed(2)}`;
}

function formatTimestamp(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export const CriticInsightsModal: React.FC<CriticInsightsModalProps> = ({
  jobId,
  onClose,
}) => {
  const [loading, setLoading] = useState(true);
  const [episodeId, setEpisodeId] = useState<string>("");
  const [rejected, setRejected] = useState<CriticDecision[]>([]);
  const [approved, setApproved] = useState<CriticDecision[]>([]);
  const [available, setAvailable] = useState(true);
  const [emptyMessage, setEmptyMessage] = useState<string>("");
  const [drafts, setDrafts] = useState<DraftMap>({});
  const [learnings, setLearnings] = useState<
    Array<{ text: string; category: string | null; evidence_count: number }>
  >([]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [data, learn] = await Promise.all([
          ClipsApi.getCriticDecisions(jobId),
          ClipsApi.getCriticLearnings().catch(() => ({ learnings: [], count: 0 })),
        ]);
        if (cancelled) return;
        setEpisodeId(data.episode_id);
        setAvailable(data.available);
        setApproved(data.approved || []);
        setRejected(data.rejected || []);
        setEmptyMessage(data.message || "");
        setLearnings(learn.learnings || []);

        // Seed drafts from any previously-saved feedback.
        const initial: DraftMap = {};
        for (const d of [...(data.approved || []), ...(data.rejected || [])]) {
          const note = d.user_note || "";
          initial[keyOf(d)] = {
            verdict: d.user_verdict,
            note,
            saving: false,
            noteState: "idle",
            lastSavedNote: note,
          };
        }
        setDrafts(initial);
      } catch (e: any) {
        toast.error(e?.message || "Could not load Critic decisions");
        onClose();
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [jobId]);

  const updateDraft = (key: string, patch: Partial<DraftMap[string]>) => {
    setDrafts((prev) => ({
      ...prev,
      [key]: {
        verdict: null,
        note: "",
        saving: false,
        noteState: "idle",
        lastSavedNote: "",
        ...prev[key],
        ...patch,
      },
    }));
  };

  // Debounce timers per rejection so the auto-save fires once after the
  // user stops typing, not on every keystroke. Stored in a ref so React
  // re-renders don't clobber the timer ids.
  const saveTimers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});

  // Auto-save a note. `note` and `verdict` are captured from the keystroke
  // that scheduled this save, NOT read from React state — that would
  // read stale values when timer fires across renders.
  // Resolution logic:
  //   - empty note → mark idle, do not POST (we don't want neutral rows
  //     with no signal cluttering the table)
  //   - has verdict → POST with that verdict
  //   - no verdict yet → POST as 'neutral' so the note is preserved; the
  //     synthesizer ignores neutral rows, so it's lossless until the user
  //     clicks Agree/Disagree to upgrade it
  const flushSave = async (
    d: CriticDecision,
    note: string,
    verdict: "agree" | "disagree" | "neutral" | null,
  ) => {
    const k = keyOf(d);
    if (!note.trim()) {
      updateDraft(k, { noteState: "idle", lastSavedNote: "" });
      return;
    }
    updateDraft(k, { noteState: "saving" });
    try {
      await ClipsApi.saveCriticFeedback({
        episode_id: episodeId,
        start_time: d.start_time,
        end_time: d.end_time,
        title: d.title,
        summary: d.summary,
        critic_reasoning: d.reasoning,
        user_verdict: (verdict as "agree" | "disagree") || "neutral",
        user_note: note,
      });
      updateDraft(k, { noteState: "saved", lastSavedNote: note });
      // Drop the "Saved ✓" indicator back to idle after a couple of
      // seconds so it doesn't linger as visual noise.
      setTimeout(() => {
        setDrafts((prev) => {
          const cur2 = prev[k];
          if (cur2 && cur2.noteState === "saved") {
            return { ...prev, [k]: { ...cur2, noteState: "idle" } };
          }
          return prev;
        });
      }, 2000);
    } catch {
      updateDraft(k, { noteState: "error" });
    }
  };

  const onNoteChange = (d: CriticDecision, value: string) => {
    const k = keyOf(d);
    const curVerdict = drafts[k]?.verdict ?? null;
    updateDraft(k, { note: value, noteState: "pending" });
    const t = saveTimers.current[k];
    if (t) clearTimeout(t);
    saveTimers.current[k] = setTimeout(
      () => flushSave(d, value, curVerdict),
      1200,
    );
  };

  // Clean up any pending timers on unmount so we don't fire saves after
  // the modal closes.
  useEffect(() => {
    return () => {
      Object.values(saveTimers.current).forEach((t) => clearTimeout(t));
      saveTimers.current = {};
    };
  }, []);

  const submit = async (d: CriticDecision, verdict: "agree" | "disagree") => {
    const k = keyOf(d);
    const note = drafts[k]?.note || "";
    updateDraft(k, { saving: true });
    try {
      await ClipsApi.saveCriticFeedback({
        episode_id: episodeId,
        start_time: d.start_time,
        end_time: d.end_time,
        title: d.title,
        summary: d.summary,
        critic_reasoning: d.reasoning,
        user_verdict: verdict,
        user_note: note,
      });
      updateDraft(k, { verdict, saving: false });
      toast.success(
        verdict === "agree"
          ? "Feedback saved — agreed"
          : "Feedback saved — disagreed",
      );
    } catch (e: any) {
      updateDraft(k, { saving: false });
      toast.error(e?.message || "Could not save feedback");
    }
  };

  return (
    <div className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-zinc-900 border border-zinc-800 rounded-2xl max-w-3xl w-full max-h-[85vh] flex flex-col">
        {/* Header */}
        <div className="flex justify-between items-start p-6 border-b border-zinc-800">
          <div>
            <h2 className="text-xl font-semibold text-white">
              Critic decisions {episodeId && `— ${episodeId}`}
            </h2>
            <p className="text-zinc-400 text-sm mt-1">
              {available
                ? `${approved.length} approved · ${rejected.length} rejected. Leave feedback on each one — your notes are saved and improve future curations.`
                : emptyMessage || "No saved decisions for this job."}
            </p>
          </div>
          <button
            onClick={onClose}
            className="text-zinc-500 hover:text-white transition-colors cursor-pointer"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          {loading ? (
            <div className="flex items-center justify-center py-12 text-zinc-500">
              <Loader2 className="w-5 h-5 animate-spin mr-2" />
              Loading decisions…
            </div>
          ) : (
            <>
              {learnings.length > 0 && (
                <div className="rounded-xl border border-indigo-500/30 bg-indigo-950/20 p-4">
                  <div className="flex items-center gap-2 mb-2">
                    <BookOpen className="w-4 h-4 text-indigo-300" />
                    <h3 className="text-indigo-200 text-sm font-semibold">
                      What the Critic has learned ({learnings.length})
                    </h3>
                  </div>
                  <p className="text-xs text-indigo-200/70 mb-3">
                    Rules distilled from your past notes. Applied on every
                    run.
                  </p>
                  <ul className="space-y-2">
                    {learnings.map((L, i) => (
                      <li
                        key={i}
                        className="text-sm text-indigo-100/90 flex gap-2"
                      >
                        <span className="text-indigo-400/60 font-mono text-xs whitespace-nowrap mt-0.5">
                          [{L.category || "general"}·{L.evidence_count}]
                        </span>
                        <span>{L.text}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          )}
          {!loading && rejected.length === 0 && available && (
            <div className="text-center py-8 text-zinc-400">
              The Critic didn't reject any candidate in this run.
            </div>
          )}
          {!loading && rejected.length > 0 &&
            rejected.map((d) => {
              const k = keyOf(d);
              const draft = drafts[k] || {
                verdict: null,
                note: "",
                saving: false,
              };
              const isAgree = draft.verdict === "agree";
              const isDisagree = draft.verdict === "disagree";
              return (
                <div
                  key={k}
                  className="border border-zinc-800 rounded-xl p-4 bg-zinc-950/40"
                >
                  <div className="flex justify-between items-start gap-3 mb-2">
                    <div className="flex-1 min-w-0">
                      <h3 className="text-white font-medium leading-snug">
                        {d.title || "(no title)"}
                      </h3>
                      {d.summary && (
                        <p className="text-zinc-400 text-sm mt-1">
                          {d.summary}
                        </p>
                      )}
                    </div>
                    <span className="text-xs font-mono text-zinc-500 whitespace-nowrap">
                      {formatTimestamp(d.start_time)}–
                      {formatTimestamp(d.end_time)} · {d.duration.toFixed(0)}s
                    </span>
                  </div>

                  <div className="mt-3 p-3 bg-red-950/20 border border-red-900/40 rounded-lg">
                    <p className="text-red-300 text-xs font-semibold mb-1">
                      Critic's reasoning:
                    </p>
                    <p className="text-red-200/90 text-sm">
                      {d.reasoning || "(no reason provided)"}
                    </p>
                  </div>

                  <div className="mt-3">
                    <textarea
                      value={draft.note}
                      onChange={(e) => onNoteChange(d, e.target.value)}
                      onBlur={() => {
                        // Snap to save immediately on blur so the user
                        // doesn't lose a note by closing the modal in
                        // the 1.2 s debounce window.
                        if (draft.note !== draft.lastSavedNote) {
                          const t = saveTimers.current[k];
                          if (t) clearTimeout(t);
                          flushSave(d, draft.note, draft.verdict);
                        }
                      }}
                      placeholder="Explain why you agree or disagree. Auto-saved as you type — used to improve future curations."
                      rows={2}
                      className="w-full px-3 py-2 bg-black/40 border border-zinc-800 rounded-lg text-sm text-zinc-200 placeholder-zinc-600 focus:border-zinc-600 focus:outline-none resize-none"
                    />
                    <div className="mt-1 flex items-center justify-end h-4 text-xs">
                      {draft.noteState === "pending" && draft.note && (
                        <span className="text-zinc-500">Editing…</span>
                      )}
                      {draft.noteState === "saving" && (
                        <span className="text-zinc-400 flex items-center gap-1">
                          <Loader2 className="w-3 h-3 animate-spin" />
                          Auto-saving…
                        </span>
                      )}
                      {draft.noteState === "saved" && (
                        <span className="text-green-400 flex items-center gap-1">
                          <Check className="w-3 h-3" />
                          Saved
                        </span>
                      )}
                      {draft.noteState === "error" && (
                        <span className="text-red-400 flex items-center gap-1">
                          <CircleAlert className="w-3 h-3" />
                          Could not save — retry by typing again
                        </span>
                      )}
                    </div>
                  </div>

                  <div className="mt-3 flex gap-2">
                    <button
                      disabled={draft.saving}
                      onClick={() => submit(d, "agree")}
                      className={`flex-1 py-2 px-3 rounded-lg text-sm font-medium transition-colors cursor-pointer flex items-center justify-center gap-2 ${
                        isAgree
                          ? "bg-green-600/30 border border-green-500/40 text-green-200"
                          : "bg-zinc-800 hover:bg-green-600/20 hover:text-green-200 text-zinc-300 border border-transparent"
                      }`}
                    >
                      <ThumbsUp className="w-3.5 h-3.5" />
                      {isAgree ? "Agree ✓" : "Agree"}
                    </button>
                    <button
                      disabled={draft.saving}
                      onClick={() => submit(d, "disagree")}
                      className={`flex-1 py-2 px-3 rounded-lg text-sm font-medium transition-colors cursor-pointer flex items-center justify-center gap-2 ${
                        isDisagree
                          ? "bg-amber-600/30 border border-amber-500/40 text-amber-200"
                          : "bg-zinc-800 hover:bg-amber-600/20 hover:text-amber-200 text-zinc-300 border border-transparent"
                      }`}
                    >
                      <ThumbsDown className="w-3.5 h-3.5" />
                      {isDisagree ? "Disagree ✓" : "Disagree"}
                    </button>
                  </div>
                </div>
              );
            })}
        </div>
      </div>
    </div>
  );
};
