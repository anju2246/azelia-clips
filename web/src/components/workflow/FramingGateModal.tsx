import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  Loader2,
  X,
  Crop,
  AlertTriangle,
  ChevronUp,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  RotateCcw,
} from "lucide-react";
import toast from "react-hot-toast";
import { ClipsApi, type FramingResponse } from "../../lib/api";

interface FramingGateModalProps {
  jobId: string;
  onClose: () => void;
  onConfirmed: () => void;
}

/**
 * Pre-render stop for single-shot templates: the close-up crop IS the whole
 * frame, so its tightness gets decided per episode — a roomy set deserves a
 * looser crop than a tight one — against a real still before committing to a
 * full render.
 */
export const FramingGateModal: React.FC<FramingGateModalProps> = ({
  jobId,
  onClose,
  onConfirmed,
}) => {
  const [framing, setFraming] = useState<FramingResponse | null>(null);
  const [mult, setMult] = useState<number | null>(null);
  const [offset, setOffset] = useState<{ x: number; y: number }>({ x: 0, y: 0 });
  const [error, setError] = useState<string | null>(null);
  const [previewSrc, setPreviewSrc] = useState<string | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [confirming, setConfirming] = useState(false);

  // Guards a slow preview from overwriting a newer one when the user keeps
  // moving the slider.
  const previewSeq = useRef(0);

  useEffect(() => {
    let cancelled = false;
    ClipsApi.getFraming(jobId)
      .then((f) => {
        if (cancelled) return;
        setFraming(f);
        setMult(f.safe_zone_mult);
        setOffset({ x: f.offset_x ?? 0, y: f.offset_y ?? 0 });
      })
      .catch((e) => !cancelled && setError((e as Error).message));
    return () => {
      cancelled = true;
    };
  }, [jobId]);

  const loadPreview = useCallback(
    (value: number, off: { x: number; y: number }) => {
      const seq = ++previewSeq.current;
      setPreviewLoading(true);
      const img = new Image();
      img.src = ClipsApi.framingPreviewUrl(jobId, value, off.x, off.y);
      img.onload = () => {
        if (seq !== previewSeq.current) return; // a newer request won
        setPreviewSrc(img.src);
        setPreviewLoading(false);
      };
      img.onerror = () => {
        if (seq !== previewSeq.current) return;
        setPreviewLoading(false);
        setError("No se pudo generar el preview del encuadre.");
      };
    },
    [jobId],
  );

  // First preview once we know the starting value.
  useEffect(() => {
    if (mult != null && previewSrc == null && !previewLoading && !error) {
      loadPreview(mult, offset);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mult]);

  /** Nudge the crop and refresh the still. Cached faces → the reload is instant. */
  const nudge = (dx: number, dy: number) => {
    if (mult == null || !framing) return;
    const cap = framing.max_offset ?? 0.5;
    const clamp = (v: number) => Math.max(-cap, Math.min(v, cap));
    const next = {
      x: parseFloat(clamp(offset.x + dx).toFixed(2)),
      y: parseFloat(clamp(offset.y + dy).toFixed(2)),
    };
    setOffset(next);
    loadPreview(mult, next);
  };

  const resetOffset = () => {
    if (mult == null) return;
    const zero = { x: 0, y: 0 };
    setOffset(zero);
    loadPreview(mult, zero);
  };

  const handleConfirm = async () => {
    if (mult == null || confirming) return; // guard double-submit
    setConfirming(true);
    try {
      await ClipsApi.confirmFraming(jobId, mult, offset.x, offset.y);
      onConfirmed();
    } catch (e) {
      toast.error((e as Error).message);
      setConfirming(false);
    }
  };

  const presets = framing?.presets ?? [];
  const count = framing?.approved_count ?? 0;

  return (
    <div className="fixed inset-0 bg-black/75 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-zinc-900 border border-zinc-800 rounded-2xl max-w-3xl w-full max-h-[92vh] flex flex-col">
        {/* Header */}
        <div className="flex items-start justify-between gap-4 px-5 pt-5">
          <div>
            <h2 className="text-lg font-semibold text-white flex items-center gap-2">
              <Crop className="w-4.5 h-4.5 text-brand-400" />
              Revisa el encuadre
            </h2>
            <p className="text-sm text-zinc-400 mt-0.5">
              {framing
                ? `Este template usa un solo plano, así que el recorte llena todo el cuadro. Ajústalo para ${framing.episode_id} antes de renderizar.`
                : "Cargando encuadre…"}
            </p>
          </div>
          <button
            onClick={onClose}
            className="text-zinc-400 hover:text-white transition-colors"
            aria-label="Cerrar"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {error ? (
          <div className="m-6 p-4 bg-red-950/30 border border-red-900/50 rounded-xl text-sm text-red-300 flex items-start gap-2">
            <AlertTriangle className="w-4 h-4 mt-0.5 flex-shrink-0" />
            <span>{error}</span>
          </div>
        ) : !framing || mult == null ? (
          <div className="flex-1 flex items-center justify-center p-12">
            <Loader2 className="w-6 h-6 animate-spin text-zinc-500" />
          </div>
        ) : (
          <div className="flex-1 overflow-y-auto p-5 flex flex-col sm:flex-row gap-5">
            {/* Preview */}
            <div className="sm:w-56 flex-shrink-0">
              <div className="relative aspect-[9/16] rounded-xl overflow-hidden bg-zinc-950 border border-zinc-800">
                {previewSrc && (
                  <img
                    src={previewSrc}
                    alt="Encuadre propuesto"
                    className="w-full h-full object-cover"
                  />
                )}
                {previewLoading && (
                  <div className="absolute inset-0 flex items-center justify-center bg-zinc-950/60">
                    <Loader2 className="w-5 h-5 animate-spin text-zinc-400" />
                  </div>
                )}
              </div>
              <p className="text-[11px] text-zinc-500 mt-2 text-center">
                Cuadro real del primer clip aprobado
              </p>
            </div>

            {/* Controls */}
            <div className="flex-1 flex flex-col gap-4">
              <div>
                <p className="text-xs uppercase tracking-wide text-zinc-500 mb-2">
                  Encuadre
                </p>
                <div className="grid grid-cols-2 gap-2">
                  {presets.map((p) => {
                    const active = Math.abs(p.mult - mult) < 0.01;
                    return (
                      <button
                        key={p.id}
                        onClick={() => {
                          setMult(p.mult);
                          loadPreview(p.mult, offset);
                        }}
                        className={`rounded-xl border p-3 text-left transition-colors ${
                          active
                            ? "border-brand-600/50 bg-brand-600/10"
                            : "border-zinc-800 bg-zinc-950/40 hover:bg-zinc-800/40"
                        }`}
                      >
                        <span
                          className={`block text-sm font-medium ${
                            active ? "text-white" : "text-zinc-300"
                          }`}
                        >
                          {p.label}
                        </span>
                        <span className="block text-[11px] text-zinc-500">
                          {p.hint}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>

              <div>
                <div className="flex items-center justify-between mb-1.5">
                  <label
                    htmlFor="framing-slider"
                    className="text-xs uppercase tracking-wide text-zinc-500"
                  >
                    Ajuste fino
                  </label>
                  <span className="text-xs text-zinc-400 tabular-nums">
                    {mult.toFixed(1)}×
                  </span>
                </div>
                <input
                  id="framing-slider"
                  type="range"
                  min={framing.min}
                  max={framing.max}
                  step={0.1}
                  value={mult}
                  onChange={(e) => setMult(parseFloat(e.target.value))}
                  onMouseUp={() => loadPreview(mult, offset)}
                  onTouchEnd={() => loadPreview(mult, offset)}
                  onKeyUp={() => loadPreview(mult, offset)}
                  className="w-full accent-brand-500"
                />
                <div className="flex justify-between text-[11px] text-zinc-600 mt-1">
                  <span>Más cerrado</span>
                  <span>Se ve más del set</span>
                </div>
              </div>

              <div>
                <div className="flex items-center justify-between mb-1.5">
                  <p className="text-xs uppercase tracking-wide text-zinc-500">
                    Posición
                  </p>
                  {(offset.x !== 0 || offset.y !== 0) && (
                    <button
                      onClick={resetOffset}
                      className="text-[11px] text-zinc-500 hover:text-zinc-300 flex items-center gap-1 transition-colors"
                    >
                      <RotateCcw className="w-3 h-3" />
                      Centrar
                    </button>
                  )}
                </div>
                <div className="flex items-center gap-3">
                  <div className="grid grid-cols-3 grid-rows-3 gap-1 w-[92px]">
                    <span />
                    <button
                      onClick={() => nudge(0, -0.05)}
                      className="h-7 rounded-lg bg-zinc-950/60 border border-zinc-800 hover:bg-zinc-800 flex items-center justify-center text-zinc-300 transition-colors"
                      aria-label="Subir el encuadre"
                    >
                      <ChevronUp className="w-4 h-4" />
                    </button>
                    <span />
                    <button
                      onClick={() => nudge(-0.05, 0)}
                      className="h-7 rounded-lg bg-zinc-950/60 border border-zinc-800 hover:bg-zinc-800 flex items-center justify-center text-zinc-300 transition-colors"
                      aria-label="Mover el encuadre a la izquierda"
                    >
                      <ChevronLeft className="w-4 h-4" />
                    </button>
                    <span className="h-7 rounded-lg border border-dashed border-zinc-800" />
                    <button
                      onClick={() => nudge(0.05, 0)}
                      className="h-7 rounded-lg bg-zinc-950/60 border border-zinc-800 hover:bg-zinc-800 flex items-center justify-center text-zinc-300 transition-colors"
                      aria-label="Mover el encuadre a la derecha"
                    >
                      <ChevronRight className="w-4 h-4" />
                    </button>
                    <span />
                    <button
                      onClick={() => nudge(0, 0.05)}
                      className="h-7 rounded-lg bg-zinc-950/60 border border-zinc-800 hover:bg-zinc-800 flex items-center justify-center text-zinc-300 transition-colors"
                      aria-label="Bajar el encuadre"
                    >
                      <ChevronDown className="w-4 h-4" />
                    </button>
                    <span />
                  </div>
                  <p className="text-[11px] text-zinc-500 leading-relaxed flex-1">
                    Corre el recorte sin cambiar el zoom.{" "}
                    {offset.x === 0 && offset.y === 0 ? (
                      "Centrado en la cara detectada."
                    ) : (
                      <span className="text-zinc-400 tabular-nums">
                        Desplazado {Math.round(offset.x * 100)}% en X,{" "}
                        {Math.round(offset.y * 100)}% en Y.
                      </span>
                    )}
                  </p>
                </div>
              </div>

              <p className="text-[11px] text-zinc-500 leading-relaxed">
                El recorte mide {mult.toFixed(1)} veces la altura de la cara
                detectada. Aplica a los {count}{" "}
                {count === 1 ? "clip aprobado" : "clips aprobados"} de este
                episodio; no cambia tu template.
              </p>
            </div>
          </div>
        )}

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 border-t border-zinc-800 px-5 py-4">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-xl text-sm text-zinc-400 hover:text-white transition-colors"
          >
            Cancelar
          </button>
          <button
            onClick={handleConfirm}
            disabled={confirming || mult == null || !!error}
            className="px-4 py-2 rounded-xl bg-brand-600 hover:bg-brand-500 disabled:opacity-50 text-sm font-medium text-white transition-colors flex items-center gap-2"
          >
            {confirming && <Loader2 className="w-4 h-4 animate-spin" />}
            {count > 0
              ? `Renderizar ${count} ${count === 1 ? "clip" : "clips"}`
              : "Renderizar"}
          </button>
        </div>
      </div>
    </div>
  );
};
