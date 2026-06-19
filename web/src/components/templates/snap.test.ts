// Pure-logic tests for the preview snap math.
// Run via: npx esbuild snap.test.ts --bundle --format=esm --platform=node --outfile=/tmp/snap.test.mjs && node /tmp/snap.test.mjs
import { pointToAlignment, ratioFromDivider } from "./snap";
import { assToCss, cssToAss, assToHex } from "./colors";

let failures = 0;
function check(name: string, cond: boolean) {
  if (!cond) {
    failures++;
    console.error(`FAIL: ${name}`);
  } else {
    console.log(`ok: ${name}`);
  }
}

const BOX = { width: 1080, height: 1920 };

// ── pointToAlignment: nine zones ────────────────────────────────────────────
check(
  "bottom-center → alignment 2",
  pointToAlignment(540, 1900, BOX).alignment === 2,
);
check(
  "bottom-center margin_v ≈ distance from bottom (20)",
  pointToAlignment(540, 1900, BOX).margin_v === 20,
);
check("top-left → alignment 7", pointToAlignment(50, 30, BOX).alignment === 7);
check(
  "top-left margin_v = distance from top (30)",
  pointToAlignment(50, 30, BOX).margin_v === 30,
);
check(
  "middle-center → alignment 5",
  pointToAlignment(540, 960, BOX).alignment === 5,
);
check(
  "middle margin_v = 0 (centered)",
  pointToAlignment(540, 960, BOX).margin_v === 0,
);
check(
  "bottom-right → alignment 3",
  pointToAlignment(1000, 1850, BOX).alignment === 3,
);
check(
  "top-right → alignment 9",
  pointToAlignment(1000, 30, BOX).alignment === 9,
);
check(
  "margin_v never negative",
  pointToAlignment(540, 1920, BOX).margin_v >= 0,
);

// ── ratioFromDivider: clamp [0.20, 0.50] ────────────────────────────────────
check(
  "divider at 1152 → ratio ≈ 0.40",
  Math.abs(ratioFromDivider(1152, 1920) - 0.4) < 0.01,
);
check("divider at top clamps to 0.50", ratioFromDivider(0, 1920) === 0.5);
check("divider at bottom clamps to 0.20", ratioFromDivider(1920, 1920) === 0.2);

// ── colors: ASS ↔ CSS ───────────────────────────────────────────────────────
check("assToCss opaque white", assToCss("&H00FFFFFF") === "rgba(255,255,255,1)");
check(
  "assToCss semi-transparent black ≈ 0.5",
  Math.abs(parseFloat(assToCss("&H80000000").split(",")[3]) - 0.498) < 0.01,
);
check("cssToAss red → &H000000FF", cssToAss("#FF0000") === "&H000000FF");
check("assToHex roundtrips red", assToHex("&H000000FF") === "#FF0000");

if (failures > 0) {
  console.error(`\n${failures} failure(s)`);
  process.exit(1);
}
console.log("\nall snap tests passed");
