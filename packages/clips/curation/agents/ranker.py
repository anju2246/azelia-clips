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

    def rank_clips(
        self, 
        approved_clips: List[CriticClip], 
        transcript: Transcript,
        top_n: int = 5
    ) -> List[CuratedClip]:
        """Assigns detailed scores to the approved clips."""
        if not approved_clips:
            return []
            
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
            response_raw = self._llm.chat(
                system_prompt=RANKER_SYSTEM,
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
        
        system_prompt = CAPTION_GENERATOR_SYSTEM.format(
            podcast_name=config.podcast_name,
            podcast_name_nospace=config.podcast_name.replace(" ", "")
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
