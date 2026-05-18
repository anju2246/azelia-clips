import json
from typing import List, Optional
from rich.console import Console

from packages.clips.transcription.transcriber import Transcript
from packages.core.llm_provider import get_llm
from packages.clips.curation.prompts import RANKER_SYSTEM, CAPTION_GENERATOR_SYSTEM
from packages.clips.curation.prompt_manager import PromptManager
from packages.clips.curation.models import CriticClip, RankerResponse, CuratedClip, CaptionResponse, CurationConfig, ViralityScore
from packages.clips.curation.signals import TextAnalyzer, AudioAnalyzer, StructuralAnalyzer

console = Console()

class RankerAgent:
    """
    Ranker Agent: Assigns final 10-dimension virality scores to approved clips.
    Also handles generating individual social media captions sequentially.
    """
    def __init__(self, temperature: float = 0.3):
        self.temperature = temperature
        self._llm = get_llm()
        self.prompt_manager = PromptManager()
        self.text_analyzer = TextAnalyzer()
        self.audio_analyzer = AudioAnalyzer()
        self.structural_analyzer = StructuralAnalyzer()

    def _format_transcript(self, transcript: Transcript) -> str:
        lines = []
        for seg in transcript.segments:
            timestamp = f"[{seg.start:.1f}s - {seg.end:.1f}s]"
            speaker = f"[{seg.speaker}]" if seg.speaker else ""
            lines.append(f"{timestamp} {speaker} {seg.text}")
        return "\n".join(lines)

    def _extract_signals_summary(self, transcript: Transcript) -> str:
        lines = ["### High-Signal Moments Detected:"]
        
        text_windows = self.text_analyzer.find_high_signal_windows(transcript, window_seconds=45, min_score=12)
        if text_windows:
            lines.append("\n**Text Signals:**")
            for start, end, sig in text_windows[:10]:
                patterns = ", ".join(sig.detected_patterns[:3]) if sig.detected_patterns else "none"
                lines.append(f"- [{start:.1f}s-{end:.1f}s] hook={sig.hook_score} story={sig.storytelling_score} | {patterns}")
        
        audio_windows = self.audio_analyzer.analyze_transcript_segments(transcript, window_seconds=45)
        high_energy = [(s, e, sig) for s, e, sig in audio_windows if sig.pacing_score >= 7]
        if high_energy:
            lines.append("\n**High-Energy Moments:**")
            for start, end, sig in high_energy[:5]:
                lines.append(f"- [{start:.1f}s-{end:.1f}s] WPS={sig.words_per_second:.1f} pacing={sig.pacing_score}")
        
        struct_windows = self.structural_analyzer.find_complete_segments(transcript, min_score=20)
        if struct_windows:
            lines.append("\n**Complete Segments:**")
            for start, end, sig in struct_windows[:5]:
                lines.append(f"- [{start:.1f}s-{end:.1f}s] completeness={sig.completeness_score} standalone={sig.standalone_score}")
        
        return "\n".join(lines)

    def _extract_clip_text(self, transcript: Transcript, start: float, end: float) -> str:
        text = []
        for seg in transcript.segments:
            if seg.end >= start and seg.start <= end:
                text.append(seg.text)
        return " ".join(text)

    def _fetch_ic_signals_for_config(self, config: CurationConfig) -> List[str]:
        """Read creator_self signals from the user's LOCAL youtube_shorts.db
        and convert them into prompt-ready hints for the Ranker.

        These signals come from the user's own past YouTube Shorts, analyzed
        with their own Anthropic key in the /api/analytics/youtube/extract-creator-signals
        flow. Nothing leaves the machine.

        Returns an empty list when:
        - No YouTube was connected (no DB)
        - Sync happened but extract-creator-signals never ran
        - Patterns exist but for a different user_id
        """
        try:
            import os
            import sqlite3
            import json as _json

            # Same path as server/routes/analytics.py:_get_yt_db
            db_path = os.path.join(
                os.path.dirname(__file__), "..", "..", "..", "..",
                "server", "data", "youtube_shorts.db",
            )
            if not os.path.exists(db_path):
                return []
            conn = sqlite3.connect(db_path)
            # user_id = 'local' in single-user MVP. config.user_cohort_hash
            # may carry a different identifier in future multi-user mode.
            user_id = config.user_cohort_hash or "local"
            cur = conn.execute(
                """
                SELECT hook_type, emotional_charge, duration_bucket, topic_tag,
                       pattern_json, performance_premium, confidence
                FROM creator_signals
                WHERE user_id = ? AND performance_premium >= 1.0
                ORDER BY performance_premium * confidence DESC
                LIMIT 8
                """,
                (user_id,),
            )
            rows = cur.fetchall()
            conn.close()
        except Exception as e:
            console.print(f"[dim]   creator_signals fetch skipped ({type(e).__name__}: {e})[/dim]")
            return []

        hints: List[str] = []
        for hook, emotion, duration, topic, raw_pat, premium, conf in rows:
            premium = float(premium or 1.0)
            conf = float(conf or 0.5)
            bits = []
            if hook:
                bits.append(f"hook '{hook}'")
            if emotion:
                bits.append(f"feel {emotion}")
            if duration:
                bits.append(f"~{duration}")
            if topic:
                bits.append(f"about {topic}")
            if not bits:
                continue
            hints.append(
                f"CREATOR SELF · {' / '.join(bits)} outperforms your median (×{premium:.2f}, conf={conf:.2f})"
            )
        return hints

    def _build_ranker_addendum(self, config: CurationConfig) -> str:
        """Combine podcast context + IC signal hints into the system addendum."""
        parts: List[str] = []
        ctx = config.get_podcast_context_block()
        if ctx:
            parts.append(ctx)
        ic_hints = self._fetch_ic_signals_for_config(config)
        if ic_hints:
            parts.append("## IC Cascade signals")
            parts.append("Patterns learned from this creator (CREATOR SELF) take precedence over niche signals (NICHE SIGNAL).")
            parts.extend(f"- {h}" for h in ic_hints)
        if config.high_retention_patterns:
            parts.append("## Proven high-retention patterns (local intelligence):")
            parts.extend(f"- {p}" for p in config.high_retention_patterns)
        return "\n".join(parts)

    def rank_clips(
        self,
        approved_clips: List[CriticClip],
        transcript: Transcript,
        top_n: int = 5,
        config: Optional[CurationConfig] = None,
    ) -> List[CuratedClip]:
        """Assigns detailed scores to the approved clips."""
        if not approved_clips:
            return []

        config = config or CurationConfig()
        transcript_text = self._format_transcript(transcript)
        signals_summary = self._extract_signals_summary(transcript)

        approved_json = json.dumps([c.model_dump() for c in approved_clips], indent=2)

        ranker_template = self.prompt_manager.get_ranker_prompt()
        ranker_prompt = ranker_template.format(
            approved_json=approved_json,
            transcript=transcript_text,
            signals_summary=signals_summary,
            top_n=top_n
        )

        try:
            from packages.core.taxonomy import language_label as _lang_label
            ranker_system_formatted = RANKER_SYSTEM.format(
                top_n=top_n,
                intelligence_addendum=self._build_ranker_addendum(config),
                output_language=_lang_label(config.language),
            )
            response_raw = self._llm.chat(
                system_prompt=ranker_system_formatted,
                user_message=ranker_prompt,
                temperature=self.temperature,
                response_format=RankerResponse
            )
            
            if isinstance(response_raw, str):
                import re
                json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", response_raw)
                raw_json = json_match.group(1).strip() if json_match else response_raw.strip()
                parsed_dict = json.loads(raw_json)
                response_obj = RankerResponse(**parsed_dict)
            else:
                response_obj = response_raw if isinstance(response_raw, RankerResponse) else RankerResponse(**json.loads(response_raw.model_dump_json()))
                
            return response_obj.ranked_clips
            
        except Exception as e:
            console.print(f"[red]Failed to run RankerAgent: {e}[/red]")
            console.print("[yellow]Fallback: returning approved clips with baseline score=50.[/yellow]")
            return [
                CuratedClip(
                    start_time=c.start_time, end_time=c.end_time,
                    title=c.title or "", summary=c.summary or "",
                    virality_score=ViralityScore(
                        hook_strength=5, quotability=5, storytelling=5,
                        controversy=5, energy_level=5, pacing=5,
                        emotional_arc=5, standalone_clarity=5,
                        segment_completeness=5, optimal_duration=5,
                    ),
                    category="insight",
                    pending_review=True,
                    review_reason="Ranker agent failed — scores are baseline estimates",
                ) for c in approved_clips
            ]

    def generate_captions(
        self,
        clips: List[CuratedClip],
        transcript: Transcript,
        episode_number: int = 0,
        config: Optional[CurationConfig] = None
    ) -> List[CuratedClip]:
        """Generates viral social media captions for individual clips sequentially."""
        if not clips:
            return []
            
        config = config or CurationConfig()
        caption_template = self.prompt_manager.get_caption_prompt()
        
        from packages.core.taxonomy import language_label as _lang_label
        system_prompt = CAPTION_GENERATOR_SYSTEM.format(
            podcast_name=config.podcast_name,
            podcast_name_nospace=config.podcast_name.replace(" ", ""),
            output_language=_lang_label(config.language),
        )
        
        # SEQUENTIAL execution is critical to avoid API rate limits
        for i, clip in enumerate(clips):
            clip_text = self._extract_clip_text(transcript, clip.start_time, clip.end_time)
            
            prompt = caption_template.format(
                episode_number=episode_number,
                clip_title=clip.title,
                clip_summary=clip.summary,
                clip_category=clip.category,
                clip_text=clip_text,
                podcast_name=config.podcast_name,
            )
            
            try:
                response = self._llm.chat(
                    system_prompt=system_prompt,
                    user_message=prompt,
                    temperature=0.7,  # Higher temp for creativity
                    response_format=CaptionResponse
                )
                
                if isinstance(response, str):
                    import re
                    json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", response)
                    raw_json = json_match.group(1).strip() if json_match else response.strip()
                    parsed_dict = json.loads(raw_json)
                    cap_data = CaptionResponse(**parsed_dict)
                else:
                    cap_data = response if isinstance(response, CaptionResponse) else CaptionResponse(**json.loads(response.model_dump_json()))
                
                clip.social_caption = cap_data.caption
                clip.caption_hashtags = cap_data.hashtags
            except Exception as e:
                console.print(f"[yellow]Failed to generate caption for clip {i+1}: {e}[/yellow]")
                
        return clips
