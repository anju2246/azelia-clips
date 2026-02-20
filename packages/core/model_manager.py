"""Model manager - Singleton cache for expensive AI models."""

import torch
from rich.console import Console

from packages.core.config import settings

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


def preload_models():
    """Preload all models at startup for faster first-clip processing."""
    console.print("[blue]⏳ Preloading AI models...[/blue]")
    get_diarization_pipeline()
    console.print("[green]✓[/green] All models loaded and cached")


def clear_cache():
    """Clear model cache to free memory."""
    global _MODEL_CACHE
    _MODEL_CACHE.clear()
    console.print("[yellow]Model cache cleared[/yellow]")
