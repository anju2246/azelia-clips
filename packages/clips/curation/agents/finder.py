import json
from typing import List, Optional
from rich.console import Console

from packages.clips.transcription.transcriber import Transcript
from packages.core.llm_provider import get_llm
from packages.clips.curation.prompts import FINDER_SYSTEM
from packages.clips.curation.prompt_manager import PromptManager
from packages.clips.curation.models import FinderResponse, FinderCandidate, CurationConfig
from packages.clips.curation.signals import TextAnalyzer, AudioAnalyzer, StructuralAnalyzer

console = Console()

class FinderAgent:
    """
    Finder Agent: Scans transcripts and identifies potential clip candidates.
    Uses a Map-Reduce approach for long transcripts by splitting them into overlapping chunks.
    """
    def __init__(self, temperature: float = 0.3):
        self.temperature = temperature
        self._llm = get_llm()
        self.prompt_manager = PromptManager()
        self.text_analyzer = TextAnalyzer()
        self.audio_analyzer = AudioAnalyzer()
        self.structural_analyzer = StructuralAnalyzer()

    def _format_transcript(self, transcript: Transcript) -> str:
        """Format transcript with timestamps for LLM."""
        lines = []
        for seg in transcript.segments:
            timestamp = f"[{seg.start:.1f}s - {seg.end:.1f}s]"
            speaker = f"[{seg.speaker}]" if seg.speaker else ""
            lines.append(f"{timestamp} {speaker} {seg.text}")
        return "\n".join(lines)

    def _extract_signals_summary(self, transcript: Transcript) -> str:
        """Extract and format signals for LLM context."""
        lines = ["### High-Signal Moments Detected:"]
        
        # Text signals
        text_windows = self.text_analyzer.find_high_signal_windows(
            transcript, window_seconds=45, min_score=12
        )
        if text_windows:
            lines.append("\n**Text Signals:**")
            for start, end, sig in text_windows[:10]:
                patterns = ", ".join(sig.detected_patterns[:3]) if sig.detected_patterns else "none"
                lines.append(f"- [{start:.1f}s-{end:.1f}s] hook={sig.hook_score} story={sig.storytelling_score} | {patterns}")
        
        # Audio signals
        audio_windows = self.audio_analyzer.analyze_transcript_segments(transcript, window_seconds=45)
        high_energy = [(s, e, sig) for s, e, sig in audio_windows if sig.pacing_score >= 7]
        if high_energy:
            lines.append("\n**High-Energy Moments:**")
            for start, end, sig in high_energy[:5]:
                lines.append(f"- [{start:.1f}s-{end:.1f}s] WPS={sig.words_per_second:.1f} pacing={sig.pacing_score}")
        
        # Structural signals
        struct_windows = self.structural_analyzer.find_complete_segments(transcript, min_score=20)
        if struct_windows:
            lines.append("\n**Complete Segments:**")
            for start, end, sig in struct_windows[:5]:
                lines.append(f"- [{start:.1f}s-{end:.1f}s] completeness={sig.completeness_score} standalone={sig.standalone_score}")
        
        return "\n".join(lines)

    def _chunk_transcript(self, transcript: Transcript, max_chars: int = 6000, overlap_seconds: int = 120) -> List[Transcript]:
        """Split transcript into chunks that fit within LLM context windows."""
        chunks = []
        current_segments = []
        current_chars = 0
        
        for seg in transcript.segments:
            seg_text = f"[{seg.start:.1f}s - {seg.end:.1f}s] {seg.text}"
            seg_chars = len(seg_text)
            
            if current_chars + seg_chars > max_chars and current_segments:
                chunk_duration = current_segments[-1].end - current_segments[0].start
                chunk = Transcript(
                    segments=current_segments.copy(),
                    language=transcript.language,
                    duration=chunk_duration,
                    source_file=transcript.source_file,
                )
                chunks.append(chunk)
                
                # Setup next chunk with overlap
                overlap_start_time = current_segments[-1].end - overlap_seconds
                overlap_segments = [s for s in current_segments if s.start >= overlap_start_time]
                
                current_segments = overlap_segments.copy()
                current_chars = sum(len(f"[{s.start:.1f}s - {s.end:.1f}s] {s.text}") for s in current_segments)
            
            current_segments.append(seg)
            current_chars += seg_chars
        
        if current_segments:
            chunk_duration = current_segments[-1].end - current_segments[0].start
            chunk = Transcript(
                segments=current_segments.copy(),
                language=transcript.language,
                duration=chunk_duration,
                source_file=transcript.source_file,
            )
            chunks.append(chunk)
            
        return chunks

    def _deduplicate_candidates(self, candidates: List[FinderCandidate], overlap_threshold: float = 0.5) -> List[FinderCandidate]:
        """Remove duplicate candidates from overlapping chunks."""
        if len(candidates) <= 1:
            return candidates
            
        sorted_cands = sorted(candidates, key=lambda c: c.start_time)
        unique_cands = []
        
        for cand in sorted_cands:
            cand_duration = cand.end_time - cand.start_time
            if cand_duration <= 0:
                continue

            is_dup = False
            for i, existing in enumerate(unique_cands):
                exist_duration = existing.end_time - existing.start_time
                overlap_start = max(cand.start_time, existing.start_time)
                overlap_end = min(cand.end_time, existing.end_time)
                overlap_duration = max(0, overlap_end - overlap_start)
                
                c_ratio = overlap_duration / cand_duration
                e_ratio = overlap_duration / exist_duration if exist_duration > 0 else 0
                
                if c_ratio > overlap_threshold or e_ratio > overlap_threshold:
                    # Keep the longer one (or whatever heuristic)
                    if cand_duration > exist_duration:
                        unique_cands[i] = cand
                    is_dup = True
                    break
                    
            if not is_dup:
                unique_cands.append(cand)
                
        return unique_cands

    def find_candidates(
        self, 
        transcript: Transcript, 
        min_duration: int = 25, 
        max_duration: int = 90,
        config: Optional[CurationConfig] = None,
        progress_callback=None,
        pause_callback=None
    ) -> List[FinderCandidate]:
        """Runs the finder logic, handling chunking automatically."""
        config = config or CurationConfig()
        transcript_text = self._format_transcript(transcript)
        
        if len(transcript_text) <= 6000:
            chunks = [transcript]
        else:
            chunks = self._chunk_transcript(transcript)
            console.print(f"[dim]   Transcript split into {len(chunks)} chunks[/dim]")

        if progress_callback:
            progress_callback(0, len(chunks), f"Finder: Initializing {len(chunks)} chunks...")

        all_candidates = []
        
        for i, chunk in enumerate(chunks):
            if pause_callback and pause_callback():
                console.print(f"[yellow]   Finder paused at chunk {i+1}/{len(chunks)}[/yellow]")
                break
                
            if progress_callback:
                progress_callback(i + 1, len(chunks), f"Finder: Chunk {i+1}/{len(chunks)}")
                
            signals_summary = self._extract_signals_summary(chunk)
            chunk_text = self._format_transcript(chunk)
            
            system_prompt = FINDER_SYSTEM.format(
                podcast_name=config.podcast_name,
                intelligence_addendum=config.get_intelligence_prompt_addendum()
            )
            
            finder_template = self.prompt_manager.get_finder_prompt()
            finder_prompt = finder_template.format(
                min_duration=min_duration,
                max_duration=max_duration,
                language=transcript.language,
                signals_summary=signals_summary,
                transcript=chunk_text,
            )
            
            # Using LLM provider's response_format capability for Pydantic validation
            try:
                response = self._llm.chat(
                    system_prompt=system_prompt,
                    user_message=finder_prompt,
                    temperature=self.temperature,
                    response_format=FinderResponse
                )
                
                if isinstance(response, str):
                    # Provider didn't natively support structure, parse manually (fallback)
                    # We should parse JSON manually and construct the Pydantic object
                    import re
                    json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", response)
                    raw_json = json_match.group(1).strip() if json_match else response.strip()
                    parsed_dict = json.loads(raw_json)
                    response_obj = FinderResponse(**parsed_dict)
                else:
                    # Depending on instructor/llm_provider implementation, it might directly return the object
                    response_obj = response if isinstance(response, FinderResponse) else FinderResponse(**json.loads(response.model_dump_json()))

                all_candidates.extend(response_obj.candidates)
            except Exception as e:
                console.print(f"[red]Failed to process chunk {i+1} with Finder: {e}[/red]")
                
        return self._deduplicate_candidates(all_candidates)
