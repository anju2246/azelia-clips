// Pure geometry for the interactive template preview. Kept free of React/DOM so
// it can be unit-tested. All coordinates are in the target 1080×1920 space.

export interface Box {
  width: number;
  height: number;
}

export interface SubtitlePlacement {
  alignment: number; // ASS numpad 1-9
  margin_v: number; // vertical margin in target px (0 for middle row)
}

export const WIDE_RATIO_MIN = 0.2;
export const WIDE_RATIO_MAX = 0.5;

// ASS numpad alignment per (row, col). Row 0 = top, 2 = bottom.
const ALIGNMENT_GRID = [
  [7, 8, 9], // top
  [4, 5, 6], // middle
  [1, 2, 3], // bottom
];

/**
 * Snap a dragged point to the nearest of the 9 ASS anchors and derive the
 * vertical margin. Bottom anchors measure margin from the bottom edge, top
 * anchors from the top, middle anchors are centered (margin_v = 0).
 */
export function pointToAlignment(x: number, y: number, box: Box): SubtitlePlacement {
  const col = Math.min(2, Math.max(0, Math.floor((x / box.width) * 3)));
  const row = Math.min(2, Math.max(0, Math.floor((y / box.height) * 3)));
  const alignment = ALIGNMENT_GRID[row][col];

  let margin_v = 0;
  if (row === 2) {
    margin_v = Math.round(box.height - y); // distance from bottom
  } else if (row === 0) {
    margin_v = Math.round(y); // distance from top
  }
  margin_v = Math.max(0, Math.min(box.height, margin_v));
  return { alignment, margin_v };
}

/**
 * Convert a split-divider Y position into a wide_height_ratio (the wide shot is
 * the region below the divider), clamped to the valid range.
 */
export function ratioFromDivider(y: number, height: number): number {
  const ratio = (height - y) / height;
  return Math.min(WIDE_RATIO_MAX, Math.max(WIDE_RATIO_MIN, ratio));
}
