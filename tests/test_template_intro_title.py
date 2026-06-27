"""T13 — Hook title: a title card on screen for the first N seconds, before the
word captions start. Text comes from the clip's curated title; the template only
controls style/duration/position. Verified at the .ass level (no FFmpeg)."""

from packages.clips.subtitles.generator import SubtitleGenerator, STYLES
from packages.clips.templates.models import IntroTitleSpec
from packages.clips.transcription.transcriber import Segment, Transcript, Word


def _transcript() -> Transcript:
    # Hook is spoken in the first ~3.5s; real content starts at 5s.
    words = [
        Word("Hola", 0.5, 1.0), Word("mundo", 1.0, 1.5), Word("esto", 1.5, 2.0),
        Word("es", 2.0, 2.5), Word("el", 2.5, 3.0), Word("hook", 3.0, 3.5),
        Word("y", 5.0, 5.3), Word("ahora", 5.3, 5.8), Word("captions", 5.8, 6.3),
    ]
    seg = Segment(text="hook y ahora captions", start=0.5, end=6.3, words=words)
    return Transcript(segments=[seg], duration=6.3)


def _ass_time_to_seconds(t: str) -> float:
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def _dialogues(path) -> list[tuple[str, str, str]]:
    """(start, end, text) per Dialogue line."""
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("Dialogue:"):
            parts = line.split(",", 9)
            out.append((parts[1].strip(), parts[2].strip(), parts[9]))
    return out


def _gen(tmp, **kwargs):
    out = tmp / "subs.ass"
    SubtitleGenerator(style=STYLES["splitscreen"]).generate_word_by_word(
        _transcript(), out, words_per_line=3, animation="cumulative", **kwargs
    )
    return out


def test_intro_title_emitted_with_duration(tmp_path):
    spec = IntroTitleSpec(enabled=True, duration_s=4.0)
    out = _gen(tmp_path, intro_title=spec, clip_title="Mi Gran Hook")
    title = [d for d in _dialogues(out) if "Mi Gran Hook" in d[2]]
    assert len(title) == 1, "exactly one title event expected"
    assert _ass_time_to_seconds(title[0][0]) == 0.0
    assert _ass_time_to_seconds(title[0][1]) == 4.0


def test_empty_clip_title_emits_no_intro(tmp_path):
    spec = IntroTitleSpec(enabled=True, duration_s=4.0)
    with_empty = _gen(tmp_path, intro_title=spec, clip_title="   ")
    baseline = _gen(tmp_path, intro_title=None, clip_title="")
    assert with_empty.read_text() == baseline.read_text()


def test_delay_captions_offsets_first_subtitle(tmp_path):
    spec = IntroTitleSpec(enabled=True, duration_s=4.0, delay_captions=True)
    out = _gen(tmp_path, intro_title=spec, clip_title="Mi Gran Hook")
    caption_starts = [
        _ass_time_to_seconds(s)
        for (s, _e, text) in _dialogues(out)
        if "Mi Gran Hook" not in text
    ]
    assert caption_starts, "captions should still be emitted"
    assert min(caption_starts) >= 4.0


def test_delay_captions_false_keeps_early_captions(tmp_path):
    spec = IntroTitleSpec(enabled=True, duration_s=4.0, delay_captions=False)
    out = _gen(tmp_path, intro_title=spec, clip_title="Mi Gran Hook")
    caption_starts = [
        _ass_time_to_seconds(s)
        for (s, _e, text) in _dialogues(out)
        if "Mi Gran Hook" not in text
    ]
    assert min(caption_starts) < 4.0, "without delay, early captions stay"


def test_intro_title_disabled_keeps_ass_unchanged(tmp_path):
    disabled = _gen(tmp_path, intro_title=IntroTitleSpec(enabled=False), clip_title="x")
    baseline = _gen(tmp_path)
    assert disabled.read_text() == baseline.read_text()
