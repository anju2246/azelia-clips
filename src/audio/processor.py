"""Audio processing with AI-based voice separation and normalization using Demucs."""

import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()


def normalize_audio_with_demucs(
    input_video: Path | str,
    output_video: Path | str,
    model: str = "htdemucs",
) -> Path:
    """
    Normalize audio using Demucs voice separation.
    
    This separates vocals from the audio, normalizes each vocal track, 
    and remixes for balanced volume between speakers.
    
    Args:
        input_video: Path to input video file
        output_video: Path to output video file
        model: Demucs model to use (htdemucs is fastest)
    
    Returns:
        Path to output video with normalized audio
    """
    input_video = Path(input_video)
    output_video = Path(output_video)
    
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        
        # Step 1: Extract audio from video
        console.print("[blue]🎵 Extracting audio...[/blue]")
        audio_path = temp_path / "audio.wav"
        
        extract_cmd = [
            "ffmpeg", "-y", "-i", str(input_video),
            "-vn", "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2",
            str(audio_path)
        ]
        subprocess.run(extract_cmd, capture_output=True, check=True)
        
        # Step 2: Run Demucs to separate vocals (using cached model + GPU)
        console.print("[blue]🤖 Running Demucs AI separation...[/blue]")
        
        vocals_path = temp_path / "vocals.wav"
        other_path = temp_path / "no_vocals.wav"
        
        try:
            # Try using cached Demucs model with GPU
            from src.model_manager import get_demucs_model
            import torchaudio
            import torch
            
            model, apply_model = get_demucs_model()
            
            if model is not None and apply_model is not None:
                with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as p:
                    p.add_task("Separating voices with AI (GPU)...", total=None)
                    
                    # Load audio
                    wav, sr = torchaudio.load(str(audio_path))
                    
                    # Convert to model's sample rate if needed
                    if sr != model.samplerate:
                        wav = torchaudio.functional.resample(wav, sr, model.samplerate)
                    
                    # Ensure stereo
                    if wav.shape[0] == 1:
                        wav = wav.repeat(2, 1)
                    
                    # Move to same device as model
                    device = next(model.parameters()).device
                    wav = wav.to(device)
                    
                    # Apply model
                    with torch.no_grad():
                        sources = apply_model(model, wav[None], device=device)[0]
                    
                    # sources shape: [num_sources, channels, samples]
                    # htdemucs outputs 4 stems: ['drums', 'bass', 'other', 'vocals']
                    # Find vocals index from model.sources
                    source_names = model.sources  # e.g., ['drums', 'bass', 'other', 'vocals']
                    vocals_idx = source_names.index('vocals') if 'vocals' in source_names else -1
                    
                    if vocals_idx >= 0:
                        vocals = sources[vocals_idx].cpu()
                        # Sum all other sources for background (drums + bass + other)
                        other_indices = [i for i in range(len(source_names)) if i != vocals_idx]
                        if other_indices:
                            no_vocals = sum(sources[i].cpu() for i in other_indices)
                        else:
                            no_vocals = None
                    else:
                        # Fallback: assume first is vocals (for two-stem models)
                        vocals = sources[0].cpu()
                        no_vocals = sources[1].cpu() if sources.shape[0] > 1 else None
                    
                    # Save separated audio
                    torchaudio.save(str(vocals_path), vocals, model.samplerate)
                    if no_vocals is not None:
                        torchaudio.save(str(other_path), no_vocals, model.samplerate)
                    
                console.print("[green]✓[/green] Separation complete (GPU)")
            else:
                raise Exception("Model not available, falling back to subprocess")
                
        except Exception as e:
            console.print(f"[yellow]GPU separation failed ({e}), using subprocess...[/yellow]")
            
            # Fallback to subprocess
            with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as p:
                p.add_task("Separating voices with AI...", total=None)
                
                demucs_cmd = [
                    "python3", "-m", "demucs",
                    "--two-stems", "vocals",
                    "-n", model_name,
                    "-o", str(temp_path),
                    str(audio_path)
                ]
                
                result = subprocess.run(demucs_cmd, capture_output=True, text=True)
                
                if result.returncode != 0:
                    console.print(f"[yellow]Warning: Demucs failed, using fallback[/yellow]")
                    fallback_cmd = [
                        "ffmpeg", "-y", "-i", str(input_video),
                        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
                        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                        str(output_video)
                    ]
                    subprocess.run(fallback_cmd, capture_output=True, check=True)
                    return output_video
                
                # Find output files from subprocess
                vocals_path = temp_path / model_name / "audio" / "vocals.wav"
                other_path = temp_path / model_name / "audio" / "no_vocals.wav"
        
        if not vocals_path.exists():
            console.print(f"[yellow]Vocals not found at {vocals_path}[/yellow]")
            # Fallback
            fallback_cmd = [
                "ffmpeg", "-y", "-i", str(input_video),
                "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                str(output_video)
            ]
            subprocess.run(fallback_cmd, capture_output=True, check=True)
            return output_video
        
        # Step 4: Normalize vocals aggressively with voice EQ
        console.print("[blue]🔊 Normalizing and EQ-ing vocals...[/blue]")
        vocals_norm_path = temp_path / "vocals_normalized.wav"
        
        # Voice EQ chain:
        # - highpass=f=80: Remove rumble below 80Hz
        # - lowpass=f=12000: Remove harsh frequencies above 12kHz
        # - equalizer=f=3000:t=q:w=1:g=3: Boost 3kHz for voice clarity
        # - compand: Aggressive compression for level balancing
        # - loudnorm: Final normalization to broadcast standard
        norm_cmd = [
            "ffmpeg", "-y", "-i", str(vocals_path),
            "-af", "highpass=f=80,lowpass=f=12000,equalizer=f=3000:t=q:w=1:g=3,equalizer=f=200:t=q:w=1:g=2,compand=attacks=0.02:decays=0.2:points=-80/-80|-50/-20|-30/-10|-10/-5|0/-3:gain=5,loudnorm=I=-14:TP=-1:LRA=5",
            str(vocals_norm_path)
        ]
        subprocess.run(norm_cmd, capture_output=True, check=True)
        
        # Step 5: Mix normalized vocals with background (if any)
        console.print("[blue]🎛️ Remixing audio...[/blue]")
        mixed_audio_path = temp_path / "mixed.wav"
        
        if other_path.exists():
            # Mix vocals (louder) with background (quieter)
            mix_cmd = [
                "ffmpeg", "-y",
                "-i", str(vocals_norm_path),
                "-i", str(other_path),
                "-filter_complex", "[0:a]volume=1.0[v];[1:a]volume=0.3[o];[v][o]amix=inputs=2:duration=first[out]",
                "-map", "[out]",
                str(mixed_audio_path)
            ]
            subprocess.run(mix_cmd, capture_output=True, check=True)
        else:
            mixed_audio_path = vocals_norm_path
        
        # Step 6: Combine with video
        console.print("[blue]🎬 Combining with video...[/blue]")
        
        combine_cmd = [
            "ffmpeg", "-y",
            "-i", str(input_video),
            "-i", str(mixed_audio_path),
            "-map", "0:v",
            "-map", "1:a",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            str(output_video)
        ]
        subprocess.run(combine_cmd, capture_output=True, check=True)
    
    console.print(f"[green]✓[/green] Audio normalized with AI")
    return output_video


def process_video_with_audio_normalization(
    input_video: Path | str,
    output_video: Optional[Path | str] = None,
    use_ai: bool = True,
) -> Path:
    """
    Process video with audio normalization.
    
    Args:
        input_video: Path to input video
        output_video: Path to output video (optional, creates temp if not provided)
        use_ai: Whether to use AI (Demucs) or simple normalization
    
    Returns:
        Path to processed video
    """
    input_video = Path(input_video)
    
    if output_video is None:
        output_video = input_video.parent / f"{input_video.stem}_normalized{input_video.suffix}"
    output_video = Path(output_video)
    
    if use_ai:
        return normalize_audio_with_demucs(input_video, output_video)
    else:
        # Simple normalization without AI
        cmd = [
            "ffmpeg", "-y", "-i", str(input_video),
            "-af", "compand=attacks=0.05:decays=0.3:points=-80/-80|-45/-25|-20/-15|-5/-5|0/-3:gain=3,loudnorm=I=-16:TP=-1.5:LRA=7",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            str(output_video)
        ]
        subprocess.run(cmd, capture_output=True, check=True)
        return output_video
