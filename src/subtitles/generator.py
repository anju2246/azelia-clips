"""Generate styled .ASS subtitles from transcripts."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from src.asr.transcriber import Transcript


@dataclass
class SubtitleStyle:
    """ASS subtitle style configuration."""
    name: str = "Default"
    font_name: str = "Arial Bold"
    font_size: int = 48
    primary_color: str = "&H00FFFFFF"  # White (ABGR format)
    secondary_color: str = "&H0000FFFF"  # Yellow for highlights
    outline_color: str = "&H00000000"  # Black outline
    back_color: str = "&H80000000"  # Semi-transparent black
    bold: bool = True
    outline: int = 3
    shadow: int = 2
    alignment: int = 2  # Bottom center
    margin_v: int = 50  # Vertical margin from bottom

    # Hola, esto es una nota que dejo a mi yo futuro, ahora estoy revisando el código, la IA está intentando
    # autocompletar lo que escribo. 


# Preset styles
STYLES = {
    "hormozi": SubtitleStyle(
        name="Hormozi",
        font_name="Impact",
        font_size=56,
        primary_color="&H00FFFFFF",
        secondary_color="&H0000D4FF",  # Orange highlight
        outline=4,
        shadow=0,
    ),
    "mrbeast": SubtitleStyle(
        name="MrBeast",
        font_name="Bebas Neue",
        font_size=64,
        primary_color="&H00FFFFFF",
        secondary_color="&H0000FF00",  # Green highlight
        outline=5,
        shadow=3,
    ),
    "minimal": SubtitleStyle(
        name="Minimal",
        font_name="Helvetica Neue",
        font_size=42,
        primary_color="&H00FFFFFF",
        outline=2,
        shadow=0,
        margin_v=80,
    ),
    "podcast": SubtitleStyle(
        name="Podcast",
        font_name="Montserrat Bold",
        font_size=52,
        primary_color="&H00FFFFFF",
        secondary_color="&H00FFE100",  # Yellow highlight
        outline=3,
        shadow=1,
    ),
    "splitscreen": SubtitleStyle(
        name="SplitScreen",
        font_name="Montserrat Bold",
        font_size=54,
        primary_color="&H00FFFFFF",
        secondary_color="&H00FFE100",  # Yellow highlight
        outline=3,
        shadow=1,
        alignment=2,  # Bottom center
        margin_v=620,  # Position at boundary (1920 - 1312 = 608, plus some offset)
    ),
}


class SubtitleGenerator:
    """Generate ASS subtitles with word-by-word animation."""

    def __init__(self, style: SubtitleStyle | str = "podcast"):
        if isinstance(style, str):
            self.style = STYLES.get(style, STYLES["podcast"])
        else:
            self.style = style

    def _format_time(self, seconds: float) -> str:
        """Convert seconds to ASS time format (h:mm:ss.cc)."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        centisecs = int((seconds % 1) * 100)
        return f"{hours}:{minutes:02d}:{secs:02d}.{centisecs:02d}"

    def _generate_header(self) -> str:
        """Generate ASS file header with styles."""
        s = self.style
        return f"""[Script Info]
Title: Celia Clips Subtitles
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: {s.name},{s.font_name},{s.font_size},{s.primary_color},{s.secondary_color},{s.outline_color},{s.back_color},{int(s.bold)},0,0,0,100,100,0,0,1,{s.outline},{s.shadow},{s.alignment},40,40,{s.margin_v},1
Style: Highlight,{s.font_name},{s.font_size},{s.secondary_color},{s.primary_color},{s.outline_color},{s.back_color},{int(s.bold)},0,0,0,100,100,0,0,1,{s.outline},{s.shadow},{s.alignment},40,40,{s.margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    def generate_word_by_word(
        self,
        transcript: Transcript,
        output_path: Path | str,
        words_per_line: int = 3,
        animation: str = "highlight",  # highlight, karaoke, or box
    ) -> Path:
        """
        Generate ASS subtitles with word-by-word animation.

        Args:
            transcript: Transcript with word-level timestamps
            output_path: Output .ass file path
            words_per_line: Max words to show per subtitle line
            animation: Animation style (highlight, karaoke, box)

        Returns:
            Path to generated .ass file
        """
        output_path = Path(output_path)
        lines = [self._generate_header()]

        # Collect all words with timing
        all_words = []
        for seg in transcript.segments:
            for word in seg.words:
                all_words.append(word)

        if not all_words:
            # Fallback to sentence-based if no word-level timestamps
            return self.generate_sentence_based(transcript, output_path)

        # Group words into subtitle events
        for i in range(0, len(all_words), words_per_line):
            group = all_words[i:i + words_per_line]
            if not group:
                continue

            group_start = group[0].start
            group_end = group[-1].end

            if animation == "highlight":
                # Show each word individually with highlight color
                for j, word in enumerate(group):
                    # Build text with current word highlighted
                    text_parts = []
                    for k, w in enumerate(group):
                        if k == j:
                            # Current word: highlighted color with scale
                            text_parts.append(f"{{\\c{self.style.secondary_color}\\fscx110\\fscy110}}{w.word}{{\\c{self.style.primary_color}\\fscx100\\fscy100}}")
                        else:
                            text_parts.append(w.word)

                    text = " ".join(text_parts)
                    start_time = self._format_time(word.start)
                    end_time = self._format_time(word.end)

                    lines.append(
                        f"Dialogue: 0,{start_time},{end_time},{self.style.name},,0,0,0,,{text}"
                    )

            elif animation == "karaoke":
                # Progressive reveal using karaoke effect
                text_parts = []
                for word in group:
                    word_duration = max(1, int((word.end - word.start) * 100))
                    text_parts.append(f"{{\\kf{word_duration}}}{word.word}")

                text = " ".join(text_parts)
                start_time = self._format_time(group_start)
                end_time = self._format_time(group_end)

                lines.append(
                    f"Dialogue: 0,{start_time},{end_time},{self.style.name},,0,0,0,,{text}"
                )

            elif animation == "box":
                # Word box effect: box around current word
                for j, word in enumerate(group):
                    text_parts = []
                    for k, w in enumerate(group):
                        if k == j:
                            # Current word with box effect
                            text_parts.append(f"{{\\bord0\\shad0\\3c{self.style.secondary_color}\\4c{self.style.secondary_color}\\xbord8\\ybord4}}{w.word}{{\\bord{self.style.outline}\\shad{self.style.shadow}}}")
                        else:
                            text_parts.append(w.word)

                    text = " ".join(text_parts)
                    start_time = self._format_time(word.start)
                    end_time = self._format_time(word.end)

                    lines.append(
                        f"Dialogue: 0,{start_time},{end_time},{self.style.name},,0,0,0,,{text}"
                    )

            elif animation == "cumulative":
                # Cumulative: words appear one by one and stay on screen
                # Example: "Hello" → "Hello world" → "Hello world today"
                for j, word in enumerate(group):
                    # Build text with all words up to current one
                    # Current word is highlighted
                    text_parts = []
                    for k in range(j + 1):
                        w = group[k]
                        if k == j:
                            # Current word: highlighted
                            text_parts.append(f"{{\\c{self.style.secondary_color}\\fscx110\\fscy110}}{w.word}{{\\c{self.style.primary_color}\\fscx100\\fscy100}}")
                        else:
                            # Previous words: normal
                            text_parts.append(w.word)
                    
                    text = " ".join(text_parts)
                    start_time = self._format_time(word.start)
                    # End at next word start, or group end for last word
                    if j < len(group) - 1:
                        end_time = self._format_time(group[j + 1].start)
                    else:
                        end_time = self._format_time(group_end)
                    
                    lines.append(
                        f"Dialogue: 0,{start_time},{end_time},{self.style.name},,0,0,0,,{text}"
                    )

            else:
                # Simple: just show all words
                text = " ".join([w.word for w in group])
                start_time = self._format_time(group_start)
                end_time = self._format_time(group_end)

                lines.append(
                    f"Dialogue: 0,{start_time},{end_time},{self.style.name},,0,0,0,,{text}"
                )

        # Write file
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        return output_path

    def generate_sentence_based(
        self,
        transcript: Transcript,
        output_path: Path | str,
    ) -> Path:
        """
        Generate ASS subtitles with sentence-level timing.

        Simpler alternative to word-by-word for faster processing.
        """
        output_path = Path(output_path)
        lines = [self._generate_header()]

        for seg in transcript.segments:
            start_time = self._format_time(seg.start)
            end_time = self._format_time(seg.end)

            # Clean and format text
            text = seg.text.strip()
            if not text:
                continue

            lines.append(
                f"Dialogue: 0,{start_time},{end_time},{self.style.name},,0,0,0,,{text}"
            )

        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        return output_path


def generate_subtitles(
    transcript: Transcript | str,
    output_path: Path | str,
    style: str = "podcast",
    mode: Literal["word", "sentence"] = "sentence",
) -> Path:
    """
    Convenience function to generate subtitles.

    Args:
        transcript: Transcript object or path to JSON
        output_path: Output .ass file path
        style: Style preset (hormozi, mrbeast, minimal, podcast)
        mode: Generation mode (word-by-word or sentence-based)

    Returns:
        Path to generated file
    """
    if isinstance(transcript, (str, Path)):
        transcript = Transcript.load(Path(transcript))

    generator = SubtitleGenerator(style=style)

    if mode == "word":
        return generator.generate_word_by_word(transcript, output_path)
    else:
        return generator.generate_sentence_based(transcript, output_path)
