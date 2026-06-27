// Pure snap logic for the Lego layout builder.
// In 9:16 the video blocks stack vertically (full width); the stack is fully
// described by each block's height fraction. Snapping nudges boundaries to nice
// fractions so the user always lands on a layout that renders well.

import type { Region } from "../../lib/api";

export type BlockMode = "active_speaker" | "speaker" | "wide";

export interface LegoBlock {
  mode: BlockMode;
  speaker_ref?: string | null;
  h: number; // height as a fraction of the frame (0..1)
}

// Fractions the builder snaps to (and their complements are implied).
export const NICE_FRACTIONS = [1 / 4, 1 / 3, 1 / 2, 2 / 3, 3 / 4];
const MIN_H = 0.12; // a block never gets thinner than this

/** Snap a value to the nearest nice fraction within tolerance, else return it. */
export function snapFraction(v: number, tol = 0.05): number {
  let best = v;
  let bestD = tol;
  for (const f of NICE_FRACTIONS) {
    const d = Math.abs(v - f);
    if (d < bestD) {
      bestD = d;
      best = f;
    }
  }
  return best;
}

/** Rescale block heights so they sum to exactly 1 (preserving ratios). */
export function normalizeHeights(blocks: LegoBlock[]): LegoBlock[] {
  const total = blocks.reduce((s, b) => s + b.h, 0) || 1;
  return blocks.map((b) => ({ ...b, h: b.h / total }));
}

/** Stacked full-width regions from blocks (y accumulates top→bottom). */
export function blocksToRegions(blocks: LegoBlock[]): Region[] {
  const norm = normalizeHeights(blocks);
  let y = 0;
  return norm.map((b) => {
    const r: Region = {
      x: 0,
      y: Math.round(y * 1e4) / 1e4,
      w: 1,
      h: Math.round(b.h * 1e4) / 1e4,
      source: { mode: b.mode, speaker_ref: b.mode === "speaker" ? b.speaker_ref ?? "Invitado" : null },
    };
    y += b.h;
    return r;
  });
}

/** Recover blocks from a saved regions list (best-effort, assumes a stack). */
export function regionsToBlocks(regions: Region[]): LegoBlock[] {
  return regions.map((r) => ({
    mode: r.source.mode,
    speaker_ref: r.source.speaker_ref ?? undefined,
    h: r.h,
  }));
}

/** Append a block, splitting the largest existing block in two (snapped). */
export function addBlock(blocks: LegoBlock[], mode: BlockMode): LegoBlock[] {
  if (blocks.length === 0) return [{ mode, h: 1 }];
  // take height from the tallest block so the newcomer has room
  let idx = 0;
  blocks.forEach((b, i) => {
    if (b.h > blocks[idx].h) idx = i;
  });
  const half = blocks[idx].h / 2;
  const next = blocks.map((b, i) => (i === idx ? { ...b, h: half } : b));
  next.splice(idx + 1, 0, { mode, speaker_ref: mode === "speaker" ? "Invitado" : undefined, h: half });
  return normalizeHeights(next);
}

/** Remove a block; the freed space is redistributed proportionally. */
export function removeBlock(blocks: LegoBlock[], index: number): LegoBlock[] {
  const next = blocks.filter((_, i) => i !== index);
  return next.length ? normalizeHeights(next) : [{ mode: "active_speaker", h: 1 }];
}

/**
 * Resize the boundary between block `index` and `index+1` to a new absolute
 * cumulative position (0..1), snapping it and respecting the min height.
 */
export function resizeBoundary(blocks: LegoBlock[], index: number, newBoundary: number): LegoBlock[] {
  if (index < 0 || index >= blocks.length - 1) return blocks;
  const norm = normalizeHeights(blocks);
  // cumulative top of block `index`
  let top = 0;
  for (let i = 0; i < index; i++) top += norm[i].h;
  const pairSpan = norm[index].h + norm[index + 1].h;
  // candidate height of the upper block within the pair
  let upper = snapFraction(newBoundary - top);
  upper = Math.max(MIN_H, Math.min(pairSpan - MIN_H, upper));
  const next = norm.map((b, i) =>
    i === index ? { ...b, h: upper } : i === index + 1 ? { ...b, h: pairSpan - upper } : b,
  );
  return next;
}
