"""
Real-world validation (Phase 5) for the brief text-trim feature.

Exercises the REAL deterministic applier against a word-level transcript fixture
(`fixtures/brief_transcript.json`) — no LLM, no mocks of the matcher — covering
the five observable "good result" cases from goal.md, and writes inspectable
evidence to out/brief_realworld/.

Run: ./venv/bin/python -m pytest tests/test_brief_realworld.py -x
"""
import json
import re
from pathlib import Path

import pytest

from packages.clips.transcription.transcriber import Transcript
from packages.clips.curation.brief_models import BriefAction, BriefCandidate, BriefSession
from packages.clips.curation.brief_actions import apply, BriefContext

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "brief_transcript.json"
OUT_DIR = Path(__file__).resolve().parents[1] / "out" / "brief_realworld"

# Evidence accumulated across cases, flushed at the end of the module run.
_EVIDENCE: list = []


@pytest.fixture(scope="module")
def transcript():
    return Transcript.load(FIXTURE)


@pytest.fixture(scope="module")
def words_flat(transcript):
    """Flat (word, start, end) list — mirrors the server's word-level provider."""
    out = []
    for seg in transcript.segments:
        for w in seg.words:
            out.append((w.word, float(w.start), float(w.end)))
    return out


def _words_provider(transcript):
    """Same shape as server/routes/clips.py: timed words overlapping [ws,we]."""
    def provider(ws, we):
        out = []
        for seg in transcript.segments:
            for w in seg.words:
                if w.end >= ws and w.start <= we:
                    out.append((w.word, float(w.start), float(w.end)))
        return out
    return provider


def _true_span(words_flat, phrase, occurrence=0):
    """Independent EXACT token search → ground-truth (start,end) for the nth match."""
    q = re.findall(r"\w+", phrase.lower())
    wt = [re.findall(r"\w+", w.lower())[0] for (w, _, _) in words_flat]
    hits = []
    for i in range(len(wt) - len(q) + 1):
        if wt[i:i + len(q)] == q:
            hits.append((words_flat[i][1], words_flat[i + len(q) - 1][2]))
    return hits[occurrence] if occurrence < len(hits) else None


def _ctx(transcript):
    return BriefContext(
        episode_duration=float(transcript.duration),
        words_provider=_words_provider(transcript),
    )


def _session(window):
    a, b = window
    return BriefSession(
        job_id="job_rw", episode_id="EP_RW", status="open",
        candidates=[BriefCandidate(
            id=1, start_time=float(a), end_time=float(b), title="Clip RW",
            summary="s", reasoning="", score=80.0, critic_approved=True,
            above_threshold=True, selected=True, origin="curation",
            transcript="(se reconstruye)",
        )],
        messages=[], created_at="t", updated_at="t",
    )


def _trim(transcript, window, keep_text):
    session, ctx = _session(window), _ctx(transcript)
    res = apply(session, BriefAction(type="trim_to_text", id=1, keep_text=keep_text), ctx)
    c = session.candidates[0]
    return res, (c.start_time, c.end_time)


def _record(case, **kw):
    _EVIDENCE.append({"case": case, **kw})


# ── Case 1: pasted exactly, internal to the clip ─────────────────────────────

def test_realworld_paste_exact(transcript, words_flat):
    frag = "multiplica por diez su produccion semanal"
    expect = _true_span(words_flat, frag)
    res, got = _trim(transcript, (54.0, 64.0), frag)
    _record("1_paste_exact", fragment=frag, expected=expect, got=got, summary=res.change_summary)
    assert got[0] == pytest.approx(expect[0], abs=0.5)
    assert got[1] == pytest.approx(expect[1], abs=0.5)


# ── Case 2: 1–2 differing words at the edges still resolves ──────────────────

def test_realworld_edge_differences(transcript, words_flat):
    true = _true_span(words_flat, "multiplica por diez su produccion semanal")
    frag = "multiplico por diez su produccion semanales"  # head + tail altered
    res, got = _trim(transcript, (54.0, 64.0), frag)
    _record("2_edge_differences", fragment=frag, expected=true, got=got, summary=res.change_summary)
    assert "no encontr" not in res.change_summary.lower()
    assert got[0] == pytest.approx(true[0], abs=0.5)
    assert got[1] == pytest.approx(true[1], abs=0.5)


# ── Case 3: fragment crosses the clip boundary → clip moves/extends ──────────

def test_realworld_crosses_boundary(transcript, words_flat):
    frag = ("el creador que aprende a delegar en la maquina "
            "multiplica por diez su produccion semanal")
    expect = _true_span(words_flat, frag)
    window = (57.0, 60.0)  # narrower than the fragment, which starts <57 and ends >60
    res, got = _trim(transcript, window, frag)
    _record("3_crosses_boundary", fragment=frag, window=window, expected=expect,
            got=got, summary=res.change_summary)
    assert got[0] < window[0]   # extended earlier than the original start
    assert got[1] > window[1]   # extended later than the original end
    assert got[0] == pytest.approx(expect[0], abs=0.5)
    assert got[1] == pytest.approx(expect[1], abs=0.5)


# ── Case 4: repeated phrase resolves to the occurrence nearest the clip ──────

def test_realworld_repeated_phrase_nearest(transcript, words_flat):
    phrase = "esto cambia todo"
    occ_a = _true_span(words_flat, phrase, occurrence=0)
    occ_b = _true_span(words_flat, phrase, occurrence=1)
    assert occ_a and occ_b and occ_b[0] > occ_a[0]  # fixture really repeats it
    # clip sits near occurrence B → must pick B, not the earlier A
    window = (occ_b[0] - 3.0, occ_b[1] + 3.0)
    res, got = _trim(transcript, window, phrase)
    _record("4_repeated_nearest", phrase=phrase, occ_a=occ_a, occ_b=occ_b,
            got=got, summary=res.change_summary)
    assert got[0] == pytest.approx(occ_b[0], abs=0.5)
    assert abs(got[0] - occ_b[0]) < abs(got[0] - occ_a[0])


# ── Case 5: a genuinely absent fragment does NOT trim ────────────────────────

def test_realworld_absent_no_trim(transcript):
    frag = "este fragmento inventado no aparece en ningun lugar del episodio jamas de los jamases"
    res, got = _trim(transcript, (54.0, 64.0), frag)
    _record("5_absent_no_trim", fragment=frag, got=got, summary=res.change_summary)
    assert got == (54.0, 64.0)               # unchanged
    assert "no encontr" in res.change_summary.lower()


# ── Flush evidence for human spot-check ──────────────────────────────────────

def test_zzz_write_evidence():
    """Runs last (alphabetical): persists captured spans for inspection."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "results.json").write_text(
        json.dumps(_EVIDENCE, ensure_ascii=False, indent=2)
    )
    log = ["brief real-world validation — resolved spans vs ground truth\n"]
    for e in _EVIDENCE:
        log.append(f"[{e['case']}] got={e.get('got')} expected="
                   f"{e.get('expected') or e.get('occ_b')} :: {e.get('summary')}")
    (OUT_DIR / "run.log").write_text("\n".join(log))
    assert len(_EVIDENCE) == 5  # all five cases recorded evidence
