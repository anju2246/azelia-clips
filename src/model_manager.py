"""Model manager - Singleton cache for expensive AI models."""

import torch
from rich.console import Console

from src.config import settings

console = Console()

# Global model cache
_MODEL_CACHE: dict = {}


def get_diarization_pipeline():
    """Get cached pyannote diarization pipeline."""
    global _MODEL_CACHE
    
    if "diarization" not in _MODEL_CACHE:
        console.print("[blue]🎙️ Loading speaker diarization model (first time)...[/blue]")
        
        from pyannote.audio import Pipeline
        
        hf_token = settings.hf_token
        
        # Workaround for PyTorch 2.6 weights_only=True default
        original_load = torch.load
        def patched_load(*args, **kwargs):
            kwargs['weights_only'] = False
            return original_load(*args, **kwargs)
        torch.load = patched_load
        
        try:
            pipeline = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1",
                use_auth_token=hf_token,
            )
        finally:
            torch.load = original_load
        
        # Use MPS (Metal) on Mac if available
        if torch.backends.mps.is_available():
            pipeline.to(torch.device("mps"))
            console.print("[green]✓[/green] Diarization using GPU (MPS)")
        elif torch.cuda.is_available():
            pipeline.to(torch.device("cuda"))
            console.print("[green]✓[/green] Diarization using GPU (CUDA)")
        
        _MODEL_CACHE["diarization"] = pipeline
        console.print("[green]✓[/green] Diarization model cached")
    
    return _MODEL_CACHE["diarization"]


def get_demucs_model():
    """Get cached Demucs model for voice separation."""
    global _MODEL_CACHE
    
    if "demucs" not in _MODEL_CACHE:
        console.print("[blue]🤖 Loading Demucs model (first time)...[/blue]")
        
        try:
            from demucs import pretrained
            from demucs.apply import apply_model
            
            # Load htdemucs (fastest model)
            model = pretrained.get_model("htdemucs")
            
            # Use MPS (Metal) on Mac if available
            if torch.backends.mps.is_available():
                model.to(torch.device("mps"))
                console.print("[green]✓[/green] Demucs using GPU (MPS)")
            elif torch.cuda.is_available():
                model.to(torch.device("cuda"))
                console.print("[green]✓[/green] Demucs using GPU (CUDA)")
            else:
                model.to(torch.device("cpu"))
            
            model.eval()
            
            _MODEL_CACHE["demucs"] = model
            _MODEL_CACHE["demucs_apply"] = apply_model
            console.print("[green]✓[/green] Demucs model cached")
            
        except ImportError:
            console.print("[yellow]Warning: Demucs not installed, will use subprocess[/yellow]")
            _MODEL_CACHE["demucs"] = None
    
    return _MODEL_CACHE.get("demucs"), _MODEL_CACHE.get("demucs_apply")


def preload_models():
    """Preload all models at startup for faster first-clip processing."""
    console.print("[blue]⏳ Preloading AI models...[/blue]")
    get_diarization_pipeline()
    get_demucs_model()
    console.print("[green]✓[/green] All models loaded and cached")


def clear_cache():
    """Clear model cache to free memory."""
    global _MODEL_CACHE
    _MODEL_CACHE.clear()
    console.print("[yellow]Model cache cleared[/yellow]")
