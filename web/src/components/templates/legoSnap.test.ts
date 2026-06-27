// Pure-logic tests for the Lego layout snap math.
// Run via: npx esbuild legoSnap.test.ts --bundle --format=esm --platform=node --outfile=/tmp/lego.test.mjs && node /tmp/lego.test.mjs
import {
  snapFraction,
  normalizeHeights,
  blocksToRegions,
  addBlock,
  removeBlock,
  resizeBoundary,
  type LegoBlock,
} from "./legoSnap";

let failures = 0;
function check(name: string, cond: boolean) {
  if (!cond) {
    failures++;
    console.error(`FAIL: ${name}`);
  } else {
    console.log(`ok: ${name}`);
  }
}
const approx = (a: number, b: number, e = 1e-3) => Math.abs(a - b) < e;

// snapFraction
check("snaps 0.49 → 0.5", approx(snapFraction(0.49), 0.5));
check("snaps 0.34 → 1/3", approx(snapFraction(0.34), 1 / 3));
check("leaves 0.6 alone (no nice within tol)", approx(snapFraction(0.6), 0.6));

// normalizeHeights
const n = normalizeHeights([
  { mode: "speaker", h: 2 },
  { mode: "speaker", h: 2 },
] as LegoBlock[]);
check("normalize sums to 1", approx(n[0].h + n[1].h, 1));
check("normalize keeps ratio (0.5 each)", approx(n[0].h, 0.5));

// blocksToRegions: stacked full-width, cumulative y
const regions = blocksToRegions([
  { mode: "speaker", speaker_ref: "Host", h: 0.5 },
  { mode: "speaker", speaker_ref: "Guest", h: 0.5 },
]);
check("two regions", regions.length === 2);
check("region0 at y=0 h=0.5", approx(regions[0].y, 0) && approx(regions[0].h, 0.5));
check("region1 at y=0.5", approx(regions[1].y, 0.5));
check("full width", regions[0].w === 1 && regions[0].x === 0);
check("speaker_ref preserved", regions[0].source.speaker_ref === "Host");

// wide block clears speaker_ref
const wideRegions = blocksToRegions([{ mode: "wide", h: 1 }]);
check("wide has null speaker_ref", wideRegions[0].source.speaker_ref === null);

// addBlock: splits the tallest
const added = addBlock([{ mode: "active_speaker", h: 1 }], "wide");
check("addBlock → 2 blocks", added.length === 2);
check("addBlock splits 0.5/0.5", approx(added[0].h, 0.5) && approx(added[1].h, 0.5));
check("addBlock appends the new mode", added[1].mode === "wide");

// removeBlock: redistributes
const removed = removeBlock(added, 0);
check("removeBlock → 1 block", removed.length === 1);
check("removeBlock renormalizes to 1", approx(removed[0].h, 1));
check("removeBlock last keeps a default", removeBlock([{ mode: "wide", h: 1 }], 0).length === 1);

// resizeBoundary: snap + min-height clamp
const resized = resizeBoundary(
  [
    { mode: "speaker", h: 0.5 },
    { mode: "speaker", h: 0.5 },
  ],
  0,
  0.32, // drag boundary near 1/3
);
check("resize snaps upper to 1/3", approx(resized[0].h, 1 / 3));
check("resize keeps pair sum", approx(resized[0].h + resized[1].h, 1));
const clamped = resizeBoundary(
  [
    { mode: "speaker", h: 0.5 },
    { mode: "speaker", h: 0.5 },
  ],
  0,
  0.02, // way too small
);
check("resize clamps to min height", clamped[0].h >= 0.12 - 1e-9);

console.log(failures === 0 ? "\nALL PASS" : `\n${failures} FAILURES`);
if (failures) process.exit(1);
