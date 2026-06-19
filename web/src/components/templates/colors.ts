// Convert between ASS colors (&HAABBGGRR — alpha, blue, green, red) and CSS.
// In ASS, alpha 00 = opaque, FF = fully transparent.

export function assToCss(ass: string): string {
  const m = /^&H([0-9A-Fa-f]{8})$/.exec(ass);
  if (!m) return "rgba(255,255,255,1)";
  const h = m[1];
  const a = parseInt(h.slice(0, 2), 16);
  const b = parseInt(h.slice(2, 4), 16);
  const g = parseInt(h.slice(4, 6), 16);
  const r = parseInt(h.slice(6, 8), 16);
  const alpha = Math.round((1 - a / 255) * 1000) / 1000;
  return `rgba(${r},${g},${b},${alpha})`;
}

/** Hex "#RRGGBB" → opaque ASS "&H00BBGGRR". */
export function cssToAss(hex: string): string {
  const m = /^#?([0-9A-Fa-f]{6})$/.exec(hex);
  if (!m) return "&H00FFFFFF";
  const h = m[1].toUpperCase();
  const rr = h.slice(0, 2);
  const gg = h.slice(2, 4);
  const bb = h.slice(4, 6);
  return `&H00${bb}${gg}${rr}`;
}

/** ASS "&HAABBGGRR" → hex "#RRGGBB" (drops alpha, for <input type=color>). */
export function assToHex(ass: string): string {
  const m = /^&H([0-9A-Fa-f]{8})$/.exec(ass);
  if (!m) return "#FFFFFF";
  const h = m[1].toUpperCase();
  const bb = h.slice(2, 4);
  const gg = h.slice(4, 6);
  const rr = h.slice(6, 8);
  return `#${rr}${gg}${bb}`;
}
